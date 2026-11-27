import { idbGet, idbGetAll, idbPut, type LocalVocab } from './localDb'
import { ensureHydrated, queueOutbox, refreshLocalCounts, syncNow } from './sync'
import type {
  DictAnswerResult,
  DictItem,
  DictSession,
  DictSummary,
  PackDetail,
  PackSummary,
  SyncAttemptRecord,
  SyncSessionRecord,
} from './types'

export const ALL_PACKS_ID = '__all__'

type DictMode = 'word' | 'word_in_context' | 'sentence'
type DictSource = 'vocab' | 'pack' | 'auto'

interface Span {
  start: number
  end: number
  word: string
}

interface StoredDictItem {
  id: string
  packId: string
  type: DictMode
  audioText: string
  maskedText: string
  answers: string[]
  hint: DictItem['hint']
  source: string
  externalAudio?: string
}

interface StoredAnswer {
  input: string | string[]
  correct: boolean
  replays: number
}

interface SessionMeta {
  items: StoredDictItem[]
  voice: string
  answers: Record<string, StoredAnswer>
}

const WORD_RE = /[A-Za-z][A-Za-z'’-]*/g
const STOP = new Set(
  `a an the of to in on at for and or but is are was were be been being it its this that these those
  with by as from i you he she we they my your his her our their me him them us do does did have has had
  will would can could should may might must not no so if than then there here what which who when where
  how very too also just about into over after before more most some any all one two three
  can't don't doesn't didn't isn't aren't wasn't weren't won't wouldn't couldn't shouldn't
  it's he's she's that's there's i'm i've you're we're they're hasn't haven't`
    .trim()
    .split(/\s+/),
)

const MAX_BLANKS = 2
const DEFAULT_VOICE = 'en-GB-SoniaNeural'

// ── 判分归一化（与服务端 grading.py 一致） ──────────────────────────────────

function normalizeAnswer(value: string): string {
  return (value || '')
    .normalize('NFKC')
    .replace(/['’‘`´]/g, "'")
    .replace(/[-–—−‐]/g, ' ')
    .replace(/\u00a0/g, ' ')
    .replace(/[^\p{L}\p{N}_\s']/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase()
    .replace(/^'+|'+$/g, '')
}

function asList(value: string | string[] | null | undefined): string[] {
  if (value == null) return []
  return Array.isArray(value) ? value.map(String) : [String(value)]
}

function compareAnswers(expected: string[], given: string | string[]) {
  const got = asList(given)
  while (got.length < expected.length) got.push('')
  const parts = expected.map((exp, idx) => normalizeAnswer(exp) === normalizeAnswer(got[idx]))
  return {
    ok: parts.length > 0 && parts.every(Boolean),
    parts,
    expected,
    given: got.slice(0, expected.length),
  }
}

// ── 挖空与题目生成（与服务端 services/dictation.py 一致） ────────────────────

function wordSpans(sentence: string): Span[] {
  const out: Span[] = []
  if (!sentence) return out
  WORD_RE.lastIndex = 0
  let m = WORD_RE.exec(sentence)
  while (m) {
    out.push({ start: m.index, end: m.index + m[0].length, word: m[0] })
    m = WORD_RE.exec(sentence)
  }
  return out
}

function isLemmaMatch(word: string, lemma: string): boolean {
  const w = word.toLowerCase()
  const l = lemma.toLowerCase()
  if (w === l) return true
  if (!w.startsWith(l)) return false
  const suffix = w.slice(l.length)
  return ['s', 'es', 'ed', 'd', 'ing', 'ies'].includes(suffix)
}

function pickBlanks(sentence: string, focus: Set<string> | null = null, limit = 1): Span[] {
  const spans = wordSpans(sentence)
  if (!spans.length) return []
  const picked: Span[] = []
  const seen = new Set<string>()

  if (focus && focus.size > 0) {
    const focusArr = Array.from(focus)
    for (const s of spans) {
      const low = s.word.toLowerCase()
      if (focusArr.some((f) => isLemmaMatch(s.word, f)) && !seen.has(low)) {
        picked.push(s)
        seen.add(low)
        if (picked.length >= limit) break
      }
    }
  }

  if (!picked.length) {
    const ok = (s: Span) =>
      s.word.length >= 4 &&
      !STOP.has(s.word.toLowerCase()) &&
      !seen.has(s.word.toLowerCase()) &&
      !/\d/.test(s.word)

    let cands = spans.filter((s) => ok(s) && s.word[0] !== s.word[0].toUpperCase())
    if (!cands.length) cands = spans.filter(ok)
    cands.sort((a, b) => a.word.length - b.word.length || a.start - b.start)
    if (cands.length) picked.push(cands[cands.length - 1])
  }

  return picked.slice(0, MAX_BLANKS)
}

function maskSentence(sentence: string, spans: Span[]): string {
  let out = sentence
  const sorted = [...spans].sort((a, b) => b.start - a.start)
  for (const s of sorted) {
    out = `${out.slice(0, s.start)}{{${s.word}}}${out.slice(s.end)}`
  }
  return out
}

function stripPlaceholders(masked: string): string {
  return masked.replace(/\{\{[^}]*\}\}/g, '{{}}')
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function toPublicItem(
  item: StoredDictItem,
  buildTtsUrl: (text: string, voice: string) => string,
  voice = DEFAULT_VOICE,
): DictItem {
  const masked = stripPlaceholders(item.maskedText)
  const hint: DictItem['hint'] = { ...item.hint }
  if (hint.context) {
    hint.context = stripPlaceholders(hint.context)
  }
  return {
    id: item.id,
    packId: item.packId,
    type: item.type,
    audioText: item.audioText,
    audioUrl: item.externalAudio || buildTtsUrl(item.audioText, voice),
    audioCached: Boolean(item.externalAudio),
    text: masked,
    blankCount: item.answers.length,
    blankLengths: item.answers.map((a) => a.length),
    hint,
    source: item.source,
  }
}

function resolveVocabContext(
  vocab: LocalVocab,
  packId: string,
): { en: string; zh: string; packId: string } {
  const contexts = vocab.contexts ?? []
  if (!contexts.length) return { en: '', zh: '', packId: packId || '' }
  if (packId && packId !== ALL_PACKS_ID) {
    const hit = contexts.find((c) => c.packId === packId && (c.en || '').trim())
    if (hit) return { en: hit.en ?? '', zh: hit.zh ?? '', packId: hit.packId ?? packId }
  }
  const first = contexts.find((c) => (c.en || '').trim()) ?? contexts[0]
  return {
    en: first.en ?? '',
    zh: first.zh ?? '',
    packId: first.packId || (packId !== ALL_PACKS_ID ? packId : ''),
  }
}

function findSentenceInPack(pack: PackDetail | null, word: string): { en: string; zh: string } {
  if (!pack || !word) return { en: '', zh: '' }
  const re = new RegExp(`(?<![A-Za-z])${escapeRegExp(word)}(?![A-Za-z])`, 'i')
  for (const para of pack.paragraphs ?? []) {
    for (const s of para.sentences ?? []) {
      if (re.test(s.en)) return { en: s.en, zh: s.zh }
    }
  }
  return { en: '', zh: '' }
}

function makeVocabWordItem(
  vocab: LocalVocab,
  mode: 'word' | 'word_in_context',
  packId: string,
  packForFallback: PackDetail | null,
): StoredDictItem {
  const rawWord = (vocab.word || vocab.lemma).trim()
  const lemma = (vocab.lemma || rawWord).trim().toLowerCase()
  let ctx = resolveVocabContext(vocab, packId)
  if (!ctx.en && packForFallback) {
    const found = findSentenceInPack(packForFallback, rawWord)
    if (found.en) ctx = { ...found, packId: packForFallback.id }
  }

  const spans = ctx.en ? pickBlanks(ctx.en, new Set([lemma, rawWord.toLowerCase()]), 1) : []
  const masked = spans.length ? maskSentence(ctx.en, spans) : ''
  const answer = mode === 'word_in_context' && spans.length ? spans[0].word : rawWord
  const itemPackId = ctx.packId || (packId === ALL_PACKS_ID ? '' : packId)

  return {
    id: `${itemPackId || 'all'}:w:${lemma}`,
    packId: itemPackId,
    type: mode,
    audioText: answer,
    maskedText: mode === 'word_in_context' ? masked || `{{${answer}}}` : '',
    answers: [answer],
    hint: {
      gloss: vocab.gloss,
      pos: vocab.pos,
      phonetic: vocab.phonetic,
      context: masked,
      contextZh: ctx.zh,
    },
    source: 'vocab',
  }
}

function buildLexiconItems(
  pack: PackDetail,
  mode: 'word' | 'word_in_context',
  limit: number,
  seenLemmas: Set<string>,
): StoredDictItem[] {
  const sentences = (pack.paragraphs ?? []).flatMap((p) => p.sentences ?? [])
  const candidates: { idx: number; word: string; gloss: string; pos: string; phonetic: string; en: string; zh: string }[] = []

  for (const [word, entry] of Object.entries(pack.lexicon ?? {})) {
    const low = word.trim().toLowerCase()
    if (!low || low.length < 4 || STOP.has(low) || seenLemmas.has(low)) continue
    if (!(entry?.gloss ?? '').trim()) continue
    const re = new RegExp(`(?<![A-Za-z])${escapeRegExp(word)}(?![A-Za-z])`, 'i')
    let matchedIdx = sentences.length
    let en = ''
    let zh = ''
    for (let i = 0; i < sentences.length; i += 1) {
      if (re.test(sentences[i].en)) {
        matchedIdx = i
        en = sentences[i].en
        zh = sentences[i].zh
        break
      }
    }
    candidates.push({
      idx: matchedIdx,
      word,
      gloss: entry.gloss ?? '',
      pos: entry.pos ?? '',
      phonetic: entry.phonetic ?? '',
      en,
      zh,
    })
  }

  candidates.sort((a, b) => a.idx - b.idx || a.word.toLowerCase().localeCompare(b.word.toLowerCase()))
  const out: StoredDictItem[] = []
  for (const c of candidates) {
    const spans = c.en ? pickBlanks(c.en, new Set([c.word.toLowerCase()]), 1) : []
    const masked = spans.length ? maskSentence(c.en, spans) : ''
    const answer = spans.length ? spans[0].word : c.word
    seenLemmas.add(c.word.toLowerCase())
    out.push({
      id: `${pack.id}:w:${c.word.toLowerCase()}`,
      packId: pack.id,
      type: mode,
      audioText: answer,
      maskedText: mode === 'word_in_context' ? masked || `{{${answer}}}` : '',
      answers: [answer],
      hint: {
        gloss: c.gloss,
        pos: c.pos,
        phonetic: c.phonetic,
        context: masked,
        contextZh: c.zh,
      },
      source: 'pack',
    })
    if (out.length >= limit) break
  }
  return out
}

function buildSentenceItems(
  pack: PackDetail,
  focus: Set<string>,
  limit: number,
): StoredDictItem[] {
  const out: StoredDictItem[] = []
  const sentences = (pack.paragraphs ?? []).flatMap((p) => p.sentences ?? [])

  // 优先包含生词本词汇的句子，其次按正文顺序
  const ordered = focus.size
    ? [
        ...sentences.filter((s) =>
          wordSpans(s.en).some((sp) => Array.from(focus).some((f) => isLemmaMatch(sp.word, f))),
        ),
        ...sentences.filter(
          (s) =>
            !wordSpans(s.en).some((sp) => Array.from(focus).some((f) => isLemmaMatch(sp.word, f))),
        ),
      ]
    : sentences

  for (const s of ordered) {
    const blanks = wordSpans(s.en).length >= 14 ? 2 : 1
    const spans = pickBlanks(s.en, focus, blanks)
    if (!spans.length) continue
    out.push({
      id: `${pack.id}:s:${s.id}`,
      packId: pack.id,
      type: 'sentence',
      audioText: s.en.replace(/\s+/g, ' ').trim(),
      maskedText: maskSentence(s.en, spans),
      answers: spans.map((sp) => sp.word),
      hint: { contextZh: s.zh },
      source: 'pack',
    })
    if (out.length >= limit) break
  }
  return out
}

function buildDeckItems(pack: PackDetail, mode: DictMode, limit: number): StoredDictItem[] {
  const out: StoredDictItem[] = []
  const rows = pack.items ?? []
  for (let i = 0; i < rows.length; i += 1) {
    const row = rows[i]
    const word = (row.answers?.[0] || row.word || '').trim()
    const sentence = (row.sentence || '').trim()
    if (!word) continue

    if (mode === 'sentence' && sentence) {
      const spans = pickBlanks(sentence, new Set([word.toLowerCase()]), Math.max(1, row.answers?.length || 1))
      if (spans.length) {
        out.push({
          id: `${pack.id}:d:${i}`,
          packId: pack.id,
          type: 'sentence',
          audioText: sentence.replace(/\s+/g, ' ').trim(),
          maskedText: maskSentence(sentence, spans),
          answers: spans.map((sp) => sp.word),
          hint: { gloss: row.meaning || '', contextZh: row.translation || '' },
          source: 'deck',
          externalAudio: row.audio || '',
        })
        if (out.length >= limit) break
        continue
      }
    }

    const ctxSpans = sentence ? pickBlanks(sentence, new Set([word.toLowerCase()]), 1) : []
    const ctxMasked = ctxSpans.length ? maskSentence(sentence, ctxSpans) : ''
    out.push({
      id: `${pack.id}:d:${i}`,
      packId: pack.id,
      type: mode === 'sentence' ? 'word' : mode,
      audioText: word,
      maskedText: mode === 'word_in_context' ? ctxMasked || `{{${word}}}` : '',
      answers: [word],
      hint: {
        gloss: row.meaning || '',
        pos: row.pos || '',
        phonetic: row.phonetic || '',
        context: ctxMasked,
        contextZh: row.translation || '',
        image: row.image || '',
      },
      source: 'deck',
    })
    if (out.length >= limit) break
  }
  return out
}

// ── 会话生命周期（本地 IndexedDB 读写 + 自动入队同步） ───────────────────────

function nowSec(): number {
  return Math.floor(Date.now() / 1000)
}

function newId(prefix: string): string {
  const rand =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID().replace(/-/g, '').slice(0, 12)
      : Math.random().toString(36).slice(2, 14)
  return `${prefix}_${rand}`
}

const activeSessions = new Map<string, SyncSessionRecord>()

export async function localDictationStart(
  payload: {
    packId: string
    mode: DictMode
    source?: DictSource
    limit?: number
  },
  helpers: {
    fetchPackDetail: (id: string) => Promise<PackDetail>
    fetchPacksList: () => Promise<{ items: PackSummary[] }>
    buildTtsUrl: (text: string, voice: string) => string
  },
): Promise<DictSession> {
  await ensureHydrated()
  const isAll = !payload.packId || payload.packId === ALL_PACKS_ID
  const mode: DictMode = payload.mode ?? 'word'
  const source: DictSource = payload.source ?? 'auto'
  const limit = Math.max(1, Math.min(100, payload.limit ?? 20))

  const allVocab = (await idbGetAll<LocalVocab>('vocab'))
    .filter((v) => !v.deletedAt && v.state !== 'suspended')
    .sort((a, b) => a.dueAt - b.dueAt || a.id - b.id)

  const items: StoredDictItem[] = []
  const seenLemmas = new Set<string>()

  if (isAll) {
    if (mode === 'word' || mode === 'word_in_context') {
      if (source === 'vocab' || source === 'auto') {
        const pool =
          mode === 'word_in_context'
            ? [
                ...allVocab.filter((v) => v.contexts?.some((c) => (c.en || '').trim())),
                ...allVocab.filter((v) => !v.contexts?.some((c) => (c.en || '').trim())),
              ]
            : allVocab
        for (const v of pool) {
          seenLemmas.add(v.lemma.toLowerCase())
          items.push(makeVocabWordItem(v, mode, ALL_PACKS_ID, null))
          if (items.length >= limit) break
        }
      }
      if (!items.length && (source === 'auto' || source === 'pack')) {
        const { items: summaries } = await helpers.fetchPacksList()
        for (const s of summaries) {
          if (items.length >= limit) break
          try {
            const detail = await helpers.fetchPackDetail(s.id)
            const more =
              detail.kind === 'deck'
                ? buildDeckItems(detail, mode, limit - items.length)
                : buildLexiconItems(detail, mode, limit - items.length, seenLemmas)
            items.push(...more)
          } catch {
            /* skip unavailable pack */
          }
        }
      }
    } else {
      const focus = new Set(allVocab.map((v) => v.lemma.toLowerCase()))
      const { items: summaries } = await helpers.fetchPacksList()
      for (const s of summaries) {
        if (items.length >= limit) break
        try {
          const detail = await helpers.fetchPackDetail(s.id)
          const more =
            detail.kind === 'deck'
              ? buildDeckItems(detail, 'sentence', limit - items.length)
              : buildSentenceItems(detail, focus, limit - items.length)
          items.push(...more)
        } catch {
          /* skip unavailable pack */
        }
      }
    }
  } else {
    const packVocab = allVocab.filter((v) =>
      (v.contexts ?? []).some((c) => c.packId === payload.packId),
    )
    let detail: PackDetail | null = null
    const needPack =
      mode === 'sentence' ||
      !packVocab.length ||
      (mode === 'word_in_context' && packVocab.some((v) => !v.contexts?.some((c) => c.packId === payload.packId && c.en)))

    if (needPack) {
      try {
        detail = await helpers.fetchPackDetail(payload.packId)
      } catch {
        detail = null
      }
    }

    if (detail?.kind === 'deck') {
      items.push(...buildDeckItems(detail, mode, limit))
    } else if (mode === 'word' || mode === 'word_in_context') {
      if (source === 'vocab' || source === 'auto') {
        for (const v of packVocab) {
          seenLemmas.add(v.lemma.toLowerCase())
          items.push(makeVocabWordItem(v, mode, payload.packId, detail))
          if (items.length >= limit) break
        }
      }
      if (!items.length && (source === 'auto' || source === 'pack') && detail) {
        items.push(...buildLexiconItems(detail, mode, limit, seenLemmas))
      }
    } else if (detail) {
      const focus = new Set(packVocab.map((v) => v.lemma.toLowerCase()))
      items.push(...buildSentenceItems(detail, focus, limit))
    }
  }

  if (!items.length) {
    const msg =
      mode === 'sentence'
        ? '当前篇目没有可用于整句听写的句子，请切换其他篇目或选择「全部篇目」。'
        : isAll
          ? '生词本里还没有词，且当前篇目暂无内置词表；请先去精读页面划词收藏几个生词。'
          : '这篇还没有收藏生词且暂无内置词表；请先在精读页划词收藏，或将篇目切换为「全部篇目」。'
    throw new Error(msg)
  }

  const sid = newId('ds')
  const now = nowSec()
  const meta: SessionMeta = {
    items,
    voice: DEFAULT_VOICE,
    answers: {},
  }
  const sessionRecord: SyncSessionRecord = {
    id: sid,
    kind: 'dictation',
    packId: isAll ? '' : payload.packId,
    mode,
    planned: items.length,
    answered: 0,
    correct: 0,
    meta: meta as unknown as Record<string, unknown>,
    startedAt: now,
    endedAt: null,
    updatedAt: now,
  }

  activeSessions.set(sid, sessionRecord)
  await idbPut('sessions', sessionRecord)
  await queueOutbox('session', sid, sessionRecord)

  return {
    sessionId: sid,
    packId: isAll ? ALL_PACKS_ID : payload.packId,
    mode,
    voice: DEFAULT_VOICE,
    startedAt: now,
    items: items.map((it) => toPublicItem(it, helpers.buildTtsUrl, DEFAULT_VOICE)),
  }
}

async function loadSession(sessionId: string): Promise<SyncSessionRecord> {
  const mem = activeSessions.get(sessionId)
  if (mem) return mem
  const stored = await idbGet<SyncSessionRecord>('sessions', sessionId)
  if (!stored || stored.kind !== 'dictation') {
    throw new Error('听写会话不存在，请重新开始')
  }
  activeSessions.set(sessionId, stored)
  return stored
}

export async function localDictationAnswer(
  sessionId: string,
  payload: { itemId: string; input: string | string[]; replays?: number; durationMs?: number },
): Promise<DictAnswerResult> {
  const session = await loadSession(sessionId)
  if (session.endedAt) throw new Error('本次听写已结束')

  const meta = session.meta as unknown as SessionMeta
  const item = (meta.items ?? []).find((it) => it.id === payload.itemId)
  if (!item) throw new Error('题目不在本次听写中')

  const expected = item.answers ?? []
  const graded = compareAnswers(expected, payload.input)
  const kind = item.type === 'sentence' ? 'dictation_sentence' : 'dictation_word'
  const ref = kind === 'dictation_word' && expected[0] ? expected[0].toLowerCase() : item.id

  const answers = (meta.answers ??= {})
  const prev = answers[payload.itemId]
  answers[payload.itemId] = {
    input: payload.input,
    correct: graded.ok,
    replays: payload.replays ?? 0,
  }

  const now = nowSec()
  const delta = (graded.ok ? 1 : 0) - (prev?.correct ? 1 : 0)
  if (!prev) {
    session.answered += 1
    if (graded.ok) session.correct += 1
  } else {
    session.correct += delta
  }
  session.updatedAt = now

  const attempt: SyncAttemptRecord = {
    clientId: newId('att'),
    kind,
    ref,
    packId: item.packId || session.packId || '',
    sessionId,
    input: Array.isArray(payload.input) ? JSON.stringify(payload.input) : String(payload.input ?? ''),
    expected: expected.join('|'),
    correct: graded.ok ? 1 : 0,
    durationMs: payload.durationMs ?? 0,
    meta: { itemId: payload.itemId, answers: expected, replays: payload.replays ?? 0 },
    createdAt: now,
  }

  await idbPut('attempts', attempt)
  await idbPut('sessions', session)
  await queueOutbox('attempt', attempt.clientId, attempt)
  await queueOutbox('session', sessionId, session)
  await refreshLocalCounts()

  return {
    itemId: payload.itemId,
    correct: graded.ok,
    parts: graded.parts,
    expected: graded.expected,
    firstTime: !prev,
  }
}

export async function localDictationFinish(sessionId: string): Promise<DictSummary> {
  const session = await loadSession(sessionId)
  const meta = session.meta as unknown as SessionMeta
  const now = nowSec()
  const ended = session.endedAt ?? now
  if (!session.endedAt) {
    session.endedAt = ended
    session.updatedAt = now
    await idbPut('sessions', session)
    await queueOutbox('session', sessionId, session)
  }
  activeSessions.delete(sessionId)

  const answers = meta.answers ?? {}
  const items = meta.items ?? []
  const wrong: DictSummary['wrong'] = []
  const skipped: DictSummary['skipped'] = []

  for (const it of items) {
    const got = answers[it.id]
    if (!got) {
      skipped.push({ itemId: it.id, answers: it.answers, text: it.maskedText })
    } else if (!got.correct) {
      wrong.push({ itemId: it.id, answers: it.answers, input: got.input, text: it.maskedText })
    }
  }

  const total = items.length
  const answered = Object.keys(answers).length
  const correct = Object.values(answers).filter((a) => a.correct).length

  void syncNow()

  return {
    sessionId,
    packId: session.packId,
    mode: session.mode,
    total,
    answered,
    correct,
    accuracy: answered ? Number((correct / answered).toFixed(4)) : 0,
    durationSec: Math.max(0, ended - session.startedAt),
    wrong,
    skipped,
  }
}
