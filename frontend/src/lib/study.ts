import type { Progress, Rating, RatingPreview, Word } from '../api'

export const RATINGS: Rating[] = ['again', 'hard', 'good', 'easy']

export const RATING_META: Record<Rating, { label: string; fallbackHint: string; className: string }> = {
  again: { label: '忘记了', fallbackHint: '10 分钟后', className: 'rate-again' },
  hard: { label: '模糊', fallbackHint: '明天', className: 'rate-hard' },
  good: { label: '记住了', fallbackHint: '按计划', className: 'rate-good' },
  easy: { label: '很熟', fallbackHint: '加倍', className: 'rate-easy' },
}

/** Positions that are never hidden in the cloze exercise (spaces, hyphens...). */
const ALWAYS_VISIBLE = /[^A-Za-z0-9]/

export function revealCount(spelling: string) {
  return Math.max(1, Math.floor(spelling.length / 3))
}

export type ClozeSlot = { index: number; char: string; visible: boolean }

export function clozeSlots(spelling: string): ClozeSlot[] {
  const count = revealCount(spelling)
  return Array.from(spelling).map((char, index) => ({
    index,
    char,
    visible: index < count || ALWAYS_VISIBLE.test(char),
  }))
}

/** Prefilled answer array: visible letters are already filled in. */
export function buildClozeAnswer(spelling: string): string[] {
  return clozeSlots(spelling).map((slot) => (slot.visible ? slot.char : ''))
}

export function isClozeComplete(spelling: string, answer: string[]) {
  const slots = clozeSlots(spelling)
  if (answer.length !== slots.length) return false
  return slots.every((slot) => slot.visible || (answer[slot.index] ?? '').trim().length > 0)
}

export function checkCloze(spelling: string, answer: string[]) {
  const slots = clozeSlots(spelling)
  if (answer.length !== slots.length) return false
  return slots.every((slot) => (answer[slot.index] ?? '').toLowerCase() === slot.char.toLowerCase())
}

export type StudyKind = 'new' | 'review'

export type StudyItem = {
  word: Word
  kind: StudyKind
  preview: RatingPreview
  repeats: number
}

export function buildQueue(review: Progress[], fresh: Word[]): StudyItem[] {
  return [
    ...review.map((progress) => ({
      word: progress.word,
      kind: 'review' as const,
      preview: progress.word.preview,
      repeats: 0,
    })),
    ...fresh.map((word) => ({
      word,
      kind: 'new' as const,
      preview: word.preview,
      repeats: 0,
    })),
  ]
}

/** "again" gets one extra pass at the end of the current session. */
export function requeueAgain(queue: StudyItem[], item: StudyItem, maxRepeats = 1): StudyItem[] {
  if (item.repeats >= maxRepeats) return queue
  return [...queue, { ...item, repeats: item.repeats + 1 }]
}

export type EmptyReason = 'no-words' | 'all-learned' | 'daily-limit'

export function emptyReason(stats: {
  total_words: number
  remaining_new: number
  today_new: number
  new_limit: number
}): EmptyReason {
  if (stats.total_words === 0) return 'no-words'
  if (stats.remaining_new <= 0) return 'all-learned'
  if (stats.today_new >= stats.new_limit) return 'daily-limit'
  return 'all-learned'
}

export function rateHint(preview: RatingPreview | undefined, rating: Rating) {
  return preview?.[rating] || RATING_META[rating].fallbackHint
}

export function progressPercent(learned: number, total: number) {
  if (!total) return 0
  return Math.min(100, Math.round((learned / total) * 100))
}

export function formatDue(iso: string | null | undefined, now: Date = new Date()) {
  if (!iso) return '暂无安排'
  const target = new Date(iso)
  if (Number.isNaN(target.getTime())) return '暂无安排'
  const diff = target.getTime() - now.getTime()
  if (diff <= 0) return '已到期'
  const days = Math.round(diff / 86_400_000)
  if (days <= 0) return '今天稍后'
  if (days === 1) return '明天'
  if (days < 30) return `${days} 天后`
  return `${Math.round(days / 30)} 个月后`
}

export function greeting(date: Date = new Date()) {
  const hour = date.getHours()
  if (hour < 6) return '夜深了'
  if (hour < 11) return '早上好'
  if (hour < 14) return '中午好'
  if (hour < 18) return '下午好'
  return '晚上好'
}
