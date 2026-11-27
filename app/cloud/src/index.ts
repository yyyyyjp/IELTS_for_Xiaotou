/**
 * 小头雅思 · Cloudflare Worker 统一入口（多用户 GitHub OAuth + 邀请码 + D1 + R2 + Static Assets）。
 *
 * 数据隔离规则：
 * - 强制登录：除 /api/health、/api/auth/* 与公共只读离线词典/音频外，所有接口均校验 JWT 且要求 status='active'。
 * - 严格按 user_id 隔离：packs、vocab、sessions、attempts 全部独立归属各用户，互不可见。
 * - 管理员（ADMIN_GITHUB_LOGIN，默认 yyyyyjp）：首次登录自动激活为 admin 并接管存量 u_admin 数据，可管理邀请码。
 */

import {
  extractBearer,
  generateInviteCode,
  getCookie,
  randomHex,
  signJwt,
  userRowToPublic,
  verifyJwt,
  type AuthUser,
} from './auth'
import { lookupInD1 } from './dict'
import {
  buildPackFromExportData,
  buildPromptText,
  extractJsonObject,
  normalizeAnalysis,
  normalizeLexEntry,
  summarizeAnalysis,
  validateAnalysis,
} from './packImporter'

export interface Env {
  ASSETS: Fetcher
  DB: D1Database
  BUCKET: R2Bucket
  GITHUB_CLIENT_ID?: string
  GITHUB_CLIENT_SECRET?: string
  JWT_SECRET?: string
  ADMIN_GITHUB_LOGIN?: string
}

const VALID_STATES = new Set(['new', 'learning', 'review', 'suspended'])
const ADMIN_USER_ID = 'u_admin'

function json(data: unknown, status = 200, extraHeaders: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      ...extraHeaders,
    },
  })
}

function nowSec(): number {
  return Math.floor(Date.now() / 1000)
}

function withCors(req: Request, res: Response): Response {
  const origin = req.headers.get('origin')
  if (!origin) return res
  const headers = new Headers(res.headers)
  headers.set('Access-Control-Allow-Origin', origin)
  headers.set('Access-Control-Allow-Methods', 'GET,POST,PATCH,DELETE,OPTIONS')
  headers.set('Access-Control-Allow-Headers', 'Content-Type,Authorization')
  return new Response(res.body, {
    status: res.status,
    statusText: res.statusText,
    headers,
  })
}

