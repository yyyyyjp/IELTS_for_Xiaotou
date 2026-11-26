/**
 * 网页端导出包合成 + AI 复盘解析 + 提示词生成（Cloudflare Worker TypeScript 版）。
 * 与 app/server/services/pack_importer.py 保持完全一致的数据结构与容错能力。
 */

const TYPE_MAP: Record<string, string> = {
  mcq_single: 'mcq',
  mcq_multi: 'mcq',
  ynng: 'ynng',
  tfng: 'tfng',
  completion_summary: 'summary',
  matching_heading: 'matching',
  matching_paragraph: 'matching',
  matching_feature: 'matching',
  matching_sentence_ending: 'matching',
  matching_other: 'matching',
}

const TYPE_LABELS: Record<string, string> = {
  mcq: '选择题',
  mcq_single: '选择题',
  mcq_multi: '多选题',
  summary: '摘要填空',
  completion_summary: '摘要填空',
  ynng: '判断题',
  tfng: '判断题',
  gap: '填空题',
  matching: '匹配题',
  matching_heading: '标题匹配',
  matching_paragraph: '段落匹配',
  matching_feature: '特征匹配',
  matching_sentence_ending: '句子匹配',
}

const LEGACY_LABELS: Record<string, string> = {
  为什么对: 'why-right',
  错在哪: 'why-wrong',
  为什么错: 'why-wrong',
}

function plain(text: unknown): string {
  if (text == null) return ''
  return String(text)
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p\s*>/gi, '\n\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .trim()
}

function cleanInstruction(text: string): string {
  return text.replace(/^Questions?\s+\d+(?:\s*[–-]\s*\d+)?\s*\n+/i, '').trim()
}

function labelKey(label: unknown): string {
  return String(label ?? '')
    .trim()
    .replace(/^(paragraph|para\.?)\s*/i, '')
}

function normalizeBook(book: string): string {
  const s = book.trim()
  const m = /^剑雅\s*(\d+)$/.exec(s)
  return m ? `剑桥雅思 ${m[1]}` : s
}

function deriveId(book: string, test: string, part: string, fallback = ''): string {
  const b = book.match(/\d+/)?.[0]
  const t = test.match(/\d+/)?.[0]
  const p = part.match(/\d+/)?.[0]
  if (b && t && p) return `cam${b}-t${t}-p${p}`
  const safe = fallback.replace(/[^a-zA-Z0-9._-]+/g, '-').replace(/^-+|-+$/g, '')
  if (safe) return `reading-${safe}`
  throw new Error('无法从书名/Test/Passage 推导内容包 ID')
}

export function extractJsonObject(rawText: string): Record<string, unknown> {
  const text = (rawText || '').trim()
  if (!text) return {}

  const candidates: string[] = []
  const fenceRe = /```(?:json|jsonc)?\s*\n([\s\S]*?)```/gi
  let m: RegExpExecArray | null
  while ((m = fenceRe.exec(text)) !== null) {
    if (m[1]?.trim()) candidates.push(m[1].trim())
  }
  candidates.push(text)
  const first = text.indexOf('{')
  const last = text.lastIndexOf('}')
  if (first >= 0 && last > first) {
    const sliced = text.slice(first, last + 1)
    if (!candidates.includes(sliced)) candidates.push(sliced)
  }

  let lastErr: Error | null = null
  for (const cand of candidates) {
    try {
      const parsed = JSON.parse(cand)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        const obj = parsed as Record<string, unknown>
        if (!('review' in obj) && !('guide' in obj) && ('sections' in obj || 'diagnoses' in obj)) {
          return { review: obj }
        }
        return obj
      }
    } catch (e) {
      lastErr = e instanceof Error ? e : new Error(String(e))
    }
  }
  throw new Error(`AI 复盘 JSON 解析失败：${lastErr?.message ?? '格式无效'}`)
}

function cleanCites(raw: unknown): { p: number; b: number[] }[] {
  const out: { p: number; b: number[] }[] = []
  if (!raw) return out
  const arr = Array.isArray(raw) ? raw : [raw]
  for (const item of arr) {
    if (typeof item === 'string') {
      const m = /^p(\d+)s(\d+)$/i.exec(item.trim())
      if (m) out.push({ p: Number(m[1]), b: [Number(m[2]) - 1] })
      continue
    }
    if (!item || typeof item !== 'object') continue
    const obj = item as Record<string, unknown>
    const p = Number(obj.p ?? obj.para ?? obj.paragraph)
    if (!Number.isFinite(p)) continue
    const rawB = obj.b ?? obj.sentences ?? []
    const bArr = Array.isArray(rawB) ? rawB : typeof rawB === 'number' ? [rawB] : []
    const nums = bArr.map((x) => Number(x)).filter((x) => Number.isFinite(x))
    if (!nums.length && obj.s != null && Number.isFinite(Number(obj.s))) {
      nums.push(Number(obj.s) - 1)
    }
    out.push({ p, b: nums })
  }
  return out
}

