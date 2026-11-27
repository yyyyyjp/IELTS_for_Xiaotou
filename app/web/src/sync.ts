import { reactive, ref } from 'vue'
import {
  getMeta,
  idbCount,
  idbDelete,
  idbDeleteMany,
  idbGet,
  idbGetAll,
  idbPut,
  idbPutMany,
  setMeta,
  type CachedPackDetail,
  type CompactDictTuple,
  type LocalVocab,
  type OutboxRecord,
} from './localDb'
import { ensureCoreDict } from './localDict'
import type {
  DailyItem,
  Overview,
  PackDetail,
  PackStats,
  PackSummary,
  ReviewGrade,
  SyncAttemptRecord,
  SyncCursor,
  SyncResponse,
  SyncSessionRecord,
  VocabContext,
  VocabItem,
  VocabStats,
  WeakWord,
} from './types'
import { reviewSrs } from './utils/srs'

const CFG_KEY = 'xiaotou.syncCfg'

export interface SyncConfig {
  apiBase: string
  token: string
}

function loadConfig(): SyncConfig {
  try {
    const raw = localStorage.getItem(CFG_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      return {
        apiBase: String(parsed.apiBase ?? '').trim().replace(/\/+$/, ''),
        token: String(parsed.token ?? '').trim(),
      }
    }
  } catch {
    /* ignore */
  }
  return { apiBase: '', token: '' }
}

export const syncConfig = reactive<SyncConfig>(loadConfig())

export function saveSyncConfig(next: Partial<SyncConfig>): void {
  if (next.apiBase !== undefined) {
    syncConfig.apiBase = next.apiBase.trim().replace(/\/+$/, '')
  }
  if (next.token !== undefined) {
    syncConfig.token = next.token.trim()
  }
  try {
    localStorage.setItem(CFG_KEY, JSON.stringify(syncConfig))
  } catch {
    /* ignore */
  }
}

export function apiBaseUrl(): string {
  if (!syncConfig.apiBase) return '/api'
  return syncConfig.apiBase.endsWith('/api') ? syncConfig.apiBase : `${syncConfig.apiBase}/api`
}

export function authHeaders(): Record<string, string> {
  try {
    const jwt = localStorage.getItem('xiaotou.authToken')
    if (jwt) return { Authorization: `Bearer ${jwt}` }
  } catch {
    /* ignore */
  }
  if (!syncConfig.token) return {}
  return { Authorization: `Bearer ${syncConfig.token}` }
}

let onUnauthorized: (() => void) | null = null

export function registerUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn
}

export type SyncPhase = 'synced' | 'syncing' | 'pending' | 'offline' | 'error'

export const isOnline = ref(typeof navigator !== 'undefined' ? navigator.onLine : true)
export const syncPhase = ref<SyncPhase>(isOnline.value ? 'synced' : 'offline')
export const pendingCount = ref(0)
export const lastSyncAt = ref<number | null>(null)
export const lastSyncError = ref('')
export const precachingPacks = ref(false)
export const localCounts = reactive({
  vocab: 0,
  attempts: 0,
  cachedPacks: 0,
})

// 内存快速生词映射（lemma -> id），用于全站 0ms 判断是否已收录
const memSavedVocab = new Map<string, number>()

export function findSavedVocabSync(lemma: string, word: string): number | null {
  const l = lemma.trim().toLowerCase()
  const w = word.trim().toLowerCase()
  return memSavedVocab.get(l) ?? memSavedVocab.get(w) ?? null
}

async function rebuildMemVocab(): Promise<void> {
  const all = await idbGetAll<LocalVocab>('vocab')
  memSavedVocab.clear()
  let active = 0
  for (const v of all) {
    if (!v.deletedAt) {
      memSavedVocab.set(v.lemma.toLowerCase(), v.id)
      active += 1
    }
  }
  localCounts.vocab = active
}

export async function refreshLocalCounts(): Promise<void> {
  await rebuildMemVocab()
  const [attCount, packDetailCount, outboxCount] = await Promise.all([
    idbCount('attempts'),
    idbCount('packs_detail'),
    idbCount('outbox'),
  ])
  localCounts.attempts = attCount
  localCounts.cachedPacks = packDetailCount
  pendingCount.value = outboxCount
  updatePhase()
}