function safeJsonParse<T>(raw: unknown, fallback: T): T {
  if (typeof raw !== 'string' || !raw) return fallback
  try {
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}

async function resolveAuthUser(req: Request, env: Env): Promise<AuthUser | null> {
  const secret = (env.JWT_SECRET ?? '').trim()
  if (!secret) return null
  const token = extractBearer(req)
  if (!token) return null
  const claims = await verifyJwt(token, secret)
  if (!claims) return null
  const row = await env.DB.prepare('SELECT * FROM users WHERE id=?')
    .bind(claims.sub)
    .first<Record<string, unknown>>()
  if (!row) return null
  return userRowToPublic(row)
}

async function requireActiveUser(
  req: Request,
  env: Env,
): Promise<{ user: AuthUser; error: null } | { user: null; error: Response }> {
  const user = await resolveAuthUser(req, env)
  if (!user) {
    return { user: null, error: json({ detail: '请先登录 GitHub 账号' }, 401) }
  }
  if (user.status !== 'active') {
    return { user: null, error: json({ detail: '账号尚未激活，请先填写邀请码' }, 403) }
  }
  return { user, error: null }
}

async function requireAdmin(
  req: Request,
  env: Env,
): Promise<{ user: AuthUser; error: null } | { user: null; error: Response }> {
  const res = await requireActiveUser(req, env)
  if (res.error) return res
  if (res.user.role !== 'admin') {
    return { user: null, error: json({ detail: '需要管理员权限' }, 403) }
  }
  return res
}

function vocabRowOut(r: Record<string, unknown>) {
  return {
    id: Number(r.id),
    lemma: String(r.lemma),
    word: String(r.word),
    gloss: String(r.gloss ?? ''),
    pos: String(r.pos ?? ''),
    phonetic: String(r.phonetic ?? ''),
    note: String(r.note ?? ''),
    tags: safeJsonParse(r.tags, []),
    contexts: safeJsonParse(r.contexts, []),
    source: String(r.source ?? ''),
    state: String(r.state ?? 'new'),
    dueAt: Number(r.due_at ?? 0),
    due: String(r.state) !== 'suspended' && Number(r.due_at ?? 0) <= nowSec(),
    intervalDays: Number(r.interval_days ?? 0),
    ease: Number(r.ease ?? 2.4),
    reps: Number(r.reps ?? 0),
    lapses: Number(r.lapses ?? 0),
    lastReviewedAt: Number(r.last_reviewed_at ?? 0),
    createdAt: Number(r.created_at ?? 0),
    updatedAt: Number(r.updated_at ?? 0),
    deletedAt: Number(r.deleted_at ?? 0),
    audioUrl: '',
    audioCached: false,
  }
}

function mergeContexts(a: unknown[], b: unknown[]): unknown[] {
  const out: unknown[] = []
  const seen = new Set<string>()
  for (const item of [...a, ...b]) {
    if (!item || typeof item !== 'object') continue
    const c = item as Record<string, unknown>
    const key = `${c.packId ?? ''}|${c.sentenceId ?? ''}|${c.en ?? ''}`
    if (key === '||' || seen.has(key)) continue
    seen.add(key)
    out.push(c)
  }
  return out
}

async function applyVocabItem(
  db: D1Database,
  userId: string,
  item: Record<string, unknown>,
  serverNow: number,
): Promise<boolean> {
  const lemma = String(item.lemma ?? item.word ?? '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .slice(0, 80)
  if (!lemma) return false
  const state = VALID_STATES.has(String(item.state)) ? String(item.state) : 'new'
  const incUpdated = Number(item.updatedAt ?? 0) || serverNow
  const incCreated = Number(item.createdAt ?? 0) || incUpdated
  const incTags = Array.isArray(item.tags) ? item.tags.map(String) : []
  const incContexts = Array.isArray(item.contexts) ? item.contexts : []
  const ease = Math.max(1.3, Math.min(3.0, Number(item.ease ?? 2.4) || 2.4))

  const row = await db
    .prepare('SELECT * FROM vocab WHERE user_id=? AND lemma=?')
    .bind(userId, lemma)
    .first<Record<string, unknown>>()

  if (!row) {
    await db
      .prepare(
        'INSERT INTO vocab(user_id,lemma,word,gloss,pos,phonetic,note,tags,contexts,source,state,' +
          'due_at,interval_days,ease,reps,lapses,last_reviewed_at,created_at,updated_at,deleted_at)' +
          ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
      )
      .bind(
        userId,
        lemma,
        String(item.word || lemma),
        String(item.gloss ?? ''),
        String(item.pos ?? ''),
        String(item.phonetic ?? ''),
        String(item.note ?? ''),
        JSON.stringify(Array.from(new Set(incTags))),
        JSON.stringify(mergeContexts([], incContexts)),
        String(item.source ?? ''),
        state,
        Number(item.dueAt ?? 0) || incCreated,
        Number(item.intervalDays ?? 0),
        ease,
        Math.max(0, Number(item.reps ?? 0)),
        Math.max(0, Number(item.lapses ?? 0)),
        Number(item.lastReviewedAt ?? 0),
        incCreated,
        Math.max(incUpdated, serverNow),
        Number(item.deletedAt ?? 0),
      )
      .run()
    return true
  }

  const oldTags = safeJsonParse<string[]>(row.tags, [])
  const oldContexts = safeJsonParse<unknown[]>(row.contexts, [])
  const mergedTags = Array.from(new Set([...oldTags, ...incTags]))
  const mergedContexts = mergeContexts(oldContexts, incContexts)

  if (incUpdated >= Number(row.updated_at ?? 0)) {
    const newUpdated = Math.max(incUpdated, serverNow)
    await db
      .prepare(
        'UPDATE vocab SET word=?,gloss=?,pos=?,phonetic=?,note=?,tags=?,contexts=?,source=?,' +
          'state=?,due_at=?,interval_days=?,ease=?,reps=?,lapses=?,last_reviewed_at=?,' +
          'updated_at=?,deleted_at=? WHERE id=? AND user_id=?',
      )
      .bind(
        String(item.word || row.word || lemma),
        String(item.gloss ?? '') !== '' ? String(item.gloss) : String(row.gloss ?? ''),
        String(item.pos ?? '') !== '' ? String(item.pos) : String(row.pos ?? ''),
        String(item.phonetic ?? '') !== '' ? String(item.phonetic) : String(row.phonetic ?? ''),
        String(item.note ?? ''),
        JSON.stringify(mergedTags),
        JSON.stringify(mergedContexts),
        String(item.source || row.source || ''),
        state,
        Number(item.dueAt ?? 0) || Number(row.due_at ?? 0),
        Number(item.intervalDays ?? 0),
        ease,
        Math.max(0, Number(item.reps ?? 0)),
        Math.max(0, Number(item.lapses ?? 0)),
        Number(item.lastReviewedAt ?? 0),
        newUpdated,
        Number(item.deletedAt ?? 0),
        Number(row.id),
        userId,
      )
      .run()
    return true
  }

  if (mergedContexts.length !== oldContexts.length || mergedTags.length !== oldTags.length) {
    await db
      .prepare('UPDATE vocab SET tags=?, contexts=?, updated_at=? WHERE id=? AND user_id=?')
      .bind(JSON.stringify(mergedTags), JSON.stringify(mergedContexts), serverNow, Number(row.id), userId)
      .run()
    return true
  }
  return false
}

async function applySessionItem(
  db: D1Database,
  userId: string,
  item: Record<string, unknown>,
  serverNow: number,
): Promise<boolean> {
  const id = String(item.id ?? '')
  if (!id) return false
  const metaStr = typeof item.meta === 'string' ? item.meta : JSON.stringify(item.meta ?? {})
  const rawEnded = item.endedAt ?? item.ended_at
  const rawStarted = item.startedAt ?? item.started_at
  const rawUpdated = item.updatedAt ?? item.updated_at
  const incUpdated = Number(rawUpdated ?? rawEnded ?? rawStarted ?? serverNow)
  const row = await db
    .prepare('SELECT * FROM sessions WHERE user_id=? AND id=?')
    .bind(userId, id)
    .first<Record<string, unknown>>()

  if (!row) {
    await db
      .prepare(
        'INSERT INTO sessions(user_id,id,kind,pack_id,mode,planned,answered,correct,meta,started_at,ended_at,updated_at)' +
          ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
      )
      .bind(
        userId,
        id,
        String(item.kind ?? ''),
        String(item.packId ?? item.pack_id ?? ''),
        String(item.mode ?? ''),
        Number(item.planned ?? 0),
        Number(item.answered ?? 0),
        Number(item.correct ?? 0),
        metaStr,
        Number(rawStarted ?? serverNow),
        rawEnded != null ? Number(rawEnded) : null,
        Math.max(incUpdated, serverNow),
      )
      .run()
    return true
  }

  if (incUpdated >= Number(row.updated_at ?? 0) || (rawEnded != null && row.ended_at == null)) {
    await db
      .prepare(
        'UPDATE sessions SET answered=?,correct=?,meta=?,ended_at=?,updated_at=? WHERE user_id=? AND id=?',
      )
      .bind(
        Math.max(Number(row.answered ?? 0), Number(item.answered ?? 0)),
        Math.max(Number(row.correct ?? 0), Number(item.correct ?? 0)),
        metaStr,
        rawEnded != null ? Number(rawEnded) : row.ended_at,
        Math.max(incUpdated, serverNow),
        userId,
        id,
      )
      .run()
    return true
  }
  return false
}

async function applyAttemptItem(
  db: D1Database,
  userId: string,
  item: Record<string, unknown>,
  serverNow: number,
): Promise<boolean> {
  const clientId = String(item.clientId ?? item.client_id ?? '')
  const kind = String(item.kind ?? '')
  if (!clientId || !kind) return false
  const metaStr = typeof item.meta === 'string' ? item.meta : JSON.stringify(item.meta ?? {})
  const res = await db
    .prepare(
      'INSERT OR IGNORE INTO attempts(user_id,client_id,kind,ref,pack_id,session_id,input,expected,correct,duration_ms,meta,created_at)' +
        ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
    )
    .bind(
      userId,
      clientId,
      kind,
      String(item.ref ?? ''),
      String(item.packId ?? item.pack_id ?? ''),
      String(item.sessionId ?? item.session_id ?? ''),
      String(item.input ?? ''),
      String(item.expected ?? ''),
      item.correct ? 1 : 0,
      Number(item.durationMs ?? item.duration_ms ?? 0),
      metaStr,
      Number(item.createdAt ?? item.created_at ?? 0) || serverNow,
    )
    .run()
  return (res.meta?.changes ?? 0) > 0
}

async function recordImportedHistory(
  db: D1Database,
  userId: string,
  packId: string,
  detail: Record<string, unknown>,
): Promise<boolean> {
  const att = detail.attempt as Record<string, unknown> | null
  if (!att) return false
  const groups = (detail.questionGroups as Record<string, unknown>[]) ?? []
  const items = groups.flatMap((g) =>
    ((g.items as Record<string, unknown>[]) ?? []).map((q) => ({ group: g, q })),
  )
  const answered = items.filter(({ q }) => String(q.mine ?? '').trim())
  if (!answered.length) return false

  const subIso = String(att.submittedAt ?? '')
  const parsedMs = subIso ? Date.parse(subIso) : NaN
  const finished = Number.isNaN(parsedMs) ? nowSec() : Math.floor(parsedMs / 1000)

  if (subIso) {
    const dup = await db
      .prepare(
        "SELECT id FROM sessions WHERE user_id=? AND kind='reading' AND mode='history' AND pack_id=? AND ended_at=?",
      )
      .bind(userId, packId, finished)
      .first()
    if (dup) return false
  }

  const durSec = Number(att.durationSec ?? 0)
  const started = Math.max(0, finished - durSec)
  const sid = `rs_${randomHex(8)}`
  const now = nowSec()
  const nos = items.map(({ q }) => Number(q.no))

  await db
    .prepare(
      'INSERT INTO sessions(id,user_id,kind,pack_id,mode,planned,answered,correct,meta,started_at,ended_at,updated_at)' +
        ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
    )
    .bind(
      sid,
      userId,
      'reading',
      packId,
      'history',
      items.length,
      items.length,
      Number(att.score ?? 0),
      JSON.stringify({ nos, imported: true, submittedAt: subIso, durationMs: durSec * 1000 }),
      started,
      finished,
      now,
    )
    .run()

  for (const { group, q } of items) {
    const expected = Array.isArray(q.answer) ? q.answer.join('|') : String(q.answer ?? '')
    const cid = `hist_${packId}_${finished}_q${q.no}`
    await db
      .prepare(
        'INSERT OR IGNORE INTO attempts(user_id,client_id,kind,ref,pack_id,session_id,input,expected,correct,duration_ms,meta,created_at)' +
          ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
      )
      .bind(
        userId,
        cid,
        'reading_question',
        String(q.no),
        packId,
        sid,
        String(q.mine ?? ''),
        expected,
        q.correct === true ? 1 : 0,
        0,
        JSON.stringify({ group: group.id, type: group.type }),
        finished,
      )
      .run()
  }
  return true
}

// ── GitHub OAuth & Auth Handlers ─────────────────────────────────────────

async function handleGithubLogin(req: Request, env: Env, url: URL): Promise<Response> {
  const clientId = (env.GITHUB_CLIENT_ID ?? '').trim()
  if (!clientId) return json({ detail: '服务端未配置 GITHUB_CLIENT_ID' }, 500)
  const state = randomHex(16)
  const callbackUrl = `${url.origin}/api/auth/github/callback`
  const authorizeUrl =
    'https://github.com/login/oauth/authorize' +
    `?client_id=${encodeURIComponent(clientId)}` +
    `&redirect_uri=${encodeURIComponent(callbackUrl)}` +
    '&scope=read:user' +
    `&state=${encodeURIComponent(state)}`

  const secure = url.protocol === 'https:' ? '; Secure' : ''
  return new Response(null, {
    status: 302,
    headers: {
      Location: authorizeUrl,
      'Set-Cookie': `xt_oauth_state=${state}; HttpOnly; SameSite=Lax; Path=/; Max-Age=600${secure}`,
    },
  })
}

async function handleGithubCallback(req: Request, env: Env, url: URL): Promise<Response> {
  const errParam = url.searchParams.get('error')
  if (errParam) {
    return Response.redirect(`${url.origin}/#auth_error=${encodeURIComponent(errParam)}`, 302)
  }

  const code = (url.searchParams.get('code') ?? '').trim()
  const state = (url.searchParams.get('state') ?? '').trim()
  const expectedState = getCookie(req, 'xt_oauth_state')
  if (!code || !state || !expectedState || state !== expectedState) {
    return Response.redirect(`${url.origin}/#auth_error=invalid_state`, 302)
  }

  const clientId = (env.GITHUB_CLIENT_ID ?? '').trim()
  const clientSecret = (env.GITHUB_CLIENT_SECRET ?? '').trim()
  const jwtSecret = (env.JWT_SECRET ?? '').trim()
  if (!clientId || !clientSecret || !jwtSecret) {
    return Response.redirect(`${url.origin}/#auth_error=server_not_configured`, 302)
  }

  const tokenResp = await fetch('https://github.com/login/oauth/access_token', {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'User-Agent': 'xiaotou-ielts',
    },
    body: JSON.stringify({
      client_id: clientId,
      client_secret: clientSecret,
      code,
      redirect_uri: `${url.origin}/api/auth/github/callback`,
    }),
  })
  if (!tokenResp.ok) {
    return Response.redirect(`${url.origin}/#auth_error=token_exchange_failed`, 302)
  }
  const tokenData = (await tokenResp.json()) as { access_token?: string; error?: string }
  if (!tokenData.access_token) {
    return Response.redirect(
      `${url.origin}/#auth_error=${encodeURIComponent(tokenData.error ?? 'missing_access_token')}`,
      302,
    )
  }

  const userResp = await fetch('https://api.github.com/user', {
    headers: {
      Authorization: `Bearer ${tokenData.access_token}`,
      Accept: 'application/vnd.github+json',
      'User-Agent': 'xiaotou-ielts',
    },
  })
  if (!userResp.ok) {
    return Response.redirect(`${url.origin}/#auth_error=github_user_failed`, 302)
  }
  const ghUser = (await userResp.json()) as {
    id: number
    login: string
    name?: string | null
    avatar_url?: string | null
  }
  if (!ghUser?.id || !ghUser.login) {
    return Response.redirect(`${url.origin}/#auth_error=invalid_github_user`, 302)
  }

  const ghId = String(ghUser.id)
  const login = String(ghUser.login)
  const name = String(ghUser.name ?? login)
  const avatarUrl = String(ghUser.avatar_url ?? '')
  const adminLogin = (env.ADMIN_GITHUB_LOGIN || 'yyyyyjp').trim().toLowerCase()
  const isAdmin = login.toLowerCase() === adminLogin
  const now = nowSec()

  let row = await env.DB.prepare('SELECT * FROM users WHERE github_id=?')
    .bind(ghId)
    .first<Record<string, unknown>>()

  let user: AuthUser
  if (!row) {
    const newId = isAdmin ? ADMIN_USER_ID : `u_${randomHex(10)}`
    const role: 'admin' | 'user' = isAdmin ? 'admin' : 'user'
    const status: 'active' | 'pending' = isAdmin ? 'active' : 'pending'
    await env.DB.prepare(
      'INSERT INTO users(id,github_id,login,name,avatar_url,role,status,invite_code,created_at,updated_at)' +
        ' VALUES(?,?,?,?,?,?,?,?,?,?)',
    )
      .bind(newId, ghId, login, name, avatarUrl, role, status, '', now, now)
      .run()
    user = { id: newId, githubId: ghId, login, name, avatarUrl, role, status }
  } else {
    const role: 'admin' | 'user' = isAdmin || row.role === 'admin' ? 'admin' : 'user'
    const status: 'active' | 'pending' = isAdmin || row.status === 'active' ? 'active' : 'pending'
    await env.DB.prepare(
      'UPDATE users SET login=?,name=?,avatar_url=?,role=?,status=?,updated_at=? WHERE id=?',
    )
      .bind(login, name, avatarUrl, role, status, now, String(row.id))
      .run()
    user = {
      id: String(row.id),
      githubId: ghId,
      login,
      name,
      avatarUrl,
      role,
      status,
    }
  }

  const jwt = await signJwt(user, jwtSecret)
  const secure = url.protocol === 'https:' ? '; Secure' : ''
  return new Response(null, {
    status: 302,
    headers: {
      Location: `${url.origin}/#auth_token=${encodeURIComponent(jwt)}`,
      'Set-Cookie': `xt_oauth_state=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0${secure}`,
    },
  })
}

async function handleActivate(req: Request, env: Env): Promise<Response> {
  const user = await resolveAuthUser(req, env)
  if (!user) return json({ detail: 'Please sign in with GitHub first.' }, 401)
  const jwtSecret = (env.JWT_SECRET ?? '').trim()
  if (user.status === 'active') {
    const token = await signJwt(user, jwtSecret)
    return json({ ok: true, token, user })
  }

  const body = (await req.json().catch(() => ({}))) as { code?: string }
  const code = String(body.code ?? '').trim().toUpperCase()
  if (!code) return json({ detail: 'Please enter an invite code.' }, 400)

  const upd = await env.DB.prepare(
    'UPDATE invites SET used_count = used_count + 1 WHERE code=? AND revoked_at=0 AND used_count < max_uses',
  )
    .bind(code)
    .run()
  if ((upd.meta?.changes ?? 0) === 0) {
    return json({ detail: 'Invalid, exhausted, or revoked invite code.' }, 400)
  }

  const now = nowSec()
  await env.DB.prepare("UPDATE users SET status='active', invite_code=?, updated_at=? WHERE id=?")
    .bind(code, now, user.id)
    .run()

  const activeUser: AuthUser = { ...user, status: 'active' }
  const token = await signJwt(activeUser, jwtSecret)
  return json({ ok: true, token, user: activeUser })
}

// ── Sync Handler (Strictly Per-User) ─────────────────────────────────────

async function handleSync(req: Request, env: Env, user: AuthUser): Promise<Response> {
  const body = (await req.json().catch(() => ({}))) as {
    cursor?: { vocab?: number; sessions?: number; attempts?: number; packs?: number }
    push?: {
      vocab?: Record<string, unknown>[]
      sessions?: Record<string, unknown>[]
      attempts?: Record<string, unknown>[]
    }
  }
  const cursor = body.cursor ?? {}
  const push = body.push ?? {}
  const now = nowSec()

  let pushedVocab = 0
  for (const it of push.vocab ?? []) {
    if (await applyVocabItem(env.DB, user.id, it, now)) pushedVocab += 1
  }
  let pushedSessions = 0
  for (const it of push.sessions ?? []) {
    if (await applySessionItem(env.DB, user.id, it, now)) pushedSessions += 1
  }
  let pushedAttempts = 0
  for (const it of push.attempts ?? []) {
    if (await applyAttemptItem(env.DB, user.id, it, now)) pushedAttempts += 1
  }

  const vRows = (
    await env.DB.prepare(
      'SELECT * FROM vocab WHERE user_id=? AND updated_at > ? ORDER BY updated_at ASC, id ASC',
    )
      .bind(user.id, Number(cursor.vocab ?? 0))
      .all<Record<string, unknown>>()
  ).results

  const sRows = (
    await env.DB.prepare(
      'SELECT * FROM sessions WHERE user_id=? AND updated_at > ? ORDER BY updated_at ASC, id ASC',
    )
      .bind(user.id, Number(cursor.sessions ?? 0))
      .all<Record<string, unknown>>()
  ).results

  const aRowsAll = (
    await env.DB.prepare('SELECT * FROM attempts WHERE user_id=? AND id > ? ORDER BY id ASC LIMIT 2001')
      .bind(user.id, Number(cursor.attempts ?? 0))
      .all<Record<string, unknown>>()
  ).results
  const hasMore = aRowsAll.length > 2000
  const aRows = hasMore ? aRowsAll.slice(0, 2000) : aRowsAll

  const packRows = (
    await env.DB.prepare('SELECT id, mtime, summary_json FROM packs WHERE user_id=?')
      .bind(user.id)
      .all<Record<string, unknown>>()
  ).results
  const packCursor = Number(cursor.packs ?? 0)
  let maxPackMtime = packCursor
  const changedPacks: { id: string; mtime: number; summary: unknown }[] = []
  const allPackIds: string[] = []
  for (const p of packRows) {
    const id = String(p.id)
    const mt = Number(p.mtime ?? 0)
    allPackIds.push(id)
    if (mt > maxPackMtime) maxPackMtime = mt
    if (mt > packCursor) {
      changedPacks.push({ id, mtime: mt, summary: safeJsonParse(p.summary_json, {}) })
    }
  }

  const nextCursor = {
    vocab: Math.max(Number(cursor.vocab ?? 0), ...vRows.map((r) => Number(r.updated_at ?? 0))),
    sessions: Math.max(Number(cursor.sessions ?? 0), ...sRows.map((r) => Number(r.updated_at ?? 0))),
    attempts: Math.max(Number(cursor.attempts ?? 0), ...aRows.map((r) => Number(r.id ?? 0))),
    packs: maxPackMtime,
  }

  return json({
    ok: true,
    serverTs: now,
    authRequired: true,
    pushed: { vocab: pushedVocab, sessions: pushedSessions, attempts: pushedAttempts },
    pull: {
      vocab: vRows.map(vocabRowOut),
      sessions: sRows.map((r) => ({
        id: String(r.id),
        kind: String(r.kind),
        packId: String(r.pack_id ?? ''),
        mode: String(r.mode ?? ''),
        planned: Number(r.planned ?? 0),
        answered: Number(r.answered ?? 0),
        correct: Number(r.correct ?? 0),
        meta: safeJsonParse(r.meta, {}),
        startedAt: Number(r.started_at ?? 0),
        endedAt: r.ended_at != null ? Number(r.ended_at) : null,
        updatedAt: Number(r.updated_at ?? 0),
      })),
      attempts: aRows.map((r) => ({
        seq: Number(r.id),
        clientId: String(r.client_id || `legacy-${r.id}`),
        kind: String(r.kind),
        ref: String(r.ref),
        packId: String(r.pack_id ?? ''),
        sessionId: String(r.session_id ?? ''),
        input: String(r.input ?? ''),
        expected: String(r.expected ?? ''),
        correct: Number(r.correct ?? 0),
        durationMs: Number(r.duration_ms ?? 0),
        meta: safeJsonParse(r.meta, {}),
        createdAt: Number(r.created_at ?? 0),
      })),
      packs: changedPacks,
      allPackIds: allPackIds.sort(),
      hasMore,
    },
    cursor: nextCursor,
  })
}

async function serveR2Gzip(req: Request, bucket: R2Bucket, key: string, maxAge = 86400): Promise<Response> {
  const obj = await bucket.get(key)
  if (!obj) return json({ detail: `R2 对象不存在：${key}` }, 404)
  const etag = obj.httpEtag
  if (req.headers.get('if-none-match') === etag) {
    return new Response(null, { status: 304, headers: { ETag: etag } })
  }
  const acceptEnc = req.headers.get('accept-encoding') ?? ''
  if (acceptEnc.toLowerCase().includes('gzip')) {
    return new Response(obj.body, {
      status: 200,
      headers: {
        'Content-Type': 'application/json; charset=utf-8',
        'Content-Encoding': 'gzip',
        ETag: etag,
        'Cache-Control': `public, max-age=${maxAge}`,
      },
    })
  }
  const decompressed = obj.body.pipeThrough(new DecompressionStream('gzip'))
  return new Response(decompressed, {
    status: 200,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      ETag: etag,
      'Cache-Control': `public, max-age=${maxAge}`,
    },
  })
}