export function normalizeAnalysis(raw: Record<string, unknown>): {
  review: Record<string, unknown> | null
  guide: Record<string, unknown> | null
} {
  let review =
    raw.review && typeof raw.review === 'object' && !Array.isArray(raw.review)
      ? ({ ...(raw.review as Record<string, unknown>) })
      : null
  let guide =
    raw.guide && typeof raw.guide === 'object' && !Array.isArray(raw.guide)
      ? ({ ...(raw.guide as Record<string, unknown>) })
      : null

  if (review) {
    const rawSecs = Array.isArray(review.sections) ? review.sections : []
    review.sections = rawSecs
      .filter((s) => s && typeof s === 'object')
      .map((sec, idx) => {
        const s = { ...(sec as Record<string, unknown>) }
        const kind = String(s.kind ?? s.type ?? 'gap')
        s.id = String(s.id ?? idx + 1)
        s.kind = kind
        s.title = String(s.title ?? TYPE_LABELS[kind] ?? kind)
        s.cites = cleanCites(s.cites)
        if (Array.isArray(s.rows)) {
          s.rows = s.rows
            .filter((r) => r && typeof r === 'object')
            .map((row) => {
              const r = { ...(row as Record<string, unknown>) }
              if (r.no != null && /^\d+$/.test(String(r.no))) r.no = Number(r.no)
              r.diag = r.diag ?? ''
              r.cites = cleanCites(r.cites)
              return r
            })
        }
        const items = Array.isArray(s.items) ? s.items : []
        s.items = items
          .filter((it) => it && typeof it === 'object')
          .map((item) => {
            const it = { ...(item as Record<string, unknown>) }
            if (it.no != null && Number.isFinite(Number(it.no))) it.no = Number(it.no)
            const lbl = String(it.label ?? '').trim()
            it.label = LEGACY_LABELS[lbl] ?? lbl
            it.cites = cleanCites(it.cites)
            return it
          })
        return s
      })
    review.diagnoses = Array.isArray(review.diagnoses) ? review.diagnoses : []
    review.actions = Array.isArray(review.actions) ? review.actions : []
  }

  if (guide) {
    const arg =
      guide.argument && typeof guide.argument === 'object'
        ? { ...(guide.argument as Record<string, unknown>) }
        : {}
    arg.negative = Array.isArray(arg.negative) ? arg.negative : []
    arg.positive = Array.isArray(arg.positive) ? arg.positive : []
    arg.punch = arg.punch ?? ''
    guide.argument = arg
    guide.band = Array.isArray(guide.band) ? guide.band : []
    guide.legend = Array.isArray(guide.legend) ? guide.legend : []
    guide.rows = Array.isArray(guide.rows) ? guide.rows : []
    guide.terms = Array.isArray(guide.terms) ? guide.terms : []
    guide.why = Array.isArray(guide.why) ? guide.why : []
    const echo =
      guide.echo && typeof guide.echo === 'object'
        ? { ...(guide.echo as Record<string, unknown>) }
        : {}
    echo.neg = echo.neg ?? ''
    echo.pos = echo.pos ?? ''
    echo.note = echo.note ?? ''
    guide.echo = echo
  }

  return { review, guide }
}

