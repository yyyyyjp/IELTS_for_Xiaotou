import { ref } from 'vue'
import { idbGet, idbPut, type CompactDictTuple } from './localDb'
import type { DictLookupResult, DictLookupToken, LexEntry } from './types'

export const coreDictStatus = ref<'idle' | 'loading' | 'ready' | 'unavailable'>('idle')
export const coreDictCount = ref(0)

const exactMap = new Map<string, CompactDictTuple>()
const lowerMap = new Map<string, CompactDictTuple>()
const swMap = new Map<string, CompactDictTuple>()
const loadedShards = new Set<string>()
const shardLoading = new Map<string, Promise<boolean>>()

const TAG_ORDER = ['ielts', 'toefl', 'gre', 'cet6', 'cet4', 'ky', 'gk', 'zk']
const POS_LINE_RE = /^([a-z]{1,6}\.(?:\s*\/\s*[a-z]{1,6}\.)*)\s+(.+)$/i
const LEADING_DET_RE = /^(?:the|a|an|to|this|that|these|those)\s+/i
const WORD_TOKEN_RE = /[A-Za-z][A-Za-z'-]*/g

const STOPWORDS = new Set([
  'a', 'an', 'the', 'of', 'to', 'in', 'on', 'at', 'for', 'by', 'with', 'from',
  'as', 'is', 'am', 'are', 'was', 'were', 'be', 'been', 'being', 'and', 'or',
  'but', 'if', 'it', 'its', 'this', 'that', 'these', 'those', 'he', 'she',
  'they', 'we', 'you', 'i', 'me', 'him', 'her', 'us', 'them', 'my', 'your',
  'his', 'their', 'our', 'not', 'no', 'so', 'than', 'then', 'into', 'onto',
])

const FORM_LABELS: Record<string, string> = {
  p: '过去式',
  d: '过去分词',
  i: '现在分词',
  '3': '第三人称单数',
  r: '比较级',
  t: '最高级',
  s: '复数',
}

const UK_TO_US: [string, string][] = [
  ['isation', 'ization'],
  ['isations', 'izations'],
  ['ising', 'izing'],
  ['ised', 'ized'],
  ['ises', 'izes'],
  ['ise', 'ize'],
  ['our', 'or'],
  ['ours', 'ors'],
  ['oured', 'ored'],
  ['ouring', 'oring'],
  ['re', 'er'],
  ['elling', 'eling'],
  ['elled', 'eled'],
  ['ence', 'ense'],
  ['logue', 'log'],
]

function stripWord(w: string): string {
  return w.replace(/[^A-Za-z0-9]/g, '').toLowerCase()
}

function indexEntries(entries: CompactDictTuple[]): void {
  exactMap.clear()
  lowerMap.clear()
  swMap.clear()
  for (const tup of entries) {
    const w = tup[0]
    exactMap.set(w, tup)
    const low = w.toLowerCase()
    if (!lowerMap.has(low)) lowerMap.set(low, tup)
    const sw = stripWord(w)
    if (sw && !swMap.has(sw)) swMap.set(sw, tup)
  }
  coreDictCount.value = entries.length
  coreDictStatus.value = entries.length > 0 ? 'ready' : 'unavailable'
}

function mergeShardEntries(entries: CompactDictTuple[]): void {
  for (const tup of entries) {
    const w = tup[0]
    if (!exactMap.has(w)) exactMap.set(w, tup)
    const low = w.toLowerCase()
    if (!lowerMap.has(low)) lowerMap.set(low, tup)
    const sw = stripWord(w)
    if (sw && !swMap.has(sw)) swMap.set(sw, tup)
  }
}

export function shardKeyFor(word: string): string {
  const ch = (word.trim()[0] ?? '').toLowerCase()
  return ch >= 'a' && ch <= 'z' ? ch : 'other'
}

export async function ensureDictShard(
  wordOrLetter: string,
  fetchShard: (letter: string) => Promise<{ entries: CompactDictTuple[] }>,
): Promise<boolean> {
  const letter = shardKeyFor(wordOrLetter)
  if (loadedShards.has(letter)) return true
  const inflight = shardLoading.get(letter)
  if (inflight) return inflight

  const p = (async () => {
    const blobKey = `shard_${letter}`
    const cached = await idbGet<{ key: string; entries: CompactDictTuple[] }>('dict_blob', blobKey)
    if (cached?.entries?.length) {
      mergeShardEntries(cached.entries)
      loadedShards.add(letter)
      return true
    }
    try {
      const data = await fetchShard(letter)
      if (data?.entries?.length) {
        await idbPut('dict_blob', { key: blobKey, entries: data.entries })
        mergeShardEntries(data.entries)
        loadedShards.add(letter)
        return true
      }
    } catch {
      /* ignore */
    }
    return false
  })().finally(() => {
    shardLoading.delete(letter)
  })

  shardLoading.set(letter, p)
  return p
}

interface CoreBundlePayload {
  version: number
  count: number
  entries: CompactDictTuple[]
}

let loadingPromise: Promise<void> | null = null

export async function ensureCoreDict(
  fetchBundle: () => Promise<CoreBundlePayload>,
  forceRefresh = false,
): Promise<void> {
  if (!forceRefresh && coreDictStatus.value === 'ready') return
  if (loadingPromise && !forceRefresh) return loadingPromise

  loadingPromise = (async () => {
    coreDictStatus.value = 'loading'
    if (!forceRefresh) {
      const cached = await idbGet<{ key: string; entries: CompactDictTuple[] }>(
        'dict_blob',
        'core_v1',
      )
      if (cached?.entries?.length) {
        indexEntries(cached.entries)
        return
      }
    }

    try {
      const bundle = await fetchBundle()
      if (bundle?.entries?.length) {
        await idbPut('dict_blob', { key: 'core_v1', entries: bundle.entries })
        indexEntries(bundle.entries)
        return
      }
      coreDictStatus.value = 'unavailable'
    } catch {
      coreDictStatus.value = 'unavailable'
    }
  })().finally(() => {
    loadingPromise = null
  })

  return loadingPromise
}

function morphCandidates(word: string): string[] {
  const w = word.toLowerCase()
  const cands: string[] = []
  const add = (v: string) => {
    const s = v.replace(/^[-']+|[-']+$/g, '')
    if (s && s !== w && !cands.includes(s)) cands.push(s)
  }

  if (w.endsWith("'s")) add(w.slice(0, -2))
  if (w.endsWith("s'")) add(w.slice(0, -1))
  if (w.endsWith("n't")) add(w.slice(0, -3))

  if (w.endsWith('ies') && w.length > 4) add(w.slice(0, -3) + 'y')
  if (w.endsWith('ied') && w.length > 4) add(w.slice(0, -3) + 'y')
  if (w.endsWith('ier') && w.length > 4) add(w.slice(0, -3) + 'y')
  if (w.endsWith('iest') && w.length > 5) add(w.slice(0, -4) + 'y')
  if (w.endsWith('ves') && w.length > 4) {
    add(w.slice(0, -3) + 'f')
    add(w.slice(0, -3) + 'fe')
  }
  if (w.endsWith('es') && w.length > 3) add(w.slice(0, -2))
  if (w.endsWith('s') && w.length > 2 && !w.endsWith('ss')) add(w.slice(0, -1))
  if (w.endsWith('ed') && w.length > 3) {
    add(w.slice(0, -2))
    add(w.slice(0, -1))
    if (/([a-z])\1ed$/.test(w)) add(w.slice(0, -3))
  }
  if (w.endsWith('ing') && w.length > 4) {
    add(w.slice(0, -3))
    add(w.slice(0, -3) + 'e')
    if (/([a-z])\1ing$/.test(w)) add(w.slice(0, -4))
  }
  if (w.endsWith('er') && w.length > 4) {
    add(w.slice(0, -2))
    add(w.slice(0, -1))
  }
  if (w.endsWith('est') && w.length > 5) {
    add(w.slice(0, -3))
    add(w.slice(0, -2))
  }

  const base = [w, ...cands]
  for (const item of base) {
    for (const [uk, us] of UK_TO_US) {
      if (item.endsWith(uk) && item.length > uk.length + 2) {
        add(item.slice(0, -uk.length) + us)
      }
    }
  }
  return cands
}

function parseExchange(raw: string): Record<string, string> {
  const out: Record<string, string> = {}
  if (!raw) return out
  for (const part of raw.split('/')) {
    const idx = part.indexOf(':')
    if (idx > 0) {
      out[part.slice(0, idx)] = part.slice(idx + 1)
    }
  }
  return out
}

function describeForm(lemma: string, code: string): string {
  if (!lemma || !code) return ''
  const labels: string[] = []
  for (const ch of code) {
    const lbl = FORM_LABELS[ch]
    if (lbl && !labels.includes(lbl)) labels.push(lbl)
  }
  return labels.length ? `${lemma} 的${labels.join('/')}` : `原型：${lemma}`
}

function extractPos(trans: string): string {
  const poses: string[] = []
  for (const line of trans.split('\n')) {
    const m = POS_LINE_RE.exec(line.trim())
    if (m && !poses.includes(m[1])) poses.push(m[1])
  }
  return poses.slice(0, 3).join(' / ')
}

function parseTags(raw: string): string[] {
  if (!raw) return []
  const set = new Set(raw.toLowerCase().split(/\s+/).filter(Boolean))
  return TAG_ORDER.filter((t) => set.has(t))
}

function findTuple(text: string): {
  tup: CompactDictTuple
  baseTup: CompactDictTuple | null
  formNote: string
} | null {
  let tup = exactMap.get(text) ?? lowerMap.get(text.toLowerCase()) ?? swMap.get(stripWord(text))

  if (!tup && text.includes(' ')) {
    const stripped = text.replace(LEADING_DET_RE, '').trim()
    if (stripped && stripped !== text) {
      tup =
        exactMap.get(stripped) ??
        lowerMap.get(stripped.toLowerCase()) ??
        swMap.get(stripWord(stripped))
    }
  }

  if (!tup && !text.includes(' ')) {
    for (const cand of morphCandidates(text)) {
      const hit = exactMap.get(cand) ?? lowerMap.get(cand)
      if (hit) {
        tup = hit
        break
      }
    }
  }

  if (!tup) return null

  const ex = parseExchange(tup[5])
  let baseTup: CompactDictTuple | null = null
  let formNote = ''
  const baseName = ex['0']
  if (baseName && baseName.toLowerCase() !== tup[0].toLowerCase()) {
    baseTup = exactMap.get(baseName) ?? lowerMap.get(baseName.toLowerCase()) ?? null
    formNote = describeForm(baseName, ex['1'] ?? '')
  }

  return { tup, baseTup, formNote }
}

function tupleToInfo(
  tup: CompactDictTuple,
  baseTup: CompactDictTuple | null,
  formNote: string,
) {
  const word = tup[0]
  const lemma = (baseTup ? baseTup[0] : word).toLowerCase()
  const trans = tup[2] || (baseTup ? baseTup[2] : '')
  const baseTrans = baseTup ? baseTup[2] : ''
  const effectiveTrans =
    baseTup && baseTrans && trans && trans.length < 20 && trans.toLowerCase().includes(lemma)
      ? baseTrans
      : trans || baseTrans

  const phonetic = tup[1] || (baseTup ? baseTup[1] : '')
  const pos = extractPos(effectiveTrans)
  const tags = parseTags(tup[3] || (baseTup ? baseTup[3] : ''))
  const flags = tup[4] || (baseTup ? baseTup[4] : 0)
  const collins = flags & 7
  const oxford = Boolean(flags & 8)

  return {
    word,
    lemma,
    phonetic,
    pos,
    gloss: effectiveTrans,
    tags,
    collins,
    oxford,
    formNote,
  }
}

export function lookupLocalCoreDict(
  cleanedQuery: string,
  packLexicon?: Record<string, LexEntry> | null,
  findSavedId?: (lemma: string, word: string) => number | null,
): DictLookupResult | null {
  if (!cleanedQuery) return null

  // 1. 检查当前文章包语境词表
  let packHit: { lemma: string; entry: LexEntry } | null = null
  if (packLexicon) {
    const low = cleanedQuery.toLowerCase()
    const cands = [cleanedQuery, low, ...(low.includes(' ') ? [] : morphCandidates(low))]
    for (const c of cands) {
      if (packLexicon[c]) {
        packHit = { lemma: c, entry: packLexicon[c] }
        break
      }
    }
  }

  // 如果内存里既没有核心词库也没有任何已加载分片，且文章词表没命中，交给后端极速查询
  const hasLocalIndex = exactMap.size > 0
  if (!hasLocalIndex && !packHit) {
    return null
  }

  let ecInfo: ReturnType<typeof tupleToInfo> | null = null
  if (hasLocalIndex) {
    const found = findTuple(cleanedQuery) ?? (packHit ? findTuple(packHit.lemma) : null)
    if (found) {
      ecInfo = tupleToInfo(found.tup, found.baseTup, found.formNote)
    }
  }

  if (packHit) {
    const lemma =
      packHit.lemma.toLowerCase() === cleanedQuery.toLowerCase()
        ? packHit.lemma.toLowerCase()
        : (ecInfo?.lemma ?? packHit.lemma.toLowerCase())
    const gloss = (packHit.entry.gloss ?? '').trim()
    const dictGloss = ecInfo && ecInfo.gloss !== gloss ? ecInfo.gloss : ''
    const vocabId = findSavedId ? findSavedId(lemma, cleanedQuery) : null
    return {
      query: cleanedQuery,
      found: true,
      source: 'pack',
      word: cleanedQuery,
      lemma,
      phonetic: packHit.entry.phonetic || ecInfo?.phonetic || '',
      pos: packHit.entry.pos || ecInfo?.pos || '',
      gloss: gloss || ecInfo?.gloss || '',
      dictGloss,
      definition: '',
      tags: ecInfo?.tags ?? [],
      collins: ecInfo?.collins ?? 0,
      oxford: ecInfo?.oxford ?? false,
      formNote: ecInfo?.formNote ?? '',
      tokens: [],
      saved: vocabId !== null,
      vocabId,
      dictReady: true,
    }
  }

  if (ecInfo && ecInfo.gloss) {
    const vocabId = findSavedId ? findSavedId(ecInfo.lemma, cleanedQuery) : null
    return {
      query: cleanedQuery,
      found: true,
      source: 'ecdict',
      word: cleanedQuery,
      lemma: ecInfo.lemma,
      phonetic: ecInfo.phonetic,
      pos: ecInfo.pos,
      gloss: ecInfo.gloss,
      dictGloss: '',
      definition: '',
      tags: ecInfo.tags,
      collins: ecInfo.collins,
      oxford: ecInfo.oxford,
      formNote: ecInfo.formNote,
      tokens: [],
      saved: vocabId !== null,
      vocabId,
      dictReady: true,
    }
  }

  // 多词短语本地拆词兜底（只要 66k 核心词库已就绪，本地即可 0ms 拆词返回）
  if (coreDictStatus.value === 'ready' && cleanedQuery.includes(' ')) {
    const rawWords = cleanedQuery.match(WORD_TOKEN_RE) ?? []
    if (rawWords.length >= 2 && rawWords.length <= 8) {
      const seen = new Set<string>()
      const tokens: DictLookupToken[] = []
      for (const raw of rawWords) {
        const low = raw.toLowerCase()
        if (STOPWORDS.has(low) || seen.has(low) || low.length < 2) continue
        seen.add(low)
        const hit = findTuple(raw)
        if (!hit) continue
        const info = tupleToInfo(hit.tup, hit.baseTup, hit.formNote)
        if (!info.gloss) continue
        tokens.push({
          word: raw,
          lemma: info.lemma,
          phonetic: info.phonetic,
          pos: info.pos,
          gloss: info.gloss.split('\n')[0],
          formNote: info.formNote,
        })
        if (tokens.length >= 6) break
      }
      if (tokens.length) {
        const lemma = cleanedQuery.toLowerCase()
        const vocabId = findSavedId ? findSavedId(lemma, cleanedQuery) : null
        return {
          query: cleanedQuery,
          found: true,
          source: 'tokens',
          word: cleanedQuery,
          lemma,
          phonetic: '',
          pos: '',
          gloss: '',
          dictGloss: '',
          definition: '',
          tags: [],
          collins: 0,
          oxford: false,
          formNote: '',
          tokens,
          saved: vocabId !== null,
          vocabId,
          dictReady: true,
        }
      }
    }
  }

  return null
}