function updatePhase(): void {
  if (!isOnline.value) {
    syncPhase.value = pendingCount.value > 0 ? 'pending' : 'offline'
    return
  }
  if (lastSyncError.value) {
    syncPhase.value = 'error'
    return
  }
  syncPhase.value = pendingCount.value > 0 ? 'pending' : 'synced'
}

function nowSec(): number {
  return Math.floor(Date.now() / 1000)
}

function newClientId(prefix = 'att_'): string {
  const rand =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID().replace(/-/g, '').slice(0, 12)
      : Math.random().toString(36).slice(2, 14)
  return `${prefix}${Date.now().toString(36)}${rand}`
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(apiBaseUrl() + path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
      ...(init?.headers ?? {}),
    },
  })
  if (res.status === 401) {
    onUnauthorized?.()
    throw new Error('登录已失效，请重新登录')
  }
  if (!res.ok) {
    let msg = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') msg = body.detail
    } catch {
      /* ignore */
    }
    throw new Error(msg)
  }
  return (await res.json()) as T
}

// ── 同步调度器（防抖推送 + 指数退避重试 + 增量游标拉取） ──────────────────

let debounceTimer = 0
let retryTimer = 0
let retryAttempt = 0
let inFlight: Promise<boolean> | null = null
let hydratePromise: Promise<void> | null = null

export function scheduleSync(delayMs = 1600): void {
  window.clearTimeout(debounceTimer)
  updatePhase()
  if (!isOnline.value) return
  debounceTimer = window.setTimeout(() => {
    void syncNow()
  }, delayMs)
}

export async function queueOutbox(
  kind: OutboxRecord['kind'],
  key: string,
  payload: unknown,
): Promise<void> {
  const opId = `${kind}:${key}`
  await idbPut<OutboxRecord>('outbox', {
    opId,
    kind,
    key,
    payload,
    ts: Date.now(),
  })
  pendingCount.value = await idbCount('outbox')
  scheduleSync()
}

export async function syncNow(): Promise<boolean> {
  if (inFlight) return inFlight
  if (!isOnline.value) {
    updatePhase()
    return false
  }
  window.clearTimeout(debounceTimer)
  window.clearTimeout(retryTimer)

  inFlight = (async () => {
    syncPhase.value = 'syncing'
    try {
      let hasMore = true
      while (hasMore) {
        const cursor = await getMeta<SyncCursor>('cursor', {
          vocab: 0,
          sessions: 0,
          attempts: 0,
          packs: 0,
        })
        const outbox = await idbGetAll<OutboxRecord>('outbox')
        const push = {
          vocab: outbox.filter((o) => o.kind === 'vocab').map((o) => o.payload),
          sessions: outbox.filter((o) => o.kind === 'session').map((o) => o.payload),
          attempts: outbox.filter((o) => o.kind === 'attempt').map((o) => o.payload),
        }

        const res = await fetchJson<SyncResponse>('/sync', {
          method: 'POST',
          body: JSON.stringify({ cursor, push }),
        })

        // 1. 清理本次已成功送达的 outbox 项（比对 ts 防止清理同步期间刚产生的新修改）
        const ackKeys: string[] = []
        const latestOutbox = await idbGetAll<OutboxRecord>('outbox')
        const sentMap = new Map(outbox.map((o) => [o.opId, o.ts]))
        for (const cur of latestOutbox) {
          if (sentMap.get(cur.opId) === cur.ts) {
            ackKeys.push(cur.opId)
          }
        }
        await idbDeleteMany('outbox', ackKeys)

        // 2. 合并拉取的生词（含墓碑）
        if (res.pull.vocab.length) {
          const toPut: LocalVocab[] = res.pull.vocab.map((v) => ({
            ...v,
            deletedAt: v.deletedAt ?? 0,
          }))
          await idbPutMany('vocab', toPut)
        }

        // 3. 合并拉取的会话与作答事件
        if (res.pull.sessions.length) {
          await idbPutMany('sessions', res.pull.sessions)
        }
        if (res.pull.attempts.length) {
          await idbPutMany('attempts', res.pull.attempts)
        }

        // 4. 合并内容包摘要清单，并清理服务端已删除或已更新 mtime 的旧详情缓存
        if (res.pull.packs.length) {
          await idbPutMany(
            'packs_summary',
            res.pull.packs.map((p) => p.summary),
          )
          for (const changed of res.pull.packs) {
            const cachedDetail = await idbGet<CachedPackDetail>('packs_detail', changed.id)
            if (cachedDetail && cachedDetail.mtime < changed.mtime) {
              await idbDelete('packs_detail', changed.id)
            }
          }
        }
        if (res.pull.allPackIds) {
          const keepSet = new Set(res.pull.allPackIds)
          const existingSummaries = await idbGetAll<PackSummary>('packs_summary')
          const staleIds = existingSummaries.filter((p) => !keepSet.has(p.id)).map((p) => p.id)
          if (staleIds.length) {
            await idbDeleteMany('packs_summary', staleIds)
            await idbDeleteMany('packs_detail', staleIds)
          }
        }

        await setMeta('cursor', res.cursor)
        await setMeta('hydrated', true)
        hasMore = res.pull.hasMore
      }

      const ts = nowSec()
      lastSyncAt.value = ts
      lastSyncError.value = ''
      retryAttempt = 0
      await setMeta('lastSyncAt', ts)
      await refreshLocalCounts()
      return true
    } catch (err) {
      lastSyncError.value = err instanceof Error ? err.message : 'Sync failed'
      syncPhase.value = 'error'
      retryAttempt += 1
      const backoff = Math.min(60_000, 4000 * Math.pow(2, retryAttempt - 1))
      retryTimer = window.setTimeout(() => {
        void syncNow()
      }, backoff)
      return false
    }
  })().finally(() => {
    inFlight = null
  })

  return inFlight
}