export function validateAnalysis(
  review: Record<string, unknown> | null,
  guide: Record<string, unknown> | null,
  paragraphs: { no: number; sentences: unknown[] }[],
  questionNos: Set<number>,
): string[] {
  const limits = new Map(paragraphs.map((p) => [p.no, p.sentences.length]))
  const out: string[] = []

  const checkCites = (cites: unknown, where: string) => {
    for (const c of Array.isArray(cites) ? cites : []) {
      const cite = c as { p: number; b: number[] }
      const len = limits.get(cite.p)
      if (len === undefined) {
        out.push(`${where}：引文段落 p=${cite.p} 不存在（共 ${limits.size} 段）`)
        continue
      }
      const bad = (cite.b ?? []).filter((i) => i < 0 || i >= len)
      if (bad.length) {
        out.push(`${where}：第 ${cite.p} 段没有句序 [${bad.join(',')}]（本段范围 0–${len - 1}）`)
      }
    }
  }

  if (review) {
    if (!String(review.title ?? '').trim()) {
      out.push('review 缺少顶层 title（复盘一句话标题）')
    }
    for (const sec of (review.sections as Record<string, unknown>[]) ?? []) {
      const title = String(sec.title ?? sec.kind ?? 'section')
      checkCites(sec.cites, title)
      for (const it of (sec.items as Record<string, unknown>[]) ?? []) {
        if (questionNos.size && !questionNos.has(Number(it.no))) {
          out.push(`${title}：题号 ${it.no} 不在本篇题号范围内`)
        }
        checkCites(it.cites, `${title} 第 ${it.no} 题`)
      }
      for (const row of (sec.rows as Record<string, unknown>[]) ?? []) {
        if (questionNos.size && !questionNos.has(Number(row.no))) {
          out.push(`${title}：题号 ${row.no} 不在本篇题号范围内`)
        }
        checkCites(row.cites, `${title} 第 ${row.no} 空`)
      }
    }
  }

  if (guide && limits.size) {
    for (const cell of (guide.band as Record<string, unknown>[]) ?? []) {
      if (!limits.has(Number(cell.n))) {
        out.push(`guide.band：段落号 n=${cell.n} 超出原文段落范围`)
      }
    }
    for (const row of (guide.rows as Record<string, unknown>[]) ?? []) {
      if (!limits.has(Number(row.n))) {
        out.push(`guide.rows：段落号 n=${row.n} 超出原文段落范围`)
      }
    }
  }
  return out
}

export function summarizeAnalysis(
  review: Record<string, unknown> | null,
  guide: Record<string, unknown> | null,
  lexiconCount = 0,
) {
  const covered = new Set<number>()
  const sections = (review?.sections as Record<string, unknown>[]) ?? []
  for (const sec of sections) {
    for (const it of (sec.items as Record<string, unknown>[]) ?? []) {
      if (typeof it.no === 'number') covered.add(it.no)
    }
    for (const row of (sec.rows as Record<string, unknown>[]) ?? []) {
      if (typeof row.no === 'number') covered.add(row.no)
    }
  }
  return {
    hasReview: Boolean(review),
    reviewTitle: String(review?.title ?? ''),
    sectionCount: sections.length,
    coveredQuestions: covered.size,
    diagnosisCount: Array.isArray(review?.diagnoses) ? review.diagnoses.length : 0,
    hasGuide: Boolean(guide),
    guideTitle: String(guide?.title ?? ''),
    bandCount: Array.isArray(guide?.band) ? guide.band.length : 0,
    lexiconCount,
  }
}

export function buildParagraphsFromPassage(passage: Record<string, unknown>) {
  const rawSents = Array.isArray(passage.sentences)
    ? ([...passage.sentences] as Record<string, unknown>[]).sort(
        (a, b) => Number(a.i ?? 0) - Number(b.i ?? 0),
      )
    : []
  const declared = (Array.isArray(passage.paragraphs) ? passage.paragraphs : [])
    .map((p) => labelKey((p as Record<string, unknown>).label))
    .filter(Boolean)

  if (rawSents.length) {
    const byLabel = new Map<string, Record<string, unknown>[]>()
    for (const s of rawSents) {
      const k = labelKey(s.paragraph)
      const list = byLabel.get(k)
      if (list) list.push(s)
      else byLabel.set(k, [s])
    }
    const order = [...declared, ...Array.from(byLabel.keys()).filter((k) => !declared.includes(k))]
    const seen = new Set<string>()
    const paragraphs: { no: number; sentences: { id: string; en: string; zh: string }[] }[] = []
    let no = 1
    for (const k of order) {
      if (seen.has(k) || !byLabel.get(k)?.length) continue
      seen.add(k)
      const sents = byLabel.get(k)!.map((s, idx) => ({
        id: `p${no}s${idx + 1}`,
        en: plain(s.text),
        zh: plain(s.translation),
      }))
      paragraphs.push({ no, sentences: sents })
      no += 1
    }
    return paragraphs
  }

  const out: { no: number; sentences: { id: string; en: string; zh: string }[] }[] = []
  let no = 1
  for (const p of Array.isArray(passage.paragraphs) ? passage.paragraphs : []) {
    const text = plain((p as Record<string, unknown>).text)
    if (!text) continue
    out.push({ no, sentences: [{ id: `p${no}s1`, en: text, zh: '' }] })
    no += 1
  }
  return out
}

