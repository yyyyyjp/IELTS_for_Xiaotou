import { lang } from '../i18n'

const locale = () => (lang.value === 'zh' ? 'zh-CN' : 'en-GB')

export function dateOf(day: string): Date {
  return new Date(`${day}T00:00:00`)
}

export function fmtDayLong(ts = Date.now() / 1000): string {
  return new Intl.DateTimeFormat(locale(), {
    month: 'long',
    day: 'numeric',
    weekday: 'short',
  }).format(new Date(ts * 1000))
}

export function fmtShort(ts: number): string {
  return new Intl.DateTimeFormat(locale(), { month: 'short', day: 'numeric' }).format(
    new Date(ts * 1000),
  )
}

export function fmtMonthDay(day: string): string {
  return new Intl.DateTimeFormat(locale(), { month: 'short', day: 'numeric' }).format(dateOf(day))
}

export function pct(value: number): string {
  return `${Math.round(value * 100)}%`
}

export function fmtDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds))
  const minutes = Math.floor(total / 60)
  const rest = total % 60
  return `${minutes}:${String(rest).padStart(2, '0')}`
}

function shortenBookToken(raw: string): string {
  const s = raw.trim()
  if (!s) return ''
  const cam = /^(?:Cambridge(?:\s+IELTS)?|Cam|剑桥(?:雅思)?|剑雅|剑)\s*(\d+)$/i.exec(s)
  if (cam) return `C${cam[1]}`
  return s
}

function shortenTestToken(raw: string): string {
  const s = raw.trim()
  if (!s) return ''
  const m = /^(?:Test|T)\s*(\d+)$/i.exec(s)
  if (m) return `T${m[1]}`
  return s
}

function shortenPassageToken(raw: string): string {
  const s = raw.trim()
  if (!s) return ''
  const m = /^(?:Reading\s*)?(?:Passage|Section|Part|P)\s*(\d+)$/i.exec(s)
  if (m) return `P${m[1]}`
  return s
}

/**
 * 动态生成篇目前缀编号，不写死剑雅格式：
 * - 剑桥雅思 18 / Test 4 / Passage 3 -> C18-T4-P3
 * - 机经 / 真题 / 自定义来源 -> 原样保留并拼接（如 2026机经-P2）
 */
export function formatPackCode(meta: {
  book?: string
  test?: string
  passage?: string
  source?: string
}): string {
  const parts = [
    shortenBookToken(meta.book ?? ''),
    shortenTestToken(meta.test ?? ''),
    shortenPassageToken(meta.passage ?? ''),
  ].filter(Boolean)
  if (parts.length) return parts.join('-')
  return (meta.source ?? '').trim()
}

export function formatPackOption(pack: {
  meta: { book?: string; test?: string; passage?: string; source?: string; title: string }
}): string {
  const code = formatPackCode(pack.meta)
  return code ? `${code} · ${pack.meta.title}` : pack.meta.title
}