export async function ensureHydrated(): Promise<void> {
  const hydrated = await getMeta<boolean>('hydrated', false)
  if (hydrated) return
  if (!hydratePromise) {
    hydratePromise = (async () => {
      await syncNow()
    })().finally(() => {
      hydratePromise = null
    })
  }
  await hydratePromise
}

let bootstrapped = false
let listenersAttached = false

export function resetSyncRuntime(): void {
  window.clearTimeout(debounceTimer)
  window.clearTimeout(retryTimer)
  bootstrapped = false
  inFlight = null
  hydratePromise = null
  retryAttempt = 0
  memSavedVocab.clear()
  pendingCount.value = 0
  lastSyncAt.value = null
  lastSyncError.value = ''
  localCounts.vocab = 0
  localCounts.attempts = 0
  localCounts.cachedPacks = 0
  updatePhase()
}

export function bootstrapSync(): void {
  if (bootstrapped || typeof window === 'undefined') return
  bootstrapped = true

  // 立即并发预热公共离线词库（已缓存时 <150ms 从 IndexedDB 就绪，不等待 syncNow 网络往返）
  void ensureCoreDict(() =>
    fetchJson<{ version: number; count: number; entries: CompactDictTuple[] }>('/dict/bundle'),
  )

  void (async () => {
    lastSyncAt.value = await getMeta<number | null>('lastSyncAt', null)
    await refreshLocalCounts()
    await syncNow()
  })()

  if (listenersAttached) return
  listenersAttached = true

  window.addEventListener('online', () => {
    isOnline.value = true
    lastSyncError.value = ''
    if (bootstrapped) void syncNow()
  })

  window.addEventListener('offline', () => {
    isOnline.value = false
    updatePhase()
  })

  document.addEventListener('visibilitychange', () => {
    if (bootstrapped && document.visibilityState === 'visible' && isOnline.value) {
      const elapsed = nowSec() - (lastSyncAt.value ?? 0)
      if (elapsed > 15 || pendingCount.value > 0) {
        void syncNow()
      }
    }
  })

  window.setInterval(() => {
    if (bootstrapped && document.visibilityState === 'visible' && isOnline.value) {
      void syncNow()
    }
  }, 60_000)
}

// ── 本地优先读写实现（0ms 响应） ──────────────────────────────────────────

function lemmaKey(s: string): string {
  return s.trim().toLowerCase().replace(/\s+/g, ' ').slice(0, 80)
}

function mergeContexts(a: VocabContext[], b: VocabContext[]): VocabContext[] {
  const out: VocabContext[] = []
  const seen = new Set<string>()
  for (const ctx of [...a, ...b]) {
    if (!ctx || (!ctx.en && !ctx.zh)) continue
    const k = `${ctx.packId ?? ''}|${ctx.sentenceId ?? ''}|${ctx.en ?? ''}`
    if (seen.has(k)) continue
    seen.add(k)
    out.push(ctx)
  }
  return out
}