// ── Main API Router ──────────────────────────────────────────────────────

async function routeApi(req: Request, env: Env, url: URL): Promise<Response> {
  const path = url.pathname.replace(/^\/api/, '')
  const method = req.method.toUpperCase()

  // 1. 公开接口（健康检查 + 认证流程 + 纯公共离线词典/音频）
  if (path === '/health' && method === 'GET') {
    const coreHead = await env.BUCKET.head('dict/core_dict.json.gz')
    return json({
      ok: true,
      ts: nowSec(),
      runtime: 'cloudflare-worker',
      authEnabled: true,
      dict: { ready: Boolean(coreHead), coreSize: coreHead?.size ?? 0 },
    })
  }

  if (path === '/auth/me' && method === 'GET') {
    const user = await resolveAuthUser(req, env)
    return json({
      authEnabled: true,
      authenticated: Boolean(user),
      user,
    })
  }
  if (path === '/auth/github/login' && method === 'GET') {
    return handleGithubLogin(req, env, url)
  }
  if (path === '/auth/github/callback' && method === 'GET') {
    return handleGithubCallback(req, env, url)
  }
  if (path === '/auth/activate' && method === 'POST') {
    return handleActivate(req, env)
  }
  if (path === '/auth/logout' && method === 'POST') {
    return json({ ok: true })
  }

  if (path === '/dict/status' && method === 'GET') {
    const head = await env.BUCKET.head('dict/core_dict.json.gz')
    return json({
      ready: Boolean(head),
      coreReady: Boolean(head),
      coreSize: head?.size ?? 0,
      entries: head ? 770611 : 0,
    })
  }
  if (path === '/dict/bundle' && method === 'GET') {
    return serveR2Gzip(req, env.BUCKET, 'dict/core_dict.json.gz', 604800)
  }
  if (path === '/dict/lookup' && method === 'GET') {
    const q = (url.searchParams.get('q') ?? '').trim()
    if (!q) return json({ detail: 'missing q' }, 400)
    const uiLang = url.searchParams.get('lang') === 'en' ? 'en' : 'zh'
    const result = await lookupInD1(env.DB, q, uiLang)
    return json(result, 200, { 'Cache-Control': 'public, max-age=604800' })
  }
  const shardMatch = /^\/dict\/shard\/([a-z]|other)$/.exec(path)
  if (shardMatch && method === 'GET') {
    return serveR2Gzip(req, env.BUCKET, `dict/shards/${shardMatch[1]}.json.gz`, 604800)
  }

  const audioMatch = /^\/audio\/([a-zA-Z0-9._-]+)$/.exec(path)
  if (audioMatch && method === 'GET') {
    const obj = await env.BUCKET.get(`audio/${audioMatch[1]}`)
    if (!obj) return json({ detail: '音频未缓存' }, 404)
    return new Response(obj.body, {
      status: 200,
      headers: {
        'Content-Type': 'audio/mpeg',
        'Cache-Control': 'public, max-age=31536000, immutable',
      },
    })
  }
  if (path === '/tts/audio' && method === 'GET') {
    const text = (url.searchParams.get('text') ?? '').trim()
    const voice = (url.searchParams.get('voice') ?? 'en-GB-SoniaNeural').trim()
    const rate = (url.searchParams.get('rate') ?? '-5%').trim()
    if (!text) return json({ detail: 'missing text' }, 400)
    const obj = await env.BUCKET.get(`audio/${encodeURIComponent(`${voice}|${rate}|${text}`)}.mp3`)
    if (!obj) return json({ detail: '云端未缓存此语音，使用浏览器本地朗读' }, 404)
    return new Response(obj.body, {
      status: 200,
      headers: { 'Content-Type': 'audio/mpeg', 'Cache-Control': 'public, max-age=31536000, immutable' },
    })
  }

  // 2. 管理员邀请码管理接口
  if (path === '/admin/invites' && method === 'GET') {
    const auth = await requireAdmin(req, env)
    if (auth.error) return auth.error
    const rows = (
      await env.DB.prepare('SELECT * FROM invites ORDER BY created_at DESC LIMIT 100').all<
        Record<string, unknown>
      >()
    ).results
    const userCount = await env.DB.prepare("SELECT COUNT(*) AS n FROM users WHERE status='active'").first<{
      n: number
    }>()
    return json({
      activeUsers: Number(userCount?.n ?? 0),
      items: rows.map((r) => ({
        code: String(r.code),
        maxUses: Number(r.max_uses ?? 1),
        usedCount: Number(r.used_count ?? 0),
        note: String(r.note ?? ''),
        createdAt: Number(r.created_at ?? 0),
        revokedAt: Number(r.revoked_at ?? 0),
      })),
    })
  }

  if (path === '/admin/invites' && method === 'POST') {
    const auth = await requireAdmin(req, env)
    if (auth.error) return auth.error
    const body = (await req.json().catch(() => ({}))) as { maxUses?: number; note?: string }
    const maxUses = Math.max(1, Math.min(100, Math.trunc(Number(body.maxUses ?? 1) || 1)))
    const note = String(body.note ?? '').trim().slice(0, 60)
    const code = generateInviteCode()
    const now = nowSec()
    await env.DB.prepare(
      'INSERT INTO invites(code,max_uses,used_count,created_by,note,created_at,revoked_at) VALUES(?,?,0,?,?,?,0)',
    )
      .bind(code, maxUses, auth.user.id, note, now)
      .run()
    return json({
      code,
      maxUses,
      usedCount: 0,
      note,
      createdAt: now,
      revokedAt: 0,
    })
  }

  const revokeInviteMatch = /^\/admin\/invites\/([^/]+)$/.exec(path)
  if (revokeInviteMatch && method === 'DELETE') {
    const auth = await requireAdmin(req, env)
    if (auth.error) return auth.error
    const code = decodeURIComponent(revokeInviteMatch[1]).trim().toUpperCase()
    const res = await env.DB.prepare('UPDATE invites SET revoked_at=? WHERE code=? AND revoked_at=0')
      .bind(nowSec(), code)
      .run()
    if ((res.meta?.changes ?? 0) === 0) return json({ detail: '邀请码不存在或已作废' }, 404)
    return json({ ok: true })
  }

  // 3. 以下全部为已激活用户专属隔离接口
  const auth = await requireActiveUser(req, env)
  if (auth.error) return auth.error
  const user = auth.user

  // ── Sync ──
  if (path === '/sync' && method === 'POST') return handleSync(req, env, user)
  if (path === '/sync/export' && method === 'GET') {
    const v = (
      await env.DB.prepare('SELECT * FROM vocab WHERE user_id=? ORDER BY id ASC')
        .bind(user.id)
        .all<Record<string, unknown>>()
    ).results
    const s = (
      await env.DB.prepare('SELECT * FROM sessions WHERE user_id=? ORDER BY started_at ASC')
        .bind(user.id)
        .all<Record<string, unknown>>()
    ).results
    const a = (
      await env.DB.prepare('SELECT * FROM attempts WHERE user_id=? ORDER BY id ASC')
        .bind(user.id)
        .all<Record<string, unknown>>()
    ).results
    return json({
      schemaVersion: 2,
      exportedAt: nowSec(),
      vocab: v.map(vocabRowOut),
      sessions: s.map((r) => ({
        id: String(r.id),
        kind: String(r.kind),
        packId: String(r.pack_id ?? ''),
        mode: String(r.mode ?? ''),
        planned: Number(r.planned ?? 0),
        answered: Number(r.answered ?? 0),
        correct: Number(r.correct ?? 0),
        meta: safeJsonParse(r.meta, {}),
        startedAt: Number(r.started_at ?? 0),
        endedAt: r.ended_at != null ? Number(r.ended_at) : null,
        updatedAt: Number(r.updated_at ?? 0),
      })),
      attempts: a.map((r) => ({
        seq: Number(r.id),
        clientId: String(r.client_id || `legacy-${r.id}`),
        kind: String(r.kind),
        ref: String(r.ref),
        packId: String(r.pack_id ?? ''),
        sessionId: String(r.session_id ?? ''),
        input: String(r.input ?? ''),
        expected: String(r.expected ?? ''),
        correct: Number(r.correct ?? 0),
        durationMs: Number(r.duration_ms ?? 0),
        meta: safeJsonParse(r.meta, {}),
        createdAt: Number(r.created_at ?? 0),
      })),
    })
  }
  if (path === '/sync/import' && method === 'POST') {
    const payload = (await req.json()) as {
      vocab?: Record<string, unknown>[]
      sessions?: Record<string, unknown>[]
      attempts?: Record<string, unknown>[]
    }
    const now = nowSec()
    let vn = 0
    let sn = 0
    let an = 0
    for (const it of payload.vocab ?? []) if (await applyVocabItem(env.DB, user.id, it, now)) vn += 1
    for (const it of payload.sessions ?? []) if (await applySessionItem(env.DB, user.id, it, now)) sn += 1
    for (const it of payload.attempts ?? []) if (await applyAttemptItem(env.DB, user.id, it, now)) an += 1
    return json({ ok: true, merged: { vocab: vn, sessions: sn, attempts: an } })
  }

  // ── Packs (Strictly Per-User) ──
  if (path === '/packs' && method === 'GET') {
    const rows = (
      await env.DB.prepare('SELECT summary_json FROM packs WHERE user_id=?')
        .bind(user.id)
        .all<{ summary_json: string }>()
    ).results
    const items = rows.map((r) => safeJsonParse(r.summary_json, {})).filter(Boolean)
    return json({ items, errors: {} })
  }

  if (path === '/packs/from-export' && method === 'POST') {
    const body = (await req.json()) as {
      passage: Record<string, unknown>
      questions: Record<string, unknown>[]
      groups: Record<string, unknown>[]
      attempt?: Record<string, unknown> | null
      analysisText?: string
      id?: string
      recordHistory?: boolean
      dryRun?: boolean
    }
    try {
      const candidateId = body.id?.trim() || undefined
      let existingDetail: Record<string, unknown> | null = null
      if (candidateId) {
        const exRow = await env.DB.prepare('SELECT detail_json FROM packs WHERE user_id=? AND id=?')
          .bind(user.id, candidateId)
          .first<{ detail_json: string }>()
        if (exRow) existingDetail = safeJsonParse(exRow.detail_json, null)
      }
      const built = buildPackFromExportData({
        passage: body.passage ?? {},
        questions: body.questions ?? [],
        groups: body.groups ?? [],
        attempt: body.attempt ?? null,
        analysisText: body.analysisText ?? '',
        packIdOverride: body.id,
        existingDetail,
      })
      if (!existingDetail) {
        const exRow = await env.DB.prepare('SELECT detail_json FROM packs WHERE user_id=? AND id=?')
          .bind(user.id, built.packId)
          .first<{ detail_json: string }>()
        if (exRow) existingDetail = safeJsonParse(exRow.detail_json, null)
      }
      const exists = Boolean(existingDetail)
      let historyRecorded = false
      if (!body.dryRun) {
        const mt = nowSec()
        await env.DB.prepare(
          'INSERT INTO packs(user_id,id,kind,origin,title,mtime,summary_json,detail_json) VALUES(?,?,?,?,?,?,?,?) ' +
            'ON CONFLICT(user_id,id) DO UPDATE SET title=excluded.title, mtime=excluded.mtime, summary_json=excluded.summary_json, detail_json=excluded.detail_json',
        )
          .bind(
            user.id,
            built.packId,
            'reading',
            String(built.detail.origin ?? 'custom'),
            String(built.detail.meta.title ?? built.packId),
            mt,
            JSON.stringify(built.summary),
            JSON.stringify(built.detail),
          )
          .run()
        if (body.recordHistory !== false) {
          historyRecorded = await recordImportedHistory(env.DB, user.id, built.packId, built.detail)
        }
      }
      return json({
        id: built.packId,
        exists,
        created: !exists && !body.dryRun,
        dryRun: Boolean(body.dryRun),
        meta: built.detail.meta,
        counts: {
          paragraphs: built.paragraphsCount,
          sentences: built.sentencesCount,
          questions: built.questionsCount,
          words: built.detail.counts.words,
        },
        attempt: built.detail.attempt,
        analysis: built.analysisSummary,
        warnings: built.warnings,
        historyRecorded,
      })
    } catch (err) {
      return json({ detail: err instanceof Error ? err.message : '导入失败' }, 400)
    }
  }

  if (path === '/packs/export-prompt' && method === 'POST') {
    const body = (await req.json()) as {
      passage: Record<string, unknown>
      questions: Record<string, unknown>[]
      groups: Record<string, unknown>[]
      attempt?: Record<string, unknown> | null
    }
    try {
      const built = buildPackFromExportData({
        passage: body.passage ?? {},
        questions: body.questions ?? [],
        groups: body.groups ?? [],
        attempt: body.attempt ?? null,
        analysisText: '',
      })
      return json({
        id: built.packId,
        title: built.detail.meta.title,
        label: [built.detail.meta.book, built.detail.meta.test, built.detail.meta.passage].filter(Boolean).join(' · '),
        prompt: buildPromptText(built.detail, body.attempt ?? null),
      })
    } catch (err) {
      return json({ detail: err instanceof Error ? err.message : '生成提示词失败' }, 400)
    }
  }

  const packPromptMatch = /^\/packs\/([^/]+)\/prompt$/.exec(path)
  if (packPromptMatch && method === 'GET') {
    const pid = decodeURIComponent(packPromptMatch[1])
    const row = await env.DB.prepare('SELECT detail_json FROM packs WHERE user_id=? AND id=?')
      .bind(user.id, pid)
      .first<{ detail_json: string }>()
    if (!row) return json({ detail: '内容包不存在' }, 404)
    const detail = safeJsonParse<Record<string, unknown>>(row.detail_json, {})
    const meta = (detail.meta as Record<string, unknown>) ?? {}
    return json({
      id: pid,
      title: String(meta.title ?? pid),
      label: [meta.book, meta.test, meta.passage].filter(Boolean).join(' · '),
      prompt: buildPromptText(detail),
    })
  }

  const packAnalysisMatch = /^\/packs\/([^/]+)\/analysis$/.exec(path)
  if (packAnalysisMatch && method === 'POST') {
    const pid = decodeURIComponent(packAnalysisMatch[1])
    const row = await env.DB.prepare('SELECT detail_json, summary_json FROM packs WHERE user_id=? AND id=?')
      .bind(user.id, pid)
      .first<{ detail_json: string; summary_json: string }>()
    if (!row) return json({ detail: '内容包不存在' }, 404)
    const body = (await req.json()) as { analysisText: string; keepLexicon?: boolean; dryRun?: boolean }
    try {
      const raw = extractJsonObject(body.analysisText ?? '')
      const { review, guide } = normalizeAnalysis(raw)
      const detail = safeJsonParse<Record<string, unknown>>(row.detail_json, {})
      const summary = safeJsonParse<Record<string, unknown>>(row.summary_json, {})
      const lexicon =
        body.keepLexicon === false ? {} : { ...((detail.lexicon as Record<string, unknown>) ?? {}) }
      let lexAdded = 0
      if (raw.lexicon && typeof raw.lexicon === 'object') {
        for (const [k, v] of Object.entries(raw.lexicon as Record<string, unknown>)) {
          const norm = normalizeLexEntry(v)
          if (norm && k.trim()) {
            if (!(k.trim() in lexicon)) lexAdded += 1
            lexicon[k.trim()] = norm
          }
        }
      }
      if (review) detail.review = review
      if (guide) detail.guide = guide
      detail.lexicon = lexicon
      detail.hasReview = Boolean(detail.review)
      detail.hasGuide = Boolean(detail.guide)
      summary.hasReview = detail.hasReview
      summary.hasGuide = detail.hasGuide

      const paragraphs = (detail.paragraphs as { no: number; sentences: unknown[] }[]) ?? []
      const qNos = new Set<number>(
        ((detail.questionGroups as Record<string, unknown>[]) ?? [])
          .flatMap((g) => (g.items as { no: number }[]) ?? [])
          .map((q) => Number(q.no)),
      )
      const warnings = validateAnalysis(review, guide, paragraphs, qNos)
      const analysis = summarizeAnalysis(
        (detail.review as Record<string, unknown> | null) ?? null,
        (detail.guide as Record<string, unknown> | null) ?? null,
        lexAdded,
      )
      if (!body.dryRun) {
        const mt = nowSec()
        await env.DB.prepare('UPDATE packs SET mtime=?, summary_json=?, detail_json=? WHERE user_id=? AND id=?')
          .bind(mt, JSON.stringify(summary), JSON.stringify(detail), user.id, pid)
          .run()
      }
      return json({
        id: pid,
        exists: true,
        dryRun: Boolean(body.dryRun),
        meta: detail.meta,
        analysis,
        warnings,
      })
    } catch (err) {
      return json({ detail: err instanceof Error ? err.message : '解析失败' }, 400)
    }
  }

  const packMatch = /^\/packs\/([^/]+)$/.exec(path)
  if (packMatch && method === 'GET') {
    const pid = decodeURIComponent(packMatch[1])
    const row = await env.DB.prepare('SELECT detail_json FROM packs WHERE user_id=? AND id=?')
      .bind(user.id, pid)
      .first<{ detail_json: string }>()
    if (!row) return json({ detail: '内容包不存在' }, 404)
    const detail = safeJsonParse<Record<string, unknown>>(row.detail_json, {})
    const withAnswers = url.searchParams.get('answers') === '1'
    if (!withAnswers) {
      detail.review = null
      detail.guide = null
      for (const g of (detail.questionGroups as Record<string, unknown>[]) ?? []) {
        for (const it of (g.items as Record<string, unknown>[]) ?? []) {
          delete it.answer
        }
      }
    }
    return json(detail)
  }

  if (packMatch && method === 'DELETE') {
    const pid = decodeURIComponent(packMatch[1])
    const res = await env.DB.prepare('DELETE FROM packs WHERE user_id=? AND id=?')
      .bind(user.id, pid)
      .run()
    if ((res.meta?.changes ?? 0) === 0) return json({ detail: '内容包不存在' }, 404)
    return json({ ok: true })
  }

  return json({ detail: 'Not Found' }, 404)
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    if (req.method === 'OPTIONS') {
      return withCors(req, new Response(null, { status: 204 }))
    }
    const url = new URL(req.url)
    if (url.pathname.startsWith('/api')) {
      const res = await routeApi(req, env, url)
      return withCors(req, res)
    }
    return env.ASSETS.fetch(req)
  },
}
