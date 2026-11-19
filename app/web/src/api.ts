import type { Book, ParsedItem, PrepareProgress, Question, Voice } from './types'

const BASE = '/api'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    let msg = `请求失败 (${res.status})`
    try {
      const data = await res.json()
      if (data?.detail) msg = typeof data.detail === 'string' ? data.detail : msg
    } catch {
      /* 非 JSON 响应，用默认文案 */
    }
    throw new Error(msg)
  }
  return res.json() as Promise<T>
}

export const api = {
  books: () => req<Book[]>('/books'),
  book: (id: string) => req<Book>(`/books/${id}`),
  questions: (id: string) => req<{ items: Question[] }>(`/books/${id}/questions`),
  createBook: (payload: { name: string; text: string; voice?: string }) =>
    req<{ id: string; name: string; count: number; blanks: number }>('/books', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  deleteBook: (id: string) => req<{ ok: true }>(`/books/${id}`, { method: 'DELETE' }),
  resetBook: (id: string) => req<{ ok: true }>(`/books/${id}/reset`, { method: 'POST' }),
  prepare: (id: string) => req<PrepareProgress>(`/books/${id}/prepare`),
  parse: (text: string) =>
    req<{ count: number; blanks: number; items: ParsedItem[] }>('/parse', {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),
  saveProgress: (payload: {
    questionId: number
    status: string
    attempts: number
    final: string
  }) =>
    req<{ ok: true }>('/progress', { method: 'POST', body: JSON.stringify(payload) }),
  voices: () =>
    req<{ default: string; rate: string; items: Voice[] }>('/voices'),
  tts: (text: string, voice?: string) =>
    req<{ url: string }>('/tts', { method: 'POST', body: JSON.stringify({ text, voice }) }),
}
