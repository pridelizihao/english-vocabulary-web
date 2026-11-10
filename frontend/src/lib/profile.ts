import type { ProfileDay } from '../api'

export const HEAT_LEVELS = 4

/** Bucket a day's answer count into the 4 heatmap levels. */
export function heatLevel(answers: number): 0 | 1 | 2 | 3 {
  if (answers <= 0) return 0
  if (answers < 10) return 1
  if (answers < 30) return 2
  return 3
}

export function dayLabel(iso: string) {
  return iso.slice(5).replace('-', '/')
}

export function recentDays(daily: ProfileDay[], count: number) {
  return daily.slice(-count)
}

export function maxAnswers(days: ProfileDay[]) {
  return days.reduce((max, day) => Math.max(max, day.answers), 0)
}

export function barPercent(value: number, max: number) {
  if (max <= 0) return 0
  return Math.min(100, Math.max(value > 0 ? 6 : 0, Math.round((value / max) * 100)))
}

export function hasActivity(day: ProfileDay) {
  return day.answers > 0
}