function hydrateVocabComputed(v: LocalVocab, now: number): VocabItem {
  return {
    ...v,
    due: v.state !== 'suspended' && v.dueAt <= now,
  }
}

export async function localVocabList(params: {
  q?: string
  packId?: string
  state?: string
  due?: boolean
  limit?: number
  offset?: number
}): Promise<{ total: number; items: VocabItem[] }> {
  await ensureHydrated()
  const now = nowSec()
  const all = (await idbGetAll<LocalVocab>('vocab')).filter((v) => !v.deletedAt)
  const kw = (params.q ?? '').trim().toLowerCase()

  const filtered = all.filter((v) => {
    if (params.state && v.state !== params.state) return false
    if (params.due && (v.state === 'suspended' || v.dueAt > now)) return false
    if (params.packId && !v.contexts.some((c) => c.packId === params.packId)) return false
    if (kw) {
      const hay = `${v.lemma} ${v.word} ${v.gloss} ${v.contexts.map((c) => `${c.en ?? ''} ${c.zh ?? ''}`).join(' ')}`.toLowerCase()
      if (!hay.includes(kw)) return false
    }
    return true
  })

  filtered.sort((a, b) => a.dueAt - b.dueAt || b.updatedAt - a.updatedAt)
  const offset = params.offset ?? 0
  const limit = params.limit ?? 200
  const sliced = filtered.slice(offset, offset + limit).map((v) => hydrateVocabComputed(v, now))
  return { total: filtered.length, items: sliced }
}

export async function localVocabStats(): Promise<VocabStats> {
  await ensureHydrated()
  const now = nowSec()
  const todayStr = localDateStr(now)
  const all = (await idbGetAll<LocalVocab>('vocab')).filter((v) => !v.deletedAt)
  const byState: VocabStats['byState'] = { new: 0, learning: 0, review: 0, suspended: 0 }
  let dueNow = 0
  let addedToday = 0
  for (const v of all) {
    if (v.state in byState) byState[v.state] += 1
    if (v.state !== 'suspended' && v.dueAt <= now) dueNow += 1
    if (localDateStr(v.createdAt) === todayStr) addedToday += 1
  }
  return { total: all.length, byState, dueNow, addedToday }
}

export async function localVocabAdd(payload: {
  lemma: string
  word?: string
  gloss?: string
  pos?: string
  phonetic?: string
  source?: string
  context?: VocabContext
}): Promise<{ created: boolean; item: VocabItem }> {
  await ensureHydrated()
  const lemma = lemmaKey(payload.lemma || payload.word || '')
  if (!lemma) throw new Error('缺少单词')
  const now = nowSec()
  const existing = await idbGet<LocalVocab>('vocab', lemma)
  const incomingCtx = payload.context ? [payload.context] : []

  let next: LocalVocab
  let created = false

  if (existing && !existing.deletedAt) {
    next = {
      ...existing,
      word: existing.word || payload.word || lemma,
      gloss: existing.gloss || payload.gloss || '',
      pos: existing.pos || payload.pos || '',
      phonetic: existing.phonetic || payload.phonetic || '',
      source: existing.source || payload.source || '',
      contexts: mergeContexts(existing.contexts, incomingCtx),
      updatedAt: now,
      deletedAt: 0,
    }
  } else {
    created = true
    const localId = existing?.id ?? -(Math.floor(Math.random() * 900_000) + 100_000)
    next = {
      id: localId,
      lemma,
      word: payload.word || lemma,
      gloss: payload.gloss || '',
      pos: payload.pos || '',
      phonetic: payload.phonetic || '',
      note: '',
      tags: [],
      contexts: mergeContexts([], incomingCtx),
      source: payload.source || '',
      state: 'new',
      dueAt: now,
      due: true,
      intervalDays: 0,
      ease: 2.4,
      reps: 0,
      lapses: 0,
      lastReviewedAt: 0,
      createdAt: now,
      updatedAt: now,
      deletedAt: 0,
      audioUrl: '',
      audioCached: false,
    }
  }

  await idbPut('vocab', next)
  memSavedVocab.set(lemma, next.id)
  localCounts.vocab = memSavedVocab.size
  await queueOutbox('vocab', lemma, next)
  return { created, item: hydrateVocabComputed(next, now) }
}

async function findLocalVocabById(id: number): Promise<LocalVocab | null> {
  const all = await idbGetAll<LocalVocab>('vocab')
  return all.find((v) => v.id === id && !v.deletedAt) ?? null
}

