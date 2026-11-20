export interface PackMeta {
  book: string
  test: string
  passage: string
  title: string
  durationSec?: number
  order?: number
  source?: string
  note?: string
}

export interface PackCounts {
  sentences: number
  questions: number
  words: number
  items: number
}

export interface PackProgress {
  dictation: { attempts: number; correct: number }
  reading: { answered: number; correct: number }
  lastAt: number | null
}

export interface PackSummary {
  id: string
  kind: 'reading' | 'deck'
  origin: 'builtin' | 'custom'
  meta: PackMeta
  counts: PackCounts
  progress?: PackProgress
}

export interface Sentence {
  id: string
  en: string
  zh: string
}

export interface Paragraph {
  no: number
  sentences: Sentence[]
}

export interface Option {
  key: string
  text: string
}

export interface Question {
  no: number
  stem?: string
  options?: Option[]
  answer?: string | string[]
}

export interface QuestionGroup {
  id: string
  type: string
  from?: number
  to?: number
  instruction?: string
  title?: string
  text?: string
  options?: Option[]
  items: Question[]
}

export interface LexEntry {
  pos?: string
  gloss?: string
  phonetic?: string
  note?: string
  raw?: string
}

export interface DeckItem {
  word?: string
  sentence?: string
  translation?: string
  meaning?: string
  pos?: string
  phonetic?: string
  image?: string
  audio?: string
  answers?: string[]
}

export interface PackDetail extends PackSummary {
  paragraphs: Paragraph[]
  questionGroups: QuestionGroup[]
  lexicon: Record<string, LexEntry>
  items: DeckItem[]
}

export interface VocabContext {
  packId?: string
  sentenceId?: string
  en?: string
  zh?: string
  para?: number
}

export interface VocabItem {
  id: number
  lemma: string
  word: string
  gloss: string
  pos: string
  phonetic: string
  note: string
  tags: string[]
  contexts: VocabContext[]
  source: string
  state: 'new' | 'learning' | 'review' | 'suspended'
  dueAt: number
  due: boolean
  intervalDays: number
  ease: number
  reps: number
  lapses: number
  lastReviewedAt: number
  createdAt: number
  updatedAt: number
  audioUrl: string
  audioCached: boolean
}

export type ReviewGrade = 'again' | 'hard' | 'good' | 'easy'

export interface DictItem {
  id: string
  packId: string
  type: 'word' | 'word_in_context' | 'sentence'
  audioText: string
  audioUrl: string
  audioCached: boolean
  text: string
  blankCount: number
  blankLengths: number[]
  hint: {
    gloss?: string
    pos?: string
    phonetic?: string
    context?: string
    contextZh?: string
    image?: string
  }
  source: string
}

export interface DictSession {
  sessionId: string
  packId: string
  mode: 'word' | 'word_in_context' | 'sentence'
  voice: string
  startedAt: number
  items: DictItem[]
}

export interface DictAnswerResult {
  itemId: string
  correct: boolean
  parts: boolean[]
  expected: string[]
  firstTime: boolean
}

export interface DictSummary {
  sessionId: string
  packId: string
  mode: string
  total: number
  answered: number
  correct: number
  accuracy: number
  durationSec: number
  wrong: { itemId: string; answers: string[]; input?: string | string[]; text?: string }[]
  skipped: { itemId: string; answers: string[]; text?: string }[]
}

export interface ReadingResultItem {
  no: number
  group: string
  mine: string | string[]
  answer: string[]
  correct: boolean
}

export interface ReadingSubmit {
  sessionId: string
  durationMs: number
  score: number
  total: number
  accuracy: number
  items: ReadingResultItem[]
  pack: PackDetail
}

export interface TodayStats {
  attempts: number
  correct: number
  accuracy: number
  minutes: number
  dictation: { attempts: number; correct: number }
  reading: { answered: number; correct: number }
  review: number
}

export interface Overview {
  date: string
  today: TodayStats
  streak: { current: number; longest: number; studyDays: number }
  totals: {
    words: number
    dueNow: number
    attempts: number
    correct: number
    dictationAttempts: number
    readingQuestions: number
    packs: number
  }
  lastStudyAt: number | null
}

export interface DailyItem {
  date: string
  dictation: { attempts: number; correct: number }
  reading: { answered: number; correct: number }
  review: number
  attempts: number
  correct: number
  minutes: number
}

export interface PackStats extends PackSummary {
  stats: {
    dictation: { attempts: number; correct: number }
    reading: { answered: number; correct: number }
    bestScore: number | null
    lastAt: number | null
  }
}

export interface WeakWord {
  word: string
  attempts: number
  wrong: number
  gloss: string
  pos: string
  vocabId: number | null
}

export interface VocabStats {
  total: number
  byState: Record<'new' | 'learning' | 'review' | 'suspended', number>
  dueNow: number
  addedToday: number
}
