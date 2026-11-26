/**
 * 小头雅思 · Cloudflare Worker 统一入口（D1 + R2 + Static Assets）。
 *
 * 复用与本地 FastAPI 完全一致的 `/api/*` 契约：
 * - `/api/sync`、`GET /api/sync/export`、`POST /api/sync/import`
 * - `/api/packs`、`/api/packs/:id`、`/api/packs/from-export`、`/api/packs/:id/analysis` 等
 * - `/api/dict/bundle`（6.6 万核心离线词库，R2）、`/api/dict/shard/:letter`（77 万首字母分片，R2）
 * - `/api/audio/:name`（R2 音频缓存）
 */

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
  SYNC_TOKEN?: string
}

const VALID_STATES = new Set(['new', 'learning', 'review', 'suspended'])

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

function checkSyncAuth(req: Request, env: Env): Response | null {
  const expected = (env.SYNC_TOKEN ?? '').trim()
  if (!expected) return null
  const auth = req.headers.get('authorization') ?? ''
  const xTok = req.headers.get('x-sync-token') ?? ''
  const token = auth.toLowerCase().startsWith('bearer ') ? auth.slice(7).trim() : xTok.trim()
  if (!token || token !== expected) {
    return json({ detail: '同步口令无效或未提供' }, 401)
  }
  return null
}