function optionList(raw: unknown): { key: string; text: string }[] {
  if (!Array.isArray(raw)) return []
  const out: { key: string; text: string }[] = []
  for (const o of raw) {
    if (!o || typeof o !== 'object') continue
    const obj = o as Record<string, unknown>
    const key = String(obj.key ?? obj.k ?? '')
    const text = plain(obj.text ?? obj.t ?? '')
    if (key) out.push({ key, text })
  }
  return out
}

export function buildGroupsFromExport(
  questions: Record<string, unknown>[],
  groupsList: Record<string, unknown>[],
) {
  const groups = new Map<string, Record<string, unknown>>()
  for (const g of groupsList) {
    if (g?.group_id) groups.set(String(g.group_id), g)
  }
  const byGroup = new Map<string, Record<string, unknown>[]>()
  for (const q of questions) {
    const gid = String(q.group_id ?? `g${q.q_number}`)
    const list = byGroup.get(gid)
    if (list) list.push(q)
    else byGroup.set(gid, [q])
  }

  const result: Record<string, unknown>[] = []
  for (const [gid, items] of byGroup.entries()) {
    const meta = groups.get(gid) ?? {}
    const qtype = String(meta.question_type ?? items[0]?.question_type ?? 'other')
    let ptype = TYPE_MAP[qtype] ?? 'gap'
    const sortedQs = items
      .filter((q) => q.q_number != null)
      .sort((a, b) => Number(a.q_number) - Number(b.q_number))

    const qidToNo = new Map<string, number>()
    const validNos = new Set<number>()
    for (const q of sortedQs) {
      const qno = Math.trunc(Number(q.q_number))
      validNos.add(qno)
      const tail = String(q.question_id ?? '').split(':').pop() ?? ''
      if (/^\d+$/.test(tail)) qidToNo.set(tail, qno)
    }

    const body = plain(meta.body)
    let text = body.replace(/\$(\d+)\$/g, (_, rawN: string) => {
      const n = Number(rawN)
      const resolved =
        qidToNo.get(rawN) ??
        (validNos.has(n) ? n : n >= 1 && n <= sortedQs.length ? Math.trunc(Number(sortedQs[n - 1].q_number)) : n)
      return `{{${resolved}}}`
    })
    text = text
      .replace(/([A-Za-z0-9])(\{\{\d+\}\})/g, '$1 $2')
      .replace(/(\{\{\d+\}\})([A-Za-z0-9])/g, '$1 $2')
    if (ptype === 'summary' && !text.includes('{{')) {
      ptype = 'gap'
      text = ''
    }

    const seen = new Set<number>()
    const qItems: Record<string, unknown>[] = []
    for (const q of sortedQs) {
      const no = Math.trunc(Number(q.q_number))
      if (seen.has(no)) continue
      seen.add(no)
      let answer: string | string[] = String(q.correct_answer ?? '').trim()
      if (q.question_type === 'mcq_multi' && answer.includes(',')) {
        answer = answer.split(',').map((s) => s.trim()).filter(Boolean)
      }
      qItems.push({
        no,
        stem: ptype !== 'summary' ? plain(q.stem) : '',
        options: ptype === 'mcq' ? optionList(q.options) : [],
        answer,
        mine: String(q.yours ?? '').trim(),
        correct: q.is_correct ?? null,
      })
    }
    if (!qItems.length) continue
    const nos = qItems.map((it) => Number(it.no))
    result.push({
      id: gid,
      type: ptype,
      from: Math.min(...nos),
      to: Math.max(...nos),
      instruction: cleanInstruction(plain(meta.instruction)),
      title: plain(meta.title),
      text,
      options: optionList(meta.options),
      items: qItems,
    })
  }
  result.sort((a, b) => Number(a.from ?? 0) - Number(b.from ?? 0))
  return result
}

export function normalizeLexEntry(v: unknown): Record<string, unknown> | null {
  if (typeof v === 'string') {
    const raw = v.trim()
    const m = /^((?:[a-z]+\.)(?:\s*\/\s*[a-z]+\.)*)\s*(.+)$/i.exec(raw)
    if (m) return { pos: m[1].trim(), gloss: m[2].trim(), raw }
    return { gloss: raw, raw }
  }
  if (v && typeof v === 'object') return v as Record<string, unknown>
  return null
}

