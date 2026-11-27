import { ref } from 'vue'
import { api } from './api'
import { t } from './i18n'
import { ensureDictShard, lookupLocalCoreDict } from './localDict'
import { refreshVocabCounts } from './state'
import { findSavedVocabSync, isOnline } from './sync'
import { toast } from './toast'
import type { DictLookupResult, LexEntry } from './types'

export interface LookupSentenceContext {
  sentenceId: string
  en: string
  zh: string
  para: number
}

export interface LookupScope {
  packId: string
  source: string
  lexicon?: Record<string, LexEntry>
  sentencesById: Record<string, LookupSentenceContext>
  onVocabChange?: (lemma: string, vocabId: number | null) => void
}

export interface LookupOpenOptions {
  word: string
  x: number
  y: number
  anchorTop?: number
  packId?: string
  source?: string
  context?: string
  contextZh?: string
  sentenceId?: string
  para?: number
  /** 已知的本地文章词表条目，可在接口返回前实现 0ms 瞬时展示。 */
  initialEntry?: LexEntry | null
  initialLemma?: string
  initialSaved?: boolean
}

export interface LookupPopoverState {
  word: string
  lemma: string
  x: number
  y: number
  anchorTop: number
  loading: boolean
  result: DictLookupResult | null
  context: string
  contextZh: string
  sentenceId: string
  para: number
  packId: string
  source: string
  saved: boolean
  vocabId: number | null
}

const currentScope = ref<LookupScope | null>(null)
export const lookupState = ref<LookupPopoverState | null>(null)
export const lookupBusy = ref(false)

const resultCache = new Map<string, DictLookupResult>()
let requestSeq = 0
let lastSelectionAt = 0

export function setLookupScope(scope: LookupScope): void {
  currentScope.value = scope
}

export function clearLookupScope(packId?: string): void {
  if (!packId || currentScope.value?.packId === packId) {
    currentScope.value = null
  }
}

export function getLookupScope(): LookupScope | null {
  return currentScope.value
}

export function markRecentSelection(): void {
  lastSelectionAt = performance.now()
}

export function wasRecentSelection(windowMs = 260): boolean {
  return performance.now() - lastSelectionAt < windowMs
}

export function hasActiveSelection(): boolean {
  const sel = window.getSelection()
  return Boolean(sel && !sel.isCollapsed && sel.toString().trim().length > 0)
}

export function closeLookup(): void {
  requestSeq += 1
  lookupState.value = null
}

export function clearLookupCache(): void {
  resultCache.clear()
  currentScope.value = null
  closeLookup()
}

function cacheKey(word: string, packId: string): string {
  return `${packId}::${word.trim().toLowerCase()}`
}

function cleanSelectionWord(raw: string): string {
  return raw
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/\s+/g, ' ')
    .replace(/^[^A-Za-z0-9]+|[^A-Za-z0-9]+$/g, '')
    .trim()
}

export function isLookupCandidate(raw: string): boolean {
  const text = cleanSelectionWord(raw)
  if (!text || text.length > 120) return false
  if (!/[A-Za-z]/.test(text)) return false
  // 排除包含中文字符的混合大段复制，避免在复盘中文区复制时误触发
  if (/[\u4e00-\u9fff]/.test(text)) return false
  const words = text.split(/\s+/).filter(Boolean)
  if (words.length > 8) return false
  return true
}

const WORD_CORE_RE = /[A-Za-z0-9]/
const WORD_JOINER_RE = /['\u2019-]/
const BLOCK_TAGS = new Set([
  'ADDRESS', 'ARTICLE', 'ASIDE', 'BLOCKQUOTE', 'DD', 'DIV', 'DL', 'DT',
  'FIGCAPTION', 'FIGURE', 'FOOTER', 'FORM', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6',
  'HEADER', 'HR', 'LI', 'MAIN', 'NAV', 'OL', 'P', 'PRE', 'SECTION', 'TABLE',
  'TBODY', 'TD', 'TFOOT', 'TH', 'THEAD', 'TR', 'UL',
])

function isWordCore(ch: string | undefined): boolean {
  return Boolean(ch && WORD_CORE_RE.test(ch))
}

function isWordJoiner(ch: string | undefined): boolean {
  return Boolean(ch && WORD_JOINER_RE.test(ch))
}

function closestBlock(node: Node): Element | null {
  let cur: Node | null = node.nodeType === Node.ELEMENT_NODE ? node : node.parentNode
  while (cur && cur.nodeType === Node.ELEMENT_NODE) {
    const el = cur as Element
    if (BLOCK_TAGS.has(el.tagName)) return el
    cur = el.parentNode
  }
  return document.body
}

function collectBlockTextNodes(block: Element): Text[] {
  const nodes: Text[] = []
  const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT)
  let current = walker.nextNode()
  while (current) {
    if ((current.nodeValue ?? '').length > 0) {
      nodes.push(current as Text)
    }
    current = walker.nextNode()
  }
  return nodes
}

