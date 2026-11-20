import type { LexEntry } from '../types'

export interface Token {
  text: string
  word: boolean
}

const WORD_RE = /[A-Za-z][A-Za-z'’\-]*/g

export function tokenize(sentence: string): Token[] {
  const tokens: Token[] = []
  let cursor = 0
  for (const match of sentence.matchAll(WORD_RE)) {
    const index = match.index ?? 0
    if (index > cursor) tokens.push({ text: sentence.slice(cursor, index), word: false })
    tokens.push({ text: match[0], word: true })
    cursor = index + match[0].length
  }
  if (cursor < sentence.length) tokens.push({ text: sentence.slice(cursor), word: false })
  return tokens
}

function normalize(raw: string): string {
  return raw.toLowerCase().replace(/[’‘]/g, "'").replace(/^-+|-+$/g, '')
}

export function lookup(
  raw: string,
  lexicon: Record<string, LexEntry>,
): { lemma: string; entry: LexEntry } | null {
  const word = normalize(raw)
  const candidates = [word]
  if (word.endsWith("'s")) candidates.push(word.slice(0, -2))
  if (word.endsWith("s'")) candidates.push(word.slice(0, -1))
  if (word.endsWith("n't")) candidates.push(word.replace(/n't$/, ''))
  candidates.push(
    word.replace(/ies$/, 'y'),
    word.replace(/es$/, ''),
    word.replace(/s$/, ''),
    word.replace(/ed$/, ''),
    word.replace(/ed$/, 'e'),
    word.replace(/ing$/, ''),
    word.replace(/ing$/, 'e'),
    word.replace(/([a-z])\1(ed|ing)$/, '$1'),
  )
  for (const candidate of candidates) {
    const entry = lexicon[candidate]
    if (entry) return { lemma: candidate, entry }
  }
  return null
}

export function resolveLemma(raw: string, lexicon: Record<string, LexEntry>): string {
  return lookup(raw, lexicon)?.lemma ?? normalize(raw)
}

export function splitHighlight(text: string, target: string): { text: string; hit: boolean }[] {
  const safe = target.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  if (!safe) return [{ text, hit: false }]
  const re = new RegExp(`\\b(${safe})\\b`, 'i')
  const match = re.exec(text)
  if (!match) return [{ text, hit: false }]
  const start = match.index
  const end = start + match[0].length
  const parts: { text: string; hit: boolean }[] = []
  if (start > 0) parts.push({ text: text.slice(0, start), hit: false })
  parts.push({ text: text.slice(start, end), hit: true })
  if (end < text.length) parts.push({ text: text.slice(end), hit: false })
  return parts
}