export async function localVocabPatch(
  id: number,
  payload: { note?: string; gloss?: string; tags?: string[]; state?: VocabItem['state'] },
): Promise<{ item: VocabItem }> {
  await ensureHydrated()
  const row = await findLocalVocabById(id)
  if (!row) throw new Error('生词不存在')
  const now = nowSec()
  const next: LocalVocab = {
    ...row,
    note: payload.note !== undefined ? payload.note : row.note,
    gloss: payload.gloss !== undefined ? payload.gloss : row.gloss,
    tags: payload.tags !== undefined ? payload.tags : row.tags,
    state: payload.state !== undefined ? payload.state : row.state,
    updatedAt: now,
  }
  await idbPut('vocab', next)
  await queueOutbox('vocab', next.lemma, next)
  return { item: hydrateVocabComputed(next, now) }
}

export async function localVocabDelete(id: number): Promise<{ ok: true }> {
  await ensureHydrated()
  const row = await findLocalVocabById(id)
  if (!row) throw new Error('生词不存在')
  const now = nowSec()
  const next: LocalVocab = {
    ...row,
    deletedAt: now,
    updatedAt: now,
  }
  await idbPut('vocab', next)
  memSavedVocab.delete(row.lemma.toLowerCase())
  localCounts.vocab = memSavedVocab.size
  await queueOutbox('vocab', next.lemma, next)
  return { ok: true }
}

export async function localVocabReviewQueue(limit = 20): Promise<{ items: VocabItem[] }> {
  await ensureHydrated()
  const now = nowSec()
  const all = (await idbGetAll<LocalVocab>('vocab')).filter(
    (v) => !v.deletedAt && v.state !== 'suspended' && v.dueAt <= now,
  )
  all.sort((a, b) => a.dueAt - b.dueAt || a.id - b.id)
  return { items: all.slice(0, limit).map((v) => hydrateVocabComputed(v, now)) }
}

export async function localVocabReview(
  id: number,
  grade: ReviewGrade,
  durationMs = 0,
): Promise<{ item: VocabItem; nextDueAt: number; intervalDays: number; state: string }> {
  await ensureHydrated()
  const row = await findLocalVocabById(id)
  if (!row) throw new Error('生词不存在')
  const now = nowSec()
  const nxt = reviewSrs(row, grade, now)
  const updated: LocalVocab = {
    ...row,
    state: nxt.state,
    ease: nxt.ease,
    intervalDays: nxt.intervalDays,
    reps: nxt.reps,
    lapses: nxt.lapses,
    dueAt: nxt.dueAt,
    lastReviewedAt: nxt.lastReviewedAt,
    updatedAt: now,
  }
  const attempt: SyncAttemptRecord = {
    clientId: newClientId('att_'),
    kind: 'vocab_review',
    ref: row.lemma,
    packId: '',
    sessionId: '',
    input: grade,
    expected: '',
    correct: grade === 'again' ? 0 : 1,
    durationMs,
    meta: { vocabId: id, grade, intervalDays: nxt.intervalDays },
    createdAt: now,
  }
  await idbPut('vocab', updated)
  await idbPut('attempts', attempt)
  localCounts.attempts += 1
  await queueOutbox('vocab', updated.lemma, updated)
  await queueOutbox('attempt', attempt.clientId, attempt)
  return {
    item: hydrateVocabComputed(updated, now),
    nextDueAt: nxt.dueAt,
    intervalDays: nxt.intervalDays,
    state: nxt.state,
  }
}

// ── 内容包与本地统计聚合 ──────────────────────────────────────────────────

