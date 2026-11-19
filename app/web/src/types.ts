export interface Book {
  id: string
  name: string
  intro: string
  voice: string
  source: 'builtin' | 'import'
  createdAt: number
  total: number
  done: number
  pendingAudio: number
  prepare?: PrepareProgress
}

export interface PrepareProgress {
  total: number
  done: number
  failed: number
  ready: boolean
}

export interface Question {
  id: number
  bookId: string
  ord: number
  text: string
  answers: string[]
  translation: string
  meaning: string
  title: string
  audioUrl: string
  sourceAudio: string
  status: 'todo' | 'correct' | 'wrong' | 'skipped'
  attempts: number
  final: '' | 'direct' | 'rewrite'
}

export interface ParsedItem {
  text: string
  answers: string[]
  translation: string
  meaning: string
  title: string
}

export interface Voice {
  id: string
  label: string
  lang: string
}

/** 一个空：要么是纯文本，要么是可填的槽位 */
export interface Segment {
  type: 'text' | 'blank'
  value: string
  index: number
}
