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

export type HeatmapColumn = (ProfileDay | null)[]
export type HeatmapMonth = { label: string; index: number }
export type Heatmap = { columns: HeatmapColumn[]; months: HeatmapMonth[] }

function toDate(iso: string) {
  const [year, month, day] = iso.split('-').map(Number)
  return new Date(year, month - 1, day)
}

function toIso(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

/**
 * Turn the daily series into GitHub-style columns: one column per week,
 * Monday first, with nulls for days outside the requested range.
 */
export function buildHeatmap(daily: ProfileDay[]): Heatmap {
  if (!daily.length) return { columns: [], months: [] }
  const byDate = new Map(daily.map((day) => [day.date, day]))
  const first = toDate(daily[0].date)
  const last = toDate(daily[daily.length - 1].date)

  const start = new Date(first)
  const offset = (start.getDay() + 6) % 7
  start.setDate(start.getDate() - offset)

  const columns: HeatmapColumn[] = []
  const months: HeatmapMonth[] = []
  let lastMonth = -1
  let lastLabelIndex = -10
  const cursor = new Date(start)

  while (cursor <= last) {
    const column: HeatmapColumn = []
    let month = -1
    for (let index = 0; index < 7; index += 1) {
      const day = byDate.get(toIso(cursor)) ?? null
      if (day && month === -1) month = cursor.getMonth()
      column.push(day)
      cursor.setDate(cursor.getDate() + 1)
    }
    const columnIndex = columns.length
    if (month !== -1 && month !== lastMonth && columnIndex - lastLabelIndex >= 3) {
      months.push({ label: `${month + 1}月`, index: columnIndex })
      lastMonth = month
      lastLabelIndex = columnIndex
    }
    columns.push(column)
  }

  return { columns, months }
}

export const WEEKDAY_LABELS = ['一', '', '三', '', '五', '', '日']

/**
 * 热力图浮层的位置：把提示框夹在视口内。
 * 桌面上鼠标在格子里，浮层飘出右边缘无所谓；手机上点最右/最下那一列时，
 * 浮层会直接跑到屏幕外，所以统一先夹一次。
 */
export function tooltipPlacement(
  x: number,
  y: number,
  viewportWidth: number,
  viewportHeight: number,
  boxWidth = 152,
  boxHeight = 84,
) {
  const margin = 8
  return {
    left: clamp(x, margin, Math.max(margin, viewportWidth - boxWidth - margin)),
    top: clamp(y, margin, Math.max(margin, viewportHeight - boxHeight - margin)),
  }
}

function clamp(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min
  return Math.min(Math.max(value, min), max)
}
