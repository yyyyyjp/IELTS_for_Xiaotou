import { ref } from 'vue'

export interface ExportPassageEntry {
  key: string
  derivedId: string
  passageId: string
  book: string
  test: string
  part: string
  title: string
  passage: Record<string, unknown>
  attempts: Record<string, unknown>[]
}

export interface LoadedExportDataset {
  passagesCount: number
  attemptsCount: number
  questionsCount: number
  groupsCount: number
  hasPassages: boolean
  hasAttempts: boolean
  hasQuestions: boolean
  hasGroups: boolean
  entries: ExportPassageEntry[]
  questionsByAttempt: Map<string, Record<string, unknown>[]>
  groupsByAttempt: Map<string, Record<string, unknown>[]>
}

const TARGET_FILES = new Set([
  'passages.jsonl',
  'attempts.jsonl',
  'questions.jsonl',
  'groups.jsonl',
])

const rawFiles = {
  passages: [] as Record<string, unknown>[],
  attempts: [] as Record<string, unknown>[],
  questions: [] as Record<string, unknown>[],
  groups: [] as Record<string, unknown>[],
  seen: new Set<string>(),
}

export const exportDataset = ref<LoadedExportDataset | null>(null)

function numOf(text: unknown): string {
  const m = String(text ?? '').match(/\d+/)
  return m ? m[0] : ''
}

export function derivePackIdClient(
  book: unknown,
  test: unknown,
  part: unknown,
  fallback = '',
): string {
  const b = numOf(book)
  const t = numOf(test)
  const p = numOf(part)
  if (b && t && p) return `cam${b}-t${t}-p${p}`
  const safe = fallback.replace(/[^a-zA-Z0-9._-]+/g, '-').replace(/^-+|-+$/g, '')
  return safe ? `reading-${safe}` : ''
}

function parseJsonl(content: string): Record<string, unknown>[] {
  const out: Record<string, unknown>[] = []
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line) continue
    const parsed = JSON.parse(line)
    if (parsed && typeof parsed === 'object') {
      out.push(parsed as Record<string, unknown>)
    }
  }
  return out
}

function rebuildDataset(): void {
  const questionsByAttempt = new Map<string, Record<string, unknown>[]>()
  for (const q of rawFiles.questions) {
    const aid = String(q.attempt_id ?? '')
    if (!aid) continue
    const list = questionsByAttempt.get(aid)
    if (list) list.push(q)
    else questionsByAttempt.set(aid, [q])
  }

  const groupsByAttempt = new Map<string, Record<string, unknown>[]>()
  for (const g of rawFiles.groups) {
    const aid = String(g.attempt_id ?? '')
    if (!aid) continue
    const list = groupsByAttempt.get(aid)
    if (list) list.push(g)
    else groupsByAttempt.set(aid, [g])
  }

  const attemptsByPassage = new Map<string, Record<string, unknown>[]>()
  for (const a of rawFiles.attempts) {
    if (a.module && a.module !== 'reading') continue
    const pid = String(a.passage_id ?? '')
    if (!pid) continue
    const list = attemptsByPassage.get(pid)
    if (list) list.push(a)
    else attemptsByPassage.set(pid, [a])
  }

  for (const list of attemptsByPassage.values()) {
    list.sort((x, y) => String(y.submitted_at ?? '').localeCompare(String(x.submitted_at ?? '')))
  }

  const entries: ExportPassageEntry[] = []
  for (const p of rawFiles.passages) {
    if (p.module && p.module !== 'reading') continue
    const pid = String(p.passage_id ?? '')
    const attempts = (attemptsByPassage.get(pid) ?? []).filter((a) =>
      questionsByAttempt.has(String(a.attempt_id ?? '')),
    )
    if (attempts.length === 0) continue

    const book = String(p.book ?? attempts[0]?.book ?? '')
    const test = String(p.test ?? attempts[0]?.test ?? '')
    const part = String(p.part ?? attempts[0]?.part ?? '')
    const title = String(p.title ?? attempts[0]?.title ?? pid)
    const derivedId = derivePackIdClient(book, test, part, String(p.part_id ?? pid))

    entries.push({
      key: pid || derivedId,
      derivedId,
      passageId: pid,
      book,
      test,
      part,
      title,
      passage: p,
      attempts,
    })
  }

  entries.sort((a, b) => {
    const ta = String(a.attempts[0]?.submitted_at ?? '')
    const tb = String(b.attempts[0]?.submitted_at ?? '')
    return tb.localeCompare(ta)
  })

  exportDataset.value = {
    passagesCount: rawFiles.passages.length,
    attemptsCount: rawFiles.attempts.length,
    questionsCount: rawFiles.questions.length,
    groupsCount: rawFiles.groups.length,
    hasPassages: rawFiles.seen.has('passages.jsonl'),
    hasAttempts: rawFiles.seen.has('attempts.jsonl'),
    hasQuestions: rawFiles.seen.has('questions.jsonl'),
    hasGroups: rawFiles.seen.has('groups.jsonl'),
    entries,
    questionsByAttempt,
    groupsByAttempt,
  }
}

export async function ingestExportFiles(fileList: FileList | File[]): Promise<number> {
  const files = Array.from(fileList).filter((f) => TARGET_FILES.has(f.name.toLowerCase()))
  if (files.length === 0) return 0

  for (const file of files) {
    const name = file.name.toLowerCase()
    const content = await file.text()
    const rows = parseJsonl(content)
    rawFiles.seen.add(name)
    if (name === 'passages.jsonl') rawFiles.passages = rows
    else if (name === 'attempts.jsonl') rawFiles.attempts = rows
    else if (name === 'questions.jsonl') rawFiles.questions = rows
    else if (name === 'groups.jsonl') rawFiles.groups = rows
  }

  rebuildDataset()
  return files.length
}