function withCors(req: Request, res: Response): Response {
  const origin = req.headers.get('origin')
  if (!origin) return res
  const headers = new Headers(res.headers)
  headers.set('Access-Control-Allow-Origin', origin)
  headers.set('Access-Control-Allow-Methods', 'GET,POST,PATCH,DELETE,OPTIONS')
  headers.set('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-Sync-Token')
  return new Response(res.body, {
    status: res.status,
    statusText: res.statusText,
    headers,
  })
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

function safeJsonParse<T>(raw: unknown, fallback: T): T {
  if (typeof raw !== 'string' || !raw) return fallback
  try {
    return JSON.parse(raw) as T
  } catch {
    return fallback
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

async function applyVocabItem(db: D1Database, item: Record<string, unknown>, serverNow: number): Promise<boolean> {
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

  const row = await db.prepare('SELECT * FROM vocab WHERE lemma=?').bind(lemma).first<Record<string, unknown>>()
  if (!row) {
    await db
      .prepare(
        'INSERT INTO vocab(lemma,word,gloss,pos,phonetic,note,tags,contexts,source,state,' +
          'due_at,interval_days,ease,reps,lapses,last_reviewed_at,created_at,updated_at,deleted_at)' +
          ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
      )
      .bind(
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
          'updated_at=?,deleted_at=? WHERE id=?',
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
      )
      .run()
    return true
  }

  if (mergedContexts.length !== oldContexts.length || mergedTags.length !== oldTags.length) {
    await db
      .prepare('UPDATE vocab SET tags=?, contexts=?, updated_at=? WHERE id=?')
      .bind(JSON.stringify(mergedTags), JSON.stringify(mergedContexts), serverNow, Number(row.id))
      .run()
    return true
  }
  return false
}

async function applySessionItem(db: D1Database, item: Record<string, unknown>, serverNow: number): Promise<boolean> {
  const id = String(item.id ?? '')
  if (!id) return false
  const metaStr = typeof item.meta === 'string' ? item.meta : JSON.stringify(item.meta ?? {})
  const incUpdated = Number(item.updatedAt ?? item.endedAt ?? item.startedAt ?? serverNow)
  const row = await db.prepare('SELECT * FROM sessions WHERE id=?').bind(id).first<Record<string, unknown>>()
  if (!row) {
    await db
      .prepare(
        'INSERT INTO sessions(id,kind,pack_id,mode,planned,answered,correct,meta,started_at,ended_at,updated_at)' +
          ' VALUES(?,?,?,?,?,?,?,?,?,?,?)',
      )
      .bind(
        id,
        String(item.kind ?? ''),
        String(item.packId ?? ''),
        String(item.mode ?? ''),
        Number(item.planned ?? 0),
        Number(item.answered ?? 0),
        Number(item.correct ?? 0),
        metaStr,
        Number(item.startedAt ?? serverNow),
        item.endedAt != null ? Number(item.endedAt) : null,
        Math.max(incUpdated, serverNow),
      )
      .run()
    return true
  }
  if (incUpdated >= Number(row.updated_at ?? 0) || (item.endedAt != null && row.ended_at == null)) {
    await db
      .prepare('UPDATE sessions SET answered=?,correct=?,meta=?,ended_at=?,updated_at=? WHERE id=?')
      .bind(
        Math.max(Number(row.answered ?? 0), Number(item.answered ?? 0)),
        Math.max(Number(row.correct ?? 0), Number(item.correct ?? 0)),
        metaStr,
        item.endedAt != null ? Number(item.endedAt) : row.ended_at,
        Math.max(incUpdated, serverNow),
        id,
      )
      .run()
    return true
  }
  return false
}

async function applyAttemptItem(db: D1Database, item: Record<string, unknown>, serverNow: number): Promise<boolean> {
  const clientId = String(item.clientId ?? '')
  const kind = String(item.kind ?? '')
  if (!clientId || !kind) return false
  const metaStr = typeof item.meta === 'string' ? item.meta : JSON.stringify(item.meta ?? {})
  const res = await db
    .prepare(
      'INSERT OR IGNORE INTO attempts(client_id,kind,ref,pack_id,session_id,input,expected,correct,duration_ms,meta,created_at)' +
        ' VALUES(?,?,?,?,?,?,?,?,?,?,?)',
    )
    .bind(
      clientId,
      kind,
      String(item.ref ?? ''),
      String(item.packId ?? ''),
      String(item.sessionId ?? ''),
      String(item.input ?? ''),
      String(item.expected ?? ''),
      item.correct ? 1 : 0,
      Number(item.durationMs ?? 0),
      metaStr,
      Number(item.createdAt ?? 0) || serverNow,
    )
    .run()
  return (res.meta?.changes ?? 0) > 0
}

async function handleSync(req: Request, env: Env): Promise<Response> {
  const denied = checkSyncAuth(req, env)
  if (denied) return denied

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
    if (await applyVocabItem(env.DB, it, now)) pushedVocab += 1
  }
  let pushedSessions = 0
  for (const it of push.sessions ?? []) {
    if (await applySessionItem(env.DB, it, now)) pushedSessions += 1
  }
  let pushedAttempts = 0
  for (const it of push.attempts ?? []) {
    if (await applyAttemptItem(env.DB, it, now)) pushedAttempts += 1
  }

  const vRows = (
    await env.DB.prepare('SELECT * FROM vocab WHERE updated_at > ? ORDER BY updated_at ASC, id ASC')
      .bind(Number(cursor.vocab ?? 0))
      .all<Record<string, unknown>>()
  ).results

  const sRows = (
    await env.DB.prepare('SELECT * FROM sessions WHERE updated_at > ? ORDER BY updated_at ASC, id ASC')
      .bind(Number(cursor.sessions ?? 0))
      .all<Record<string, unknown>>()
  ).results

  const aRowsAll = (
    await env.DB.prepare('SELECT * FROM attempts WHERE id > ? ORDER BY id ASC LIMIT 2001')
      .bind(Number(cursor.attempts ?? 0))
      .all<Record<string, unknown>>()
  ).results
  const hasMore = aRowsAll.length > 2000
  const aRows = hasMore ? aRowsAll.slice(0, 2000) : aRowsAll

  const packRows = (
    await env.DB.prepare('SELECT id, mtime, summary_json FROM packs').all<Record<string, unknown>>()
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
    authRequired: Boolean((env.SYNC_TOKEN ?? '').trim()),
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

async function routeApi(req: Request, env: Env, url: URL): Promise<Response> {
  const path = url.pathname.replace(/^\/api/, '')
  const method = req.method.toUpperCase()

  if (path === '/health' && method === 'GET') {
    const countRow = await env.DB.prepare('SELECT COUNT(*) AS n FROM packs').first<{ n: number }>()
    const coreHead = await env.BUCKET.head('dict/core_dict.json.gz')
    return json({
      ok: true,
      ts: nowSec(),
      runtime: 'cloudflare-worker',
      packs: { loaded: Number(countRow?.n ?? 0), errors: {} },
      dict: { ready: Boolean(coreHead), coreSize: coreHead?.size ?? 0 },
    })
  }

  // ── Sync ──
  if (path === '/sync' && method === 'POST') return handleSync(req, env)
  if (path === '/sync/export' && method === 'GET') {
    const denied = checkSyncAuth(req, env)
    if (denied) return denied
    const v = (await env.DB.prepare('SELECT * FROM vocab ORDER BY id ASC').all<Record<string, unknown>>()).results
    const s = (await env.DB.prepare('SELECT * FROM sessions ORDER BY started_at ASC').all<Record<string, unknown>>()).results
    const a = (await env.DB.prepare('SELECT * FROM attempts ORDER BY id ASC').all<Record<string, unknown>>()).results
    return json({
      schemaVersion: 2,
      exportedAt: nowSec(),
      vocab: v.map(vocabRowOut),
      sessions: s,
      attempts: a,
    })
  }
  if (path === '/sync/import' && method === 'POST') {
    const denied = checkSyncAuth(req, env)
    if (denied) return denied
    const payload = (await req.json()) as {
      vocab?: Record<string, unknown>[]
      sessions?: Record<string, unknown>[]
      attempts?: Record<string, unknown>[]
    }
    const now = nowSec()
    let vn = 0
    let sn = 0
    let an = 0
    for (const it of payload.vocab ?? []) if (await applyVocabItem(env.DB, it, now)) vn += 1
    for (const it of payload.sessions ?? []) if (await applySessionItem(env.DB, it, now)) sn += 1
    for (const it of payload.attempts ?? []) if (await applyAttemptItem(env.DB, it, now)) an += 1
    return json({ ok: true, merged: { vocab: vn, sessions: sn, attempts: an } })
  }

  // ── Dict (R2) ──
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
    return serveR2Gzip(req, env.BUCKET, 'dict/core_dict.json.gz', 86400)
  }
  const shardMatch = /^\/dict\/shard\/([a-z]|other)$/.exec(path)
  if (shardMatch && method === 'GET') {
    return serveR2Gzip(req, env.BUCKET, `dict/shards/${shardMatch[1]}.json.gz`, 604800)
  }

  // ── Audio (R2) ──
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
    // 若 R2 未缓存则直接返回 404，前端 audio.ts 自动无缝降级为浏览器原生英音朗读
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

  // ── Packs (D1) ──
  if (path === '/packs' && method === 'GET') {
    const rows = (await env.DB.prepare('SELECT summary_json FROM packs').all<{ summary_json: string }>()).results
    const items = rows.map((r) => safeJsonParse(r.summary_json, {})).filter(Boolean)
    return json({ items, errors: {} })
  }

  if (path === '/packs/from-export' && method === 'POST') {
    const denied = checkSyncAuth(req, env)
    if (denied) return denied
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
        const exRow = await env.DB.prepare('SELECT detail_json FROM packs WHERE id=?').bind(candidateId).first<{ detail_json: string }>()
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
        const exRow = await env.DB.prepare('SELECT detail_json FROM packs WHERE id=?').bind(built.packId).first<{ detail_json: string }>()
        if (exRow) existingDetail = safeJsonParse(exRow.detail_json, null)
      }
      const exists = Boolean(existingDetail)
      if (!body.dryRun) {
        const mt = nowSec()
        await env.DB.prepare(
          'INSERT INTO packs(id,kind,origin,title,mtime,summary_json,detail_json) VALUES(?,?,?,?,?,?,?) ' +
            'ON CONFLICT(id) DO UPDATE SET title=excluded.title, mtime=excluded.mtime, summary_json=excluded.summary_json, detail_json=excluded.detail_json',
        )
          .bind(
            built.packId,
            'reading',
            String(built.detail.origin ?? 'custom'),
            String(built.detail.meta.title ?? built.packId),
            mt,
            JSON.stringify(built.summary),
            JSON.stringify(built.detail),
          )
          .run()
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
        historyRecorded: false,
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
    const row = await env.DB.prepare('SELECT detail_json FROM packs WHERE id=?').bind(pid).first<{ detail_json: string }>()
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
    const denied = checkSyncAuth(req, env)
    if (denied) return denied
    const pid = decodeURIComponent(packAnalysisMatch[1])
    const row = await env.DB.prepare('SELECT detail_json, summary_json FROM packs WHERE id=?').bind(pid).first<{
      detail_json: string
      summary_json: string
    }>()
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
        await env.DB.prepare('UPDATE packs SET mtime=?, summary_json=?, detail_json=? WHERE id=?')
          .bind(mt, JSON.stringify(summary), JSON.stringify(detail), pid)
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
    const row = await env.DB.prepare('SELECT detail_json FROM packs WHERE id=?').bind(pid).first<{ detail_json: string }>()
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
