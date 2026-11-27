/**
 * Cloudflare D1 轻量单词/短语查词模块（响应体仅 ~250 B，首查 <0.3s）。
 * 在浏览器 1.96 MB 离线核心词库尚未下载完之前提供即时查词，避免首查等待大文件。
 */

interface DictRow {
  word_lower: string
  word: string
  phonetic: string
  trans: string
  tag: string
  flags: number
  exchange: string
}

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

function cleanQuery(raw: string): string {
  return raw
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/\s+/g, ' ')
    .replace(/^[^A-Za-z0-9]+|[^A-Za-z0-9]+$/g, '')
    .trim()
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
    if (idx > 0) out[part.slice(0, idx)] = part.slice(idx + 1)
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

async function fetchDictRows(db: D1Database, keys: string[]): Promise<Map<string, DictRow>> {
  const uniq = Array.from(new Set(keys.map((k) => k.toLowerCase()).filter(Boolean))).slice(0, 24)
  const map = new Map<string, DictRow>()
  if (!uniq.length) return map
  const placeholders = uniq.map(() => '?').join(',')
  const rows = (
    await db
      .prepare(
        `SELECT word_lower, word, phonetic, trans, tag, flags, exchange FROM dict WHERE word_lower IN (${placeholders})`,
      )
      .bind(...uniq)
      .all<DictRow>()
  ).results
  for (const r of rows) {
    map.set(r.word_lower, r)
  }
  return map
}

function rowToInfo(row: DictRow, baseRow: DictRow | null, formNote: string) {
  const word = row.word
  const lemma = (baseRow ? baseRow.word : word).toLowerCase()
  const trans = row.trans || (baseRow ? baseRow.trans : '')
  const baseTrans = baseRow ? baseRow.trans : ''
  const effectiveTrans =
    baseRow && baseTrans && trans && trans.length < 20 && trans.toLowerCase().includes(lemma)
      ? baseTrans
      : trans || baseTrans

  const phonetic = row.phonetic || (baseRow ? baseRow.phonetic : '')
  const flags = Number(row.flags || (baseRow ? baseRow.flags : 0))
  return {
    word,
    lemma,
    phonetic,
    pos: extractPos(effectiveTrans),
    gloss: effectiveTrans,
    tags: parseTags(row.tag || (baseRow ? baseRow.tag : '')),
    collins: flags & 7,
    oxford: Boolean(flags & 8),
    formNote,
  }
}

export async function lookupInD1(db: D1Database, rawQuery: string) {
  const cleaned = cleanQuery(rawQuery)
  const empty = {
    query: cleaned,
    found: false,
    source: 'none' as const,
    word: cleaned,
    lemma: cleaned.toLowerCase(),
    phonetic: '',
    pos: '',
    gloss: '',
    dictGloss: '',
    definition: '',
    tags: [] as string[],
    collins: 0,
    oxford: false,
    formNote: '',
    tokens: [] as {
      word: string
      lemma: string
      phonetic: string
      pos: string
      gloss: string
      formNote: string
    }[],
    saved: false,
    vocabId: null as number | null,
    dictReady: true,
  }
  if (!cleaned) return empty

  const low = cleaned.toLowerCase()
  const cands = [low]
  if (cleaned.includes(' ')) {
    const stripped = cleaned.replace(LEADING_DET_RE, '').trim().toLowerCase()
    if (stripped && stripped !== low) cands.push(stripped)
  } else {
    cands.push(...morphCandidates(low))
  }

  let rows: Map<string, DictRow>
  try {
    rows = await fetchDictRows(db, cands)
  } catch {
    return { ...empty, dictReady: false }
  }

  let hit: DictRow | null = null
  for (const c of cands) {
    const r = rows.get(c)
    if (r) {
      hit = r
      break
    }
  }

  if (hit) {
    const ex = parseExchange(hit.exchange)
    let baseRow: DictRow | null = null
    let formNote = ''
    const baseName = ex['0']
    if (baseName && baseName.toLowerCase() !== hit.word.toLowerCase()) {
      baseRow = rows.get(baseName.toLowerCase()) ?? null
      if (!baseRow) {
        const extra = await fetchDictRows(db, [baseName.toLowerCase()])
        baseRow = extra.get(baseName.toLowerCase()) ?? null
      }
      formNote = describeForm(baseName, ex['1'] ?? '')
    }
    const info = rowToInfo(hit, baseRow, formNote)
    if (info.gloss) {
      return {
        ...empty,
        found: true,
        source: 'ecdict' as const,
        word: cleaned,
        lemma: info.lemma,
        phonetic: info.phonetic,
        pos: info.pos,
        gloss: info.gloss,
        tags: info.tags,
        collins: info.collins,
        oxford: info.oxford,
        formNote: info.formNote,
      }
    }
  }

  // 多词短语拆词
  if (cleaned.includes(' ')) {
    const rawWords = cleaned.match(WORD_TOKEN_RE) ?? []
    const contentWords: string[] = []
    const seen = new Set<string>()
    for (const raw of rawWords) {
      const l = raw.toLowerCase()
      if (STOPWORDS.has(l) || seen.has(l) || l.length < 2) continue
      seen.add(l)
      contentWords.push(raw)
      if (contentWords.length >= 6) break
    }
    if (contentWords.length >= 2) {
      const tokKeys: string[] = []
      const perWordCands = contentWords.map((w) => {
        const list = [w.toLowerCase(), ...morphCandidates(w.toLowerCase()).slice(0, 3)]
        tokKeys.push(...list)
        return { raw: w, list }
      })
      const tokRows = await fetchDictRows(db, tokKeys)
      const tokens: typeof empty.tokens = []
      for (const { raw, list } of perWordCands) {
        let matched: DictRow | null = null
        for (const k of list) {
          const r = tokRows.get(k)
          if (r) {
            matched = r
            break
          }
        }
        if (!matched) continue
        const info = rowToInfo(matched, null, '')
        if (!info.gloss) continue
        tokens.push({
          word: raw,
          lemma: info.lemma,
          phonetic: info.phonetic,
          pos: info.pos,
          gloss: info.gloss.split('\n')[0],
          formNote: info.formNote,
        })
      }
      if (tokens.length) {
        return {
          ...empty,
          found: true,
          source: 'tokens' as const,
          tokens,
        }
      }
    }
  }

  return empty
}