export function buildPackFromExportData(params: {
  passage: Record<string, unknown>
  questions: Record<string, unknown>[]
  groups: Record<string, unknown>[]
  attempt: Record<string, unknown> | null
  analysisText: string
  packIdOverride?: string
  existingDetail?: Record<string, unknown> | null
}) {
  const paragraphs = buildParagraphsFromPassage(params.passage)
  if (!paragraphs.length) throw new Error('这篇没有原文段落')
  const questionGroups = buildGroupsFromExport(params.questions, params.groups)
  if (!questionGroups.length) throw new Error('没有匹配到题目数据')

  const analysisRaw = params.analysisText.trim() ? extractJsonObject(params.analysisText) : {}
  const { review, guide } = normalizeAnalysis(analysisRaw)

  const book = String(params.passage.book ?? params.attempt?.book ?? '')
  const test = String(params.passage.test ?? params.attempt?.test ?? '')
  const part = String(params.passage.part ?? params.attempt?.part ?? '')
  const packId =
    params.packIdOverride?.trim() ||
    String(analysisRaw.packId ?? '').trim() ||
    deriveId(book, test, part, String(params.passage.part_id ?? params.passage.passage_id ?? ''))

  const existing = params.existingDetail ?? null
  const lexicon: Record<string, unknown> = {
    ...((existing?.lexicon as Record<string, unknown>) ?? {}),
  }
  let lexAdded = 0
  if (analysisRaw.lexicon && typeof analysisRaw.lexicon === 'object') {
    for (const [k, v] of Object.entries(analysisRaw.lexicon as Record<string, unknown>)) {
      const norm = normalizeLexEntry(v)
      if (norm && k.trim()) {
        if (!(k.trim() in lexicon)) lexAdded += 1
        lexicon[k.trim()] = norm
      }
    }
  }

  const allItems = questionGroups.flatMap((g) => (g.items as Record<string, unknown>[]) ?? [])
  const answered = allItems.filter((it) => String(it.mine ?? '').trim()).length
  const correct = allItems.filter((it) => it.correct === true).length
  const total = allItems.length

  const attemptObj =
    params.attempt && answered > 0
      ? {
          source: 'idictation',
          submittedAt: String(params.attempt.submitted_at ?? ''),
          durationSec: Number(params.attempt.duration_sec ?? 0),
          score: correct,
          total,
          answered,
          blank: total - answered,
          wrong: answered - correct,
          accuracy: total ? Math.round((correct / total) * 10000) / 10000 : 0,
          byType: Array.isArray(params.attempt.by_type)
            ? (params.attempt.by_type as Record<string, unknown>[]).map((row) => ({
                label: String(row.question_type_zh ?? row.question_type ?? ''),
                correct: row.correct,
                total: row.total,
                accuracy: row.accuracy,
              }))
            : [],
        }
      : (existing?.attempt as Record<string, unknown> | null) ?? null

  const meta = {
    book: normalizeBook(book) || String((existing?.meta as Record<string, unknown>)?.book ?? ''),
    test: test || String((existing?.meta as Record<string, unknown>)?.test ?? ''),
    passage: part || String((existing?.meta as Record<string, unknown>)?.passage ?? ''),
    title:
      plain(params.passage.title) ||
      String((existing?.meta as Record<string, unknown>)?.title ?? packId),
    durationSec: Number((attemptObj as Record<string, unknown>)?.durationSec ?? 0),
    source: 'idictation',
    order: Number((existing?.meta as Record<string, unknown>)?.order ?? 0),
  }

  const finalReview = review ?? (existing?.review as Record<string, unknown> | null) ?? null
  const finalGuide = guide ?? (existing?.guide as Record<string, unknown> | null) ?? null
  const sentenceCount = paragraphs.reduce((acc, p) => acc + p.sentences.length, 0)
  const qNos = new Set(allItems.map((it) => Number(it.no)))
  const warnings = validateAnalysis(finalReview, finalGuide, paragraphs, qNos)
  const analysisSummary = summarizeAnalysis(finalReview, finalGuide, lexAdded)

  const detail = {
    id: packId,
    kind: 'reading',
    origin: String(existing?.origin ?? 'custom'),
    meta,
    counts: {
      sentences: sentenceCount,
      questions: total,
      words: Object.keys(lexicon).length,
      items: 0,
    },
    paragraphs,
    questionGroups,
    lexicon,
    items: [],
    attempt: attemptObj,
    hasReview: Boolean(finalReview),
    hasGuide: Boolean(finalGuide),
    review: finalReview,
    guide: finalGuide,
  }

  const summary = {
    id: packId,
    kind: 'reading',
    origin: detail.origin,
    meta,
    counts: detail.counts,
    attempt: attemptObj,
    hasReview: detail.hasReview,
    hasGuide: detail.hasGuide,
  }

  return {
    packId,
    detail,
    summary,
    warnings,
    analysisSummary,
    paragraphsCount: paragraphs.length,
    sentencesCount: sentenceCount,
    questionsCount: total,
  }
}

