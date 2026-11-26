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

export interface Attempt {
  source: string
  submittedAt: string
  durationSec: number
  score: number
  total: number
  answered: number
  blank: number
  wrong: number
  accuracy: number
  byType: { label: string; correct?: number; total?: number; accuracy?: number }[]
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
  attempt?: Attempt | null
  hasReview?: boolean
  hasGuide?: boolean
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
  mine?: string
  correct?: boolean | null
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

export interface Cite {
  p: number
  b: number[]
}

export interface ReviewItem {
  no: number
  label?: string
  tag?: string
  diag?: string
  chain?: string
  cites?: Cite[]
}

export interface ReviewRow {
  no: number
  minePhrase?: string
  corPhrase?: string
  src?: string
  diag?: string
  cites?: Cite[]
}

export interface ReviewSection {
  id: string
  kind: string
  title: string
  from?: number | null
  to?: number | null
  diag?: string
  note?: string
  cites?: Cite[]
  items?: ReviewItem[]
  rows?: ReviewRow[]
}

export interface ReviewDoc {
  kicker?: string
  title?: string
  lede?: string
  stats?: [string, string, number][]
  bars?: [string, number, string][]
  sections?: ReviewSection[]
  diagnoses?: { n: string; t: string; p: string }[]
  actions?: string[]
  end?: string
}

export interface GuideCell {
  n: number
  f: string
  s: string
}

export interface GuideBlock {
  t: string
  p: string
}

export interface GuideRow {
  n: number
  w: string
  s: string
  d: string
}

export interface GuideTerm {
  k: string
  en?: string
  d: string
}

export interface GuideDoc {
  kicker?: string
  title?: string
  lede?: string
  thesis?: string
  structureTitle?: string
  band?: GuideCell[]
  legend?: { s: string; text: string }[]
  argument?: {
    negativeTitle?: string
    negative?: GuideBlock[]
    positiveTitle?: string
    positive?: GuideBlock[]
    punch?: string
  }
  rows?: GuideRow[]
  terms?: GuideTerm[]
  echo?: { neg?: string; pos?: string; note?: string }
  why?: GuideBlock[]
  side?: string
  end?: string
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
  review?: ReviewDoc | null
  guide?: GuideDoc | null
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
  deletedAt?: number
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

export interface DictLookupToken {
  word: string
  lemma: string
  phonetic: string
  pos: string
  gloss: string
  formNote: string
}

export interface DictLookupResult {
  query: string
  found: boolean
  source: 'pack' | 'ecdict' | 'tokens' | 'none'
  word: string
  lemma: string
  phonetic: string
  pos: string
  gloss: string
  dictGloss: string
  definition: string
  tags: string[]
  collins: number
  oxford: boolean
  formNote: string
  tokens: DictLookupToken[]
  saved: boolean
  vocabId: number | null
  dictReady: boolean
}

export interface DictStatus {
  ready: boolean
  entries: number
  path: string
}

export interface AnalysisSummary {
  hasReview: boolean
  reviewTitle: string
  sectionCount: number
  coveredQuestions: number
  diagnosisCount: number
  hasGuide: boolean
  guideTitle: string
  bandCount: number
  lexiconCount: number
}

export interface PackImportResult {
  id: string
  exists: boolean
  created?: boolean
  dryRun: boolean
  meta: PackMeta
  counts?: {
    paragraphs: number
    sentences: number
    questions: number
    words: number
  }
  attempt?: Attempt | null
  analysis: AnalysisSummary
  warnings: string[]
  historyRecorded?: boolean
}

export interface PackPromptResult {
  id: string
  title: string
  label: string
  prompt: string
}

export interface SyncCursor {
  vocab: number
  sessions: number
  attempts: number
  packs: number
}

export interface SyncSessionRecord {
  id: string
  kind: 'dictation' | 'reading' | string
  packId: string
  mode: string
  planned: number
  answered: number
  correct: number
  meta: Record<string, unknown>
  startedAt: number
  endedAt: number | null
  updatedAt: number
}

export interface SyncAttemptRecord {
  seq?: number
  clientId: string
  kind: string
  ref: string
  packId: string
  sessionId: string
  input: string
  expected: string
  correct: number
  durationMs: number
  meta: Record<string, unknown>
  createdAt: number
}

export interface AuthUser {
  id: string
  githubId: string
  login: string
  name: string
  avatarUrl: string
  role: 'admin' | 'user'
  status: 'active' | 'pending'
}

export interface AuthMeResponse {
  authEnabled: boolean
  authenticated: boolean
  user: AuthUser | null
}

export interface InviteRecord {
  code: string
  maxUses: number
  usedCount: number
  note: string
  createdAt: number
  revokedAt: number
}

export interface SyncResponse {
  ok: boolean
  serverTs: number
  authRequired: boolean
  pushed: { vocab: number; sessions: number; attempts: number }
  pull: {
    vocab: VocabItem[]
    sessions: SyncSessionRecord[]
    attempts: SyncAttemptRecord[]
    packs: { id: string; mtime: number; summary: PackSummary }[]
    allPackIds: string[]
    hasMore: boolean
  }
  cursor: SyncCursor
}