function localDateStr(unixSec: number): string {
  const d = new Date(unixSec * 1000)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

async function computePackProgressMap(): Promise<Record<string, PackSummary['progress']>> {
  const attempts = await idbGetAll<SyncAttemptRecord>('attempts')
  const map: Record<
    string,
    { dictation: { attempts: number; correct: number }; reading: { answered: number; correct: number }; lastAt: number | null }
  > = {}
  for (const a of attempts) {
    if (!a.packId) continue
    const slot = (map[a.packId] ??= {
      dictation: { attempts: 0, correct: 0 },
      reading: { answered: 0, correct: 0 },
      lastAt: null,
    })
    if (a.kind.startsWith('dictation_')) {
      slot.dictation.attempts += 1
      if (a.correct) slot.dictation.correct += 1
    } else if (a.kind === 'reading_question') {
      slot.reading.answered += 1
      if (a.correct) slot.reading.correct += 1
    }
    if (slot.lastAt === null || a.createdAt > slot.lastAt) {
      slot.lastAt = a.createdAt
    }
  }
  return map
}

export async function localPacksList(
  fallbackFetch: () => Promise<{ items: PackSummary[] }>,
): Promise<{ items: PackSummary[] }> {
  await ensureHydrated()
  const summaries = await idbGetAll<PackSummary>('packs_summary')
  if (!summaries.length && isOnline.value) {
    const fresh = await fallbackFetch()
    await idbPutMany('packs_summary', fresh.items)
    return fresh
  }
  const progMap = await computePackProgressMap()
  const emptyProg = {
    dictation: { attempts: 0, correct: 0 },
    reading: { answered: 0, correct: 0 },
    lastAt: null,
  }
  const items = summaries.map((s) => ({
    ...s,
    progress: progMap[s.id] ?? s.progress ?? emptyProg,
  }))
  items.sort(
    (a, b) =>
      (a.meta.order || 999) - (b.meta.order || 999) ||
      (a.meta.book || '').localeCompare(b.meta.book || '') ||
      (a.meta.test || '').localeCompare(b.meta.test || '') ||
      (a.meta.passage || '').localeCompare(b.meta.passage || ''),
  )
  return { items }
}

export async function localPackDetail(
  id: string,
  withAnswers: boolean,
  networkFetch: () => Promise<PackDetail>,
): Promise<PackDetail> {
  const cached = await idbGet<CachedPackDetail>('packs_detail', id)
  if (cached && (cached.withAnswers || !withAnswers)) {
    return cached.detail
  }
  const detail = await networkFetch()
  await cachePackDetail(detail, withAnswers)
  return detail
}

export async function cachePackDetail(
  detail: PackDetail,
  withAnswers: boolean,
  mtime = nowSec(),
): Promise<void> {
  await idbPut<CachedPackDetail>('packs_detail', {
    id: detail.id,
    withAnswers,
    mtime,
    detail,
  })
  localCounts.cachedPacks = await idbCount('packs_detail')
}

export async function invalidatePackCache(id: string): Promise<void> {
  await idbDelete('packs_detail', id)
  await syncNow()
}

export async function precacheAllPacks(
  fetchDetail: (id: string) => Promise<PackDetail>,
): Promise<number> {
  if (precachingPacks.value) return 0
  precachingPacks.value = true
  try {
    await syncNow()
    const summaries = await idbGetAll<PackSummary>('packs_summary')
    let cached = 0
    for (const s of summaries) {
      const existing = await idbGet<CachedPackDetail>('packs_detail', s.id)
      if (existing?.withAnswers) {
        cached += 1
        continue
      }
      const detail = await fetchDetail(s.id)
      await cachePackDetail(detail, true)
      cached += 1
    }
    return cached
  } finally {
    precachingPacks.value = false
  }
}

export async function localStatsDaily(days = 30): Promise<{
  from: string
  to: string
  items: DailyItem[]
}> {
  await ensureHydrated()
  const now = nowSec()
  const since = now - days * 86400
  const [attempts, sessions] = await Promise.all([
    idbGetAll<SyncAttemptRecord>('attempts'),
    idbGetAll<SyncSessionRecord>('sessions'),
  ])

  const buckets = new Map<string, DailyItem>()
  const ensureBucket = (d: string): DailyItem => {
    let b = buckets.get(d)
    if (!b) {
      b = {
        date: d,
        dictation: { attempts: 0, correct: 0 },
        reading: { answered: 0, correct: 0 },
        review: 0,
        attempts: 0,
        correct: 0,
        minutes: 0,
      }
      buckets.set(d, b)
    }
    return b
  }

  for (const a of attempts) {
    if (a.createdAt < since) continue
    const b = ensureBucket(localDateStr(a.createdAt))
    if (a.kind.startsWith('dictation')) {
      b.dictation.attempts += 1
      b.dictation.correct += a.correct ? 1 : 0
    } else if (a.kind === 'reading_question') {
      b.reading.answered += 1
      b.reading.correct += a.correct ? 1 : 0
    } else if (a.kind === 'vocab_review') {
      b.review += 1
    }
    b.attempts += 1
    b.correct += a.correct ? 1 : 0
  }

  const secsByDay = new Map<string, number>()
  for (const s of sessions) {
    if (s.endedAt == null || s.startedAt < since) continue
    const d = localDateStr(s.startedAt)
    secsByDay.set(d, (secsByDay.get(d) ?? 0) + Math.max(0, s.endedAt - s.startedAt))
  }
  for (const [d, secs] of secsByDay.entries()) {
    ensureBucket(d).minutes = Math.round((secs / 60) * 10) / 10
  }

  const items: DailyItem[] = []
  const baseDate = new Date()
  baseDate.setHours(12, 0, 0, 0)
  baseDate.setDate(baseDate.getDate() - (days - 1))
  for (let i = 0; i < days; i += 1) {
    const cur = new Date(baseDate.getTime() + i * 86400 * 1000)
    const dStr = localDateStr(Math.floor(cur.getTime() / 1000))
    items.push(
      buckets.get(dStr) ?? {
        date: dStr,
        dictation: { attempts: 0, correct: 0 },
        reading: { answered: 0, correct: 0 },
        review: 0,
        attempts: 0,
        correct: 0,
        minutes: 0,
      },
    )
  }

  return {
    from: items[0]?.date ?? localDateStr(now),
    to: items[items.length - 1]?.date ?? localDateStr(now),
    items,
  }
}

function computeStreak(daysSet: Set<string>): { current: number; longest: number } {
  if (!daysSet.size) return { current: 0, longest: 0 }
  const ordered = Array.from(daysSet).sort()
  let longest = 1
  let run = 1
  for (let i = 1; i < ordered.length; i += 1) {
    const prev = Date.parse(`${ordered[i - 1]}T12:00:00`)
    const cur = Date.parse(`${ordered[i]}T12:00:00`)
    run = Math.round((cur - prev) / 86400000) === 1 ? run + 1 : 1
    if (run > longest) longest = run
  }

  const cursor = new Date()
  cursor.setHours(12, 0, 0, 0)
  const fmt = (d: Date) => localDateStr(Math.floor(d.getTime() / 1000))
  if (!daysSet.has(fmt(cursor))) {
    cursor.setDate(cursor.getDate() - 1)
  }
  let current = 0
  while (daysSet.has(fmt(cursor))) {
    current += 1
    cursor.setDate(cursor.getDate() - 1)
  }
  return { current, longest }
}

export async function localStatsOverview(): Promise<Overview> {
  await ensureHydrated()
  const now = nowSec()
  const today = localDateStr(now)
  const [daily1, attempts, vocab, summaries] = await Promise.all([
    localStatsDaily(1),
    idbGetAll<SyncAttemptRecord>('attempts'),
    idbGetAll<LocalVocab>('vocab'),
    idbGetAll<PackSummary>('packs_summary'),
  ])

  const t = daily1.items[0] ?? {
    date: today,
    dictation: { attempts: 0, correct: 0 },
    reading: { answered: 0, correct: 0 },
    review: 0,
    attempts: 0,
    correct: 0,
    minutes: 0,
  }

  const allDays = new Set<string>()
  let totalCorrect = 0
  let dictAttempts = 0
  let readQuestions = 0
  let lastStudyAt: number | null = null

  for (const a of attempts) {
    allDays.add(localDateStr(a.createdAt))
    if (a.correct) totalCorrect += 1
    if (a.kind.startsWith('dictation_')) dictAttempts += 1
    if (a.kind === 'reading_question') readQuestions += 1
    if (lastStudyAt === null || a.createdAt > lastStudyAt) lastStudyAt = a.createdAt
  }

  const activeVocab = vocab.filter((v) => !v.deletedAt)
  const dueNow = activeVocab.filter((v) => v.state !== 'suspended' && v.dueAt <= now).length
  const { current, longest } = computeStreak(allDays)

  return {
    date: today,
    today: {
      attempts: t.attempts,
      correct: t.correct,
      accuracy: t.attempts ? Math.round((t.correct / t.attempts) * 10000) / 10000 : 0,
      minutes: t.minutes,
      dictation: t.dictation,
      reading: t.reading,
      review: t.review,
    },
    streak: { current, longest, studyDays: allDays.size },
    totals: {
      words: activeVocab.length,
      dueNow,
      attempts: attempts.length,
      correct: totalCorrect,
      dictationAttempts: dictAttempts,
      readingQuestions: readQuestions,
      packs: summaries.length,
    },
    lastStudyAt,
  }
}

export async function localStatsPacks(): Promise<{ items: PackStats[] }> {
  await ensureHydrated()
  const [summaries, attempts, sessions] = await Promise.all([
    idbGetAll<PackSummary>('packs_summary'),
    idbGetAll<SyncAttemptRecord>('attempts'),
    idbGetAll<SyncSessionRecord>('sessions'),
  ])

  const prog = await computePackProgressMap()
  const bestMap = new Map<string, number>()
  for (const s of sessions) {
    if (s.kind === 'reading' && s.planned > 0 && s.answered > 0) {
      const ratio = s.correct / s.planned
      const prev = bestMap.get(s.packId)
      if (prev === undefined || ratio > prev) bestMap.set(s.packId, ratio)
    }
  }
  void attempts

  const out: PackStats[] = summaries.map((s) => {
    const p = prog[s.id]
    const best = bestMap.get(s.id)
    return {
      ...s,
      stats: {
        dictation: p?.dictation ?? { attempts: 0, correct: 0 },
        reading: p?.reading ?? { answered: 0, correct: 0 },
        bestScore: best !== undefined ? Math.round(best * 10000) / 10000 : null,
        lastAt: p?.lastAt ?? null,
      },
    }
  })

  out.sort((a, b) => (b.stats.lastAt ?? 0) - (a.stats.lastAt ?? 0))
  return { items: out }
}

export async function localStatsWeak(limit = 12): Promise<{ items: WeakWord[] }> {
  await ensureHydrated()
  const [attempts, vocab] = await Promise.all([
    idbGetAll<SyncAttemptRecord>('attempts'),
    idbGetAll<LocalVocab>('vocab'),
  ])

  const counts = new Map<string, { n: number; c: number }>()
  for (const a of attempts) {
    if (a.kind !== 'dictation_word') continue
    const slot = counts.get(a.ref) ?? { n: 0, c: 0 }
    slot.n += 1
    if (a.correct) slot.c += 1
    counts.set(a.ref, slot)
  }

  const vocabByLemma = new Map<string, LocalVocab>()
  for (const v of vocab) {
    if (!v.deletedAt) vocabByLemma.set(v.lemma, v)
  }

  const ranked = Array.from(counts.entries())
    .filter(([, v]) => v.c < v.n)
    .map(([word, v]) => ({ word, attempts: v.n, wrong: v.n - v.c }))
    .sort((a, b) => b.wrong - a.wrong || b.attempts - a.attempts)
    .slice(0, limit)

  return {
    items: ranked.map((item) => {
      const v = vocabByLemma.get(item.word)
      return {
        ...item,
        gloss: v?.gloss ?? '',
        pos: v?.pos ?? '',
        vocabId: v?.id ?? null,
      }
    }),
  }
}

// ── 本地快照导出 / 导入兜底 ───────────────────────────────────────────────

export async function buildLocalSnapshot(): Promise<Record<string, unknown>> {
  const [vocab, sessions, attempts] = await Promise.all([
    idbGetAll<LocalVocab>('vocab'),
    idbGetAll<SyncSessionRecord>('sessions'),
    idbGetAll<SyncAttemptRecord>('attempts'),
  ])
  return {
    schemaVersion: 2,
    exportedAt: nowSec(),
    vocab,
    sessions,
    attempts,
  }
}

export async function restoreLocalSnapshot(raw: Record<string, unknown>): Promise<void> {
  const vocab = Array.isArray(raw.vocab) ? (raw.vocab as LocalVocab[]) : []
  const sessions = Array.isArray(raw.sessions) ? (raw.sessions as SyncSessionRecord[]) : []
  const attempts = Array.isArray(raw.attempts) ? (raw.attempts as SyncAttemptRecord[]) : []

  if (vocab.length) {
    await idbPutMany(
      'vocab',
      vocab.map((v) => ({ ...v, deletedAt: v.deletedAt ?? 0 })),
    )
    for (const v of vocab) {
      await queueOutbox('vocab', v.lemma, v)
    }
  }
  if (sessions.length) {
    await idbPutMany('sessions', sessions)
    for (const s of sessions) {
      await queueOutbox('session', s.id, s)
    }
  }
  if (attempts.length) {
    await idbPutMany('attempts', attempts)
    for (const a of attempts) {
      await queueOutbox('attempt', a.clientId, a)
    }
  }
  await refreshLocalCounts()
  void syncNow()
}