function resolveTextEndpoint(
  container: Node,
  offset: number,
  side: 'start' | 'end',
): { node: Text; offset: number } | null {
  if (container.nodeType === Node.TEXT_NODE) {
    return { node: container as Text, offset }
  }
  if (container.nodeType !== Node.ELEMENT_NODE) return null
  const el = container as Element
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
  if (side === 'start') {
    const child = el.childNodes[offset]
    if (child) {
      if (child.nodeType === Node.TEXT_NODE) return { node: child as Text, offset: 0 }
      const sub = document.createTreeWalker(child, NodeFilter.SHOW_TEXT)
      const first = sub.nextNode()
      if (first) return { node: first as Text, offset: 0 }
    }
    const fallback = walker.nextNode()
    return fallback ? { node: fallback as Text, offset: 0 } : null
  } else {
    const child = el.childNodes[Math.max(0, offset - 1)]
    if (child) {
      if (child.nodeType === Node.TEXT_NODE) {
        return { node: child as Text, offset: (child.nodeValue ?? '').length }
      }
      const sub = document.createTreeWalker(child, NodeFilter.SHOW_TEXT)
      let last: Node | null = null
      let n = sub.nextNode()
      while (n) {
        last = n
        n = sub.nextNode()
      }
      if (last) return { node: last as Text, offset: (last.nodeValue ?? '').length }
    }
    let last: Node | null = null
    let n = walker.nextNode()
    while (n) {
      last = n
      n = walker.nextNode()
    }
    return last ? { node: last as Text, offset: (last.nodeValue ?? '').length } : null
  }
}

/**
 * 若当前划词选区的起止位置落在英文单词中间，自动扩展到完整单词边界，
 * 并同步更新浏览器选区高亮。仅在同块级元素内扩展，避免跨段落误扩。
 */
export function expandSelectionToWordBoundaries(sel: Selection): Range | null {
  if (sel.rangeCount === 0 || sel.isCollapsed) return null
  const orig = sel.getRangeAt(0)
  const rawText = orig.toString()
  if (!/[A-Za-z]/.test(rawText)) return orig

  const startPt = resolveTextEndpoint(orig.startContainer, orig.startOffset, 'start')
  const endPt = resolveTextEndpoint(orig.endContainer, orig.endOffset, 'end')
  if (!startPt || !endPt) return orig

  const startBlock = closestBlock(startPt.node)
  const endBlock = closestBlock(endPt.node)
  if (!startBlock || startBlock !== endBlock) return orig

  const textNodes = collectBlockTextNodes(startBlock)
  if (!textNodes.length) return orig

  // 把同一块内的文本节点拼接成扁平字符串，方便处理跨 <span>/<em> 的单词边界
  const offsets: number[] = []
  let full = ''
  let startIdx = -1
  let endIdx = -1

  for (const node of textNodes) {
    const base = full.length
    offsets.push(base)
    const val = node.nodeValue ?? ''
    if (node === startPt.node) startIdx = base + startPt.offset
    if (node === endPt.node) endIdx = base + endPt.offset
    full += val
  }

  if (startIdx < 0 || endIdx < 0 || startIdx >= endIdx) return orig

  // 1. 先收紧选区首尾的纯空白，确保如 " depos" 也能正确识别并补全成 "deposit"
  let s = startIdx
  let e = endIdx
  while (s < e && /\s/.test(full[s])) s += 1
  while (e > s && /\s/.test(full[e - 1])) e -= 1
  if (s >= e) return orig

  // 2. 左边界补全：起点处于单词内部时，向左扩展到单词起始字符
  if (isWordCore(full[s]) || (isWordJoiner(full[s]) && isWordCore(full[s + 1]))) {
    while (s > 0) {
      if (isWordCore(full[s - 1])) {
        s -= 1
      } else if (isWordJoiner(full[s - 1]) && s - 2 >= 0 && isWordCore(full[s - 2])) {
        s -= 1
      } else {
        break
      }
    }
  }

  // 3. 右边界补全：终点处于单词内部时，向右扩展到单词结束字符
  if (isWordCore(full[e - 1]) || (isWordJoiner(full[e - 1]) && isWordCore(full[e - 2]))) {
    while (e < full.length) {
      if (isWordCore(full[e])) {
        e += 1
      } else if (isWordJoiner(full[e]) && e + 1 < full.length && isWordCore(full[e + 1])) {
        e += 1
      } else {
        break
      }
    }
  }

  if (s === startIdx && e === endIdx) return orig

  const locate = (globalPos: number, preferEnd: boolean): { node: Text; offset: number } | null => {
    for (let i = 0; i < textNodes.length; i += 1) {
      const nodeStart = offsets[i]
      const len = (textNodes[i].nodeValue ?? '').length
      const nodeEnd = nodeStart + len
      if (preferEnd ? globalPos <= nodeEnd : globalPos < nodeEnd) {
        return { node: textNodes[i], offset: Math.max(0, Math.min(len, globalPos - nodeStart)) }
      }
    }
    const last = textNodes[textNodes.length - 1]
    return { node: last, offset: (last.nodeValue ?? '').length }
  }

  const newStart = locate(s, false)
  const newEnd = locate(e, true)
  if (!newStart || !newEnd) return orig

  const expanded = document.createRange()
  expanded.setStart(newStart.node, newStart.offset)
  expanded.setEnd(newEnd.node, newEnd.offset)

  // 仅当扩展结果仍属于合法查词候选时才应用视觉选区吸附
  if (!isLookupCandidate(expanded.toString())) return orig

  sel.removeAllRanges()
  sel.addRange(expanded)
  return expanded
}

