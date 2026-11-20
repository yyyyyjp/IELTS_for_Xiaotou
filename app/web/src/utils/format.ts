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
