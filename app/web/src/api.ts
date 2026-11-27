import {
  localDictationAnswer,
  localDictationFinish,
  localDictationStart,
} from './localDictation'
import {
  apiBaseUrl,
  authHeaders,
  cachePackDetail,
  invalidatePackCache,
  localPackDetail,
  localPacksList,
  localStatsDaily,
  localStatsOverview,
  localStatsPacks,
  localStatsWeak,
  localVocabAdd,
  localVocabDelete,
  localVocabList,
  localVocabPatch,
  localVocabReview,
  localVocabReviewQueue,
  localVocabStats,
  syncNow,
} from './sync'
import type {
  DailyItem,
  DictAnswerResult,
  DictLookupResult,
  DictSession,
  DictStatus,
  DictSummary,
  Overview,
  PackDetail,
  PackImportResult,
  PackPromptResult,
  PackStats,
  PackSummary,
  ReadingSubmit,
  ReviewGrade,
  VocabItem,
  VocabStats,
  WeakWord,
} from './types'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(apiBaseUrl() + path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
      ...(init?.headers ?? {}),
    },
  })
  if (!res.ok) {
    let message = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') message = body.detail
      else if (Array.isArray(body?.detail)) message = body.detail[0]?.msg ?? message
    } catch {
      /* 非 JSON */
    }
    throw new ApiError(res.status, message)
  }
  const type = res.headers.get('content-type') ?? ''
  if (!type.includes('application/json')) return (await res.text()) as T
  return (await res.json()) as T
}

function query(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === '' || value === false) continue
    search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const api = {
  packs: () => localPacksList(() => req<{ items: PackSummary[] }>('/packs')),

  pack: (id: string, answers = false) =>
    localPackDetail(id, answers, () =>
      req<PackDetail>(`/packs/${encodeURIComponent(id)}${answers ? '?answers=1' : ''}`),
    ),

  packNetwork: (id: string, answers = true) =>
    req<PackDetail>(`/packs/${encodeURIComponent(id)}${answers ? '?answers=1' : ''}`),

  vocabList: (params: {
    q?: string
    packId?: string
    state?: string
    due?: boolean
    limit?: number
    offset?: number
  }) => localVocabList(params),

  vocabAdd: (payload: {
    lemma: string
    word?: string
    gloss?: string
    pos?: string
    phonetic?: string
    source?: string
    context?: {
      packId?: string
      sentenceId?: string
      en?: string
      zh?: string
      para?: number
    }
  }) => localVocabAdd(payload),

  vocabPatch: (
    id: number,
    payload: { note?: string; gloss?: string; tags?: string[]; state?: VocabItem['state'] },
  ) => localVocabPatch(id, payload),

  vocabDelete: (id: number) => localVocabDelete(id),

  vocabReviewQueue: (limit = 20) => localVocabReviewQueue(limit),

  vocabReview: (id: number, grade: ReviewGrade, durationMs = 0) =>
    localVocabReview(id, grade, durationMs),

  vocabStats: () => localVocabStats(),

  dictationSession: (payload: {
    packId: string
    mode: 'word' | 'word_in_context' | 'sentence'
    source?: 'vocab' | 'pack' | 'auto'
    limit?: number
  }): Promise<DictSession> =>
    localDictationStart(payload, {
      fetchPackDetail: (id) => api.pack(id, true),
      fetchPacksList: () => api.packs(),
      buildTtsUrl: (text, voice) => ttsUrl(text, voice),
    }),

  dictationAnswer: (
    sessionId: string,
    payload: { itemId: string; input: string | string[]; replays?: number; durationMs?: number },
  ): Promise<DictAnswerResult> => localDictationAnswer(sessionId, payload),

  dictationFinish: (sessionId: string): Promise<DictSummary> => localDictationFinish(sessionId),

  readingSession: (packId: string, nos: number[] = []) =>
    req<{
      sessionId: string
      startedAt: number
      nos: number[]
      pack: PackDetail
    }>('/reading/sessions', {
      method: 'POST',
      body: JSON.stringify({ packId, nos }),
    }),

  readingSubmit: async (
    sessionId: string,
    answers: Record<string, string>,
    durationMs: number,
  ) => {
    const res = await req<ReadingSubmit>(`/reading/sessions/${sessionId}/submit`, {
      method: 'POST',
      body: JSON.stringify({ answers, durationMs }),
    })
    if (res.pack) {
      await cachePackDetail(res.pack, true)
    }
    void syncNow()
    return res
  },

  statsOverview: (): Promise<Overview> => localStatsOverview(),
  statsDaily: (days = 30): Promise<{ from: string; to: string; items: DailyItem[] }> =>
    localStatsDaily(days),
  statsPacks: (): Promise<{ items: PackStats[] }> => localStatsPacks(),
  statsWeak: (limit = 12): Promise<{ items: WeakWord[] }> => localStatsWeak(limit),

  dictStatus: () => req<DictStatus>('/dict/status'),
  dictShard: (letter: string) =>
    req<{ version: number; shard: string; count: number; entries: [string, string, string, string, number, string][] }>(
      `/dict/shard/${encodeURIComponent(letter)}`,
    ),
  dictLookup: (q: string, packId?: string) =>
    req<DictLookupResult>(`/dict/lookup${query({ q, packId })}`),

  packImportFromExport: async (payload: {
    passage: Record<string, unknown>
    questions: Record<string, unknown>[]
    groups: Record<string, unknown>[]
    attempt?: Record<string, unknown> | null
    analysisText?: string
    id?: string
    keepLexicon?: boolean
    recordHistory?: boolean
    dryRun?: boolean
  }) => {
    const res = await req<PackImportResult>('/packs/from-export', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    if (!payload.dryRun) {
      await invalidatePackCache(res.id)
    }
    return res
  },

  packExportPrompt: (payload: {
    passage: Record<string, unknown>
    questions: Record<string, unknown>[]
    groups: Record<string, unknown>[]
    attempt?: Record<string, unknown> | null
  }) =>
    req<PackPromptResult>('/packs/export-prompt', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  packUpdateAnalysis: async (
    packId: string,
    payload: { analysisText: string; keepLexicon?: boolean; dryRun?: boolean },
  ) => {
    const res = await req<PackImportResult>(`/packs/${encodeURIComponent(packId)}/analysis`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    if (!payload.dryRun) {
      await invalidatePackCache(res.id)
    }
    return res
  },

  packPrompt: (packId: string) =>
    req<PackPromptResult>(`/packs/${encodeURIComponent(packId)}/prompt`),
}

export function ttsUrl(text: string, voice = 'en-GB-SoniaNeural'): string {
  return `${apiBaseUrl()}/tts/audio?text=${encodeURIComponent(text)}&voice=${encodeURIComponent(voice)}`
}