export async function openLookup(options: LookupOpenOptions): Promise<void> {
  const cleaned = cleanSelectionWord(options.word)
  if (!cleaned) return

  const scope = currentScope.value
  const packId = options.packId ?? scope?.packId ?? ''
  const source = options.source ?? scope?.source ?? ''
  const anchorTop = options.anchorTop ?? options.y

  const seq = ++requestSeq
  const key = cacheKey(cleaned, packId)
  const cached = resultCache.get(key)

  // 1. 优先查浏览器本地 66k 核心词库 + 当前文章包词表（0ms 纯本地响应，离线秒开）
  const localHit =
    cached ??
    lookupLocalCoreDict(
      cleaned,
      scope?.packId === packId ? scope.lexicon : null,
      findSavedVocabSync,
    )

  if (localHit) {
    // 实时用本地生词映射刷新 saved 状态
    const savedId = findSavedVocabSync(localHit.lemma, cleaned)
    const freshHit: DictLookupResult = {
      ...localHit,
      saved: savedId !== null,
      vocabId: savedId,
    }
    lookupState.value = {
      word: freshHit.word || cleaned,
      lemma: freshHit.lemma || cleaned.toLowerCase(),
      x: options.x,
      y: options.y,
      anchorTop,
      loading: false,
      result: freshHit,
      context: options.context ?? '',
      contextZh: options.contextZh ?? '',
      sentenceId: options.sentenceId ?? '',
      para: options.para ?? 0,
      packId,
      source,
      saved: freshHit.saved,
      vocabId: freshHit.vocabId,
    }
    return
  }

  // 2. 超出 66k 核心词库的生僻词或词组：若当前离线则直接展示离线结果，在线则回退查服务端 77 万词库
  if (!isOnline.value) {
    const savedId = findSavedVocabSync(cleaned, cleaned)
    lookupState.value = {
      word: cleaned,
      lemma: cleaned.toLowerCase(),
      x: options.x,
      y: options.y,
      anchorTop,
      loading: false,
      result: null,
      context: options.context ?? '',
      contextZh: options.contextZh ?? '',
      sentenceId: options.sentenceId ?? '',
      para: options.para ?? 0,
      packId,
      source,
      saved: savedId !== null,
      vocabId: savedId,
    }
    return
  }

  const optimisticResult: DictLookupResult | null = options.initialEntry
    ? {
        query: cleaned,
        found: true,
        source: 'pack',
        word: cleaned,
        lemma: options.initialLemma ?? cleaned.toLowerCase(),
        phonetic: options.initialEntry.phonetic ?? '',
        pos: options.initialEntry.pos ?? '',
        gloss: options.initialEntry.gloss ?? '',
        dictGloss: '',
        definition: '',
        tags: [],
        collins: 0,
        oxford: false,
        formNote: '',
        tokens: [],
        saved: Boolean(options.initialSaved),
        vocabId: null,
        dictReady: true,
      }
    : null

  lookupState.value = {
    word: cleaned,
    lemma: optimisticResult?.lemma ?? options.initialLemma ?? cleaned.toLowerCase(),
    x: options.x,
    y: options.y,
    anchorTop,
    loading: true,
    result: optimisticResult,
    context: options.context ?? '',
    contextZh: options.contextZh ?? '',
    sentenceId: options.sentenceId ?? '',
    para: options.para ?? 0,
    packId,
    source,
    saved: optimisticResult?.saved ?? Boolean(options.initialSaved),
    vocabId: optimisticResult?.vocabId ?? null,
  }

  try {
    // 1. 优先走超轻量单次查词接口（云端 D1 仅 ~250B / <0.3s；本地 FastAPI 77 万库 ~5ms），
    //    避免首访未缓存 2MB 离线核心词库时苦等大文件下载
    const res = await api.dictLookup(cleaned, packId || undefined)
    if (seq !== requestSeq || !lookupState.value) return
    if (res.found) {
      resultCache.set(key, res)
      const localSavedId = findSavedVocabSync(res.lemma || cleaned, cleaned)
      const finalSavedId = localSavedId ?? res.vocabId
      lookupState.value = {
        ...lookupState.value,
        word: res.word || cleaned,
        lemma: res.lemma || cleaned.toLowerCase(),
        loading: false,
        result: { ...res, saved: finalSavedId !== null, vocabId: finalSavedId },
        saved: finalSavedId !== null,
        vocabId: finalSavedId,
      }
      return
    }

    // 2. 6.6 万核心库未命中的极生僻词：再按首字母拉取 R2 全量 77 万分片并缓存到 IndexedDB
    const firstWord = cleaned.split(/\s+/)[0] || cleaned
    const shardOk = await ensureDictShard(firstWord, (letter) => api.dictShard(letter))
    if (seq !== requestSeq || !lookupState.value) return
    if (shardOk) {
      const shardHit = lookupLocalCoreDict(
        cleaned,
        scope?.packId === packId ? scope.lexicon : null,
        findSavedVocabSync,
      )
      if (shardHit) {
        resultCache.set(key, shardHit)
        const savedId = findSavedVocabSync(shardHit.lemma, cleaned)
        lookupState.value = {
          ...lookupState.value,
          word: shardHit.word || cleaned,
          lemma: shardHit.lemma || cleaned.toLowerCase(),
          loading: false,
          result: { ...shardHit, saved: savedId !== null, vocabId: savedId },
          saved: savedId !== null,
          vocabId: savedId,
        }
        return
      }
    }

    resultCache.set(key, res)
    const localSavedId = findSavedVocabSync(res.lemma || cleaned, cleaned)
    const finalSavedId = localSavedId ?? res.vocabId
    lookupState.value = {
      ...lookupState.value,
      word: res.word || cleaned,
      lemma: res.lemma || cleaned.toLowerCase(),
      loading: false,
      result: res,
      saved: finalSavedId !== null,
      vocabId: finalSavedId,
    }
  } catch {
    if (seq !== requestSeq || !lookupState.value) return
    lookupState.value = {
      ...lookupState.value,
      loading: false,
    }
  }
}