export function buildPromptText(
  detail: Record<string, unknown>,
  rawAttempt?: Record<string, unknown> | null,
): string {
  const meta = (detail.meta as Record<string, unknown>) ?? {}
  const label = [meta.book, meta.test, meta.passage].filter(Boolean).join(' · ')
  const lines: string[] = [
    '请为我的雅思阅读练习生成深度复盘与文章结构导读 JSON。',
    `篇目：${label} · ${meta.title ?? detail.id}`,
  ]
  const att = detail.attempt as Record<string, unknown> | null
  if (att) {
    const dur = Number(att.durationSec ?? 0)
    lines.push(
      `成绩：${att.score} / ${att.total}（错 ${att.wrong}，空 ${att.blank}），用时 ${Math.floor(dur / 60)}:${String(dur % 60).padStart(2, '0')}`,
    )
  }
  lines.push('', '## 一、原文（已按 [p段号, b=段内0起句序] 标号，写 cites 时请直接引用）')
  for (const p of (detail.paragraphs as { no: number; sentences: { en: string }[] }[]) ?? []) {
    lines.push(`\n### 第 ${p.no} 段`)
    p.sentences.forEach((s, idx) => {
      lines.push(`[p${p.no}, b=${idx}] ${s.en}`)
    })
  }
  lines.push('\n## 二、题目与我的作答')
  for (const g of (detail.questionGroups as Record<string, unknown>[]) ?? []) {
    lines.push(`\n### 题组 ${g.from}–${g.to}（kind=${g.type}）`)
    if (g.instruction) lines.push(`指令：${g.instruction}`)
    if (g.title) lines.push(`标题：${g.title}`)
    if (g.text) lines.push(`摘要正文：${g.text}`)
    if (Array.isArray(g.options) && g.options.length) {
      lines.push(
        '共用选项池：' +
          (g.options as { key: string; text: string }[]).map((o) => `${o.key}: ${o.text}`).join(' | '),
      )
    }
    for (const q of (g.items as Record<string, unknown>[]) ?? []) {
      const ans = Array.isArray(q.answer) ? q.answer.join('/') : String(q.answer ?? '')
      const status = q.correct === true ? '✓正确' : q.mine ? '✗错误' : '○未答'
      let line = `- Q${q.no} [${status}] 我的作答=${q.mine || '(空)'} | 正确答案=${ans}`
      if (q.stem) line += ` | 题干：${q.stem}`
      lines.push(line)
      if (Array.isArray(q.options)) {
        for (const o of q.options as { key: string; text: string }[]) {
          lines.push(`    ${o.key}. ${o.text}`)
        }
      }
    }
  }

  const marks = rawAttempt?.marks as { highlights?: Record<string, unknown>[]; notes?: Record<string, unknown>[] } | undefined
  if (marks?.highlights?.length || marks?.notes?.length) {
    lines.push('\n## 二（附）、我在做题时留下的高亮与笔记轨迹')
    for (const h of (marks.highlights ?? []).slice(0, 40)) {
      const txt = plain(h.text)
      if (txt.length >= 2) lines.push(`- [${h.scope ?? 'article'} ${h.paragraph ?? h.question_number ?? ''}] ${txt}`)
    }
    for (const n of (marks.notes ?? []).slice(0, 20)) {
      const txt = plain(n.content)
      if (txt) lines.push(`- [笔记] ${txt}`)
    }
  }

  lines.push(
    '\n## 三、输出要求',
    '请只输出一个合法 JSON 对象（含 review / guide / lexicon），cites 里的 p 从 1 起、b 从 0 起对应上面的 [p段号, b=句序]；只有 kind="summary" 用 rows[]，其余题型全部用 items[]。',
  )
  return lines.join('\n')
}
