import type {
  DailyItem,
  DictAnswerResult,
  DictSession,
  DictSummary,
  Overview,
  PackDetail,
  PackStats,
  PackSummary,
  ReadingSubmit,
  ReviewGrade,
  VocabItem,
  VocabStats,
  WeakWord,
} from './types'

const BASE = '/api'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
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
  packs: () => req<{ items: PackSummary[] }>('/packs'),
  pack: (id: string, answers = false) =>
    req<PackDetail>(`/packs/${encodeURIComponent(id)}${answers ? '?answers=1' : ''}`),

  vocabList: (params: {
    q?: string
    packId?: string
    state?: string
    due?: boolean
    limit?: number
    offset?: number
  }) => req<{ total: number; items: VocabItem[] }>(`/vocab${query(params)}`),

  vocabAdd: (payload: {
    lemma: string
    word?: string
    gloss?: string
    pos?: string
    source?: string
    context?: {
      packId?: string
      sentenceId?: string
      en?: string
      zh?: string
      para?: number
    }
  }) =>
    req<{ created: boolean; item: VocabItem }>('/vocab', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  vocabPatch: (id: number, payload: { note?: string; gloss?: string; tags?: string[] }) =>
    req<{ item: VocabItem }>(`/vocab/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

  vocabDelete: (id: number) => req<{ ok: true }>(`/vocab/${id}`, { method: 'DELETE' }),

  vocabReviewQueue: (limit = 20) =>
    req<{ items: VocabItem[] }>(`/vocab/review?limit=${limit}`),

  vocabReview: (id: number, grade: ReviewGrade, durationMs = 0) =>
    req<{ item: VocabItem; nextDueAt: number; intervalDays: number; state: string }>(
      `/vocab/${id}/review`,
      { method: 'POST', body: JSON.stringify({ grade, durationMs }) },
    ),

  vocabStats: () => req<VocabStats>('/vocab/stats'),

  dictationSession: (payload: {
    packId: string
    mode: 'word' | 'word_in_context' | 'sentence'
    source?: 'vocab' | 'pack' | 'auto'
    limit?: number
  }) =>
    req<DictSession>('/dictation/sessions', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  dictationAnswer: (
    sessionId: string,
    payload: { itemId: string; input: string | string[]; replays?: number; durationMs?: number },
  ) =>
    req<DictAnswerResult>(`/dictation/sessions/${sessionId}/answer`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  dictationFinish: (sessionId: string) =>
    req<DictSummary>(`/dictation/sessions/${sessionId}/finish`, { method: 'POST' }),

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

  readingSubmit: (sessionId: string, answers: Record<string, string>, durationMs: number) =>
    req<ReadingSubmit>(`/reading/sessions/${sessionId}/submit`, {
      method: 'POST',
      body: JSON.stringify({ answers, durationMs }),
    }),

  statsOverview: () => req<Overview>('/stats/overview'),
  statsDaily: (days = 30) =>
    req<{ from: string; to: string; items: DailyItem[] }>(`/stats/daily?days=${days}`),
  statsPacks: () => req<{ items: PackStats[] }>('/stats/packs'),
  statsWeak: (limit = 12) => req<{ items: WeakWord[] }>(`/stats/weak-words?limit=${limit}`),
}

export function ttsUrl(text: string, voice = 'en-GB-SoniaNeural'): string {
  return `${BASE}/tts/audio?text=${encodeURIComponent(text)}&voice=${encodeURIComponent(voice)}`
}