export async function lookupSubword(word: string): Promise<void> {
  const cur = lookupState.value
  if (!cur) return
  await openLookup({
    word,
    x: cur.x,
    y: cur.y,
    anchorTop: cur.anchorTop,
    packId: cur.packId,
    source: cur.source,
    context: cur.context,
    contextZh: cur.contextZh,
    sentenceId: cur.sentenceId,
    para: cur.para,
  })
}

function updateCachedSaved(lemma: string, saved: boolean, vocabId: number | null): void {
  const target = lemma.trim().toLowerCase()
  for (const [k, item] of resultCache.entries()) {
    if (item.lemma.toLowerCase() === target || item.word.toLowerCase() === target) {
      resultCache.set(k, { ...item, saved, vocabId })
    }
  }
}

export async function toggleLookupVocab(): Promise<void> {
  const cur = lookupState.value
  if (!cur || lookupBusy.value) return
  lookupBusy.value = true
  try {
    if (cur.saved) {
      let id = cur.vocabId ?? findSavedVocabSync(cur.lemma, cur.word)
      if (id == null && isOnline.value) {
        const res = await api.dictLookup(cur.lemma || cur.word, cur.packId || undefined)
        id = res.vocabId
      }
      if (id != null) {
        await api.vocabDelete(id)
      }
      cur.saved = false
      cur.vocabId = null
      if (cur.result) {
        cur.result = { ...cur.result, saved: false, vocabId: null }
      }
      updateCachedSaved(cur.lemma, false, null)
      currentScope.value?.onVocabChange?.(cur.lemma, null)
      toast(t('toast.removed'))
    } else {
      const res = cur.result
      const gloss =
        res?.gloss ||
        (res?.tokens?.length
          ? res.tokens.map((tok) => `${tok.word}: ${tok.gloss}`).join('；')
          : '')
      const response = await api.vocabAdd({
        lemma: cur.lemma || cur.word.toLowerCase(),
        word: cur.word,
        gloss,
        pos: res?.pos ?? '',
        phonetic: res?.phonetic ?? '',
        source: cur.source,
        context:
          cur.context || cur.contextZh
            ? {
                packId: cur.packId,
                sentenceId: cur.sentenceId,
                en: cur.context,
                zh: cur.contextZh,
                para: cur.para,
              }
            : undefined,
      })
      const newId = response.item.id
      cur.saved = true
      cur.vocabId = newId
      if (cur.result) {
        cur.result = { ...cur.result, saved: true, vocabId: newId }
      }
      updateCachedSaved(cur.lemma, true, newId)
      currentScope.value?.onVocabChange?.(cur.lemma, newId)
      toast(t('toast.added'))
    }
    await refreshVocabCounts()
  } catch (error) {
    toast(error instanceof Error ? error.message : t('toast.loadFailed'))
  } finally {
    lookupBusy.value = false
  }
}

