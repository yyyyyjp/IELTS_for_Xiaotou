import type { ReviewGrade } from '../types'

const DAY = 86400
const RELEARN_SECONDS = 600
const MIN_EASE = 1.3
const MAX_EASE = 3.0
const MAX_INTERVAL = 365

export interface SrsCardInput {
  ease: number
  intervalDays: number
  reps: number
  lapses: number
}

export interface SrsCardNext {
  state: 'learning' | 'review'
  ease: number
  intervalDays: number
  reps: number
  lapses: number
  dueAt: number
  lastReviewedAt: number
}

export function reviewSrs(card: SrsCardInput, grade: ReviewGrade, nowSec: number): SrsCardNext {
  let ease = Number(card.ease || 2.4)
  let interval = Number(card.intervalDays || 0)
  const reps = Number(card.reps || 0) + 1
  let lapses = Number(card.lapses || 0)

  if (grade === 'again') {
    ease = Math.max(MIN_EASE, ease - 0.2)
    lapses += 1
    return {
      state: 'learning',
      ease: Math.round(ease * 1000) / 1000,
      intervalDays: 0,
      reps,
      lapses,
      dueAt: nowSec + RELEARN_SECONDS,
      lastReviewedAt: nowSec,
    }
  }

  if (grade === 'hard') {
    ease = Math.max(MIN_EASE, ease - 0.05)
    interval = Math.max(1, interval > 0 ? interval * 1.2 : 1)
  } else if (grade === 'good') {
    if (interval <= 0) interval = 1
    else if (interval < 2) interval = 3
    else interval = interval * ease
  } else {
    ease = Math.min(MAX_EASE, ease + 0.1)
    interval = interval <= 0 ? 3 : interval * ease * 1.3
  }

  interval = Math.min(MAX_INTERVAL, Math.round(interval * 100) / 100)
  return {
    state: 'review',
    ease: Math.round(ease * 1000) / 1000,
    intervalDays: interval,
    reps,
    lapses,
    dueAt: nowSec + Math.round(interval * DAY),
    lastReviewedAt: nowSec,
  }
}