/** 尝试从选区所在的 DOM 节点提取原句上下文（支持精读正文与全站英文块）。 */
export function extractSelectionContext(anchorNode: Node | null, selectedText: string): {
  context: string
  contextZh: string
  sentenceId: string
  para: number
} {
  const empty = { context: '', contextZh: '', sentenceId: '', para: 0 }
  if (!anchorNode) return empty

  const el =
    anchorNode.nodeType === Node.ELEMENT_NODE
      ? (anchorNode as HTMLElement)
      : anchorNode.parentElement
  if (!el) return empty

  // 1. 精读正文：通过 .sent[data-id] 精确拿到英文原句、中文译文与段号
  const sentEl = el.closest<HTMLElement>('.sent[data-id]')
  const sentId = sentEl?.dataset.id
  const scope = currentScope.value
  if (sentId && scope?.sentencesById[sentId]) {
    const s = scope.sentencesById[sentId]
    return { context: s.en, contextZh: s.zh, sentenceId: s.sentenceId, para: s.para }
  }

  // 2. 其他区域（题干/选项/导读/生词本例句等）：从最近语义块抽取包含该词的英文句
  const block = el.closest<HTMLElement>(
    'p, li, blockquote, .stem, .opt-text, .en, .diag, .chain, .card-text, td, dd',
  )
  if (!block) return empty
  const raw = (block.textContent ?? '').replace(/\s+/g, ' ').trim()
  if (!raw || raw.length > 600) return empty
  // 只在区块主要是英文时作为英文例句上下文
  const latinCount = (raw.match(/[A-Za-z]/g) ?? []).length
  if (latinCount < 10 || latinCount < raw.length * 0.45) return empty
  if (raw.toLowerCase() === selectedText.toLowerCase()) return empty

  // 按句号/问号/感叹号切分，取包含选中词的那一句
  const sentences = raw.split(/(?<=[.!?])\s+/)
  const lowTarget = selectedText.toLowerCase()
  const hit = sentences.find((s) => s.toLowerCase().includes(lowTarget)) ?? raw
  if (hit.length > 260) return empty
  return { context: hit, contextZh: '', sentenceId: '', para: 0 }
}
