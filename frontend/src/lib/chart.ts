import type { CalibrationRow, ProgressPoint, RetentionBucket } from '../api'

export type Tone = 'good' | 'warn' | 'info'
export type Verdict = { tone: Tone; text: string }

export type Rect = { index: number; x: number; y: number; width: number; height: number; filled: boolean }
export type Point = { x: number; y: number }

/** 把最大值圆到 1 / 2 / 5 × 10^n，让坐标轴刻度是整数。 */
export function niceMax(value: number): number {
  if (!Number.isFinite(value) || value <= 0) return 1
  const exponent = Math.floor(Math.log10(value))
  const base = 10 ** exponent
  const fraction = value / base
  const pick = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10
  return pick * base
}

export function pct(rate: number | null): string {
  if (rate === null || !Number.isFinite(rate)) return '—'
  return `${Math.round(rate * 100)}%`
}

/**
 * 等宽柱子：`rates` 里 null 表示这一档没有样本，画成空心占位而不是 0%。
 * 坐标系原点在左上，`height` 是绘图区高度（已扣掉内边距）。
 */
export function barRects(rates: (number | null)[], width: number, height: number, gapRatio = 0.3): Rect[] {
  const count = rates.length
  if (!count || width <= 0 || height <= 0) return []
  const slot = width / count
  const barWidth = slot * (1 - gapRatio)
  return rates.map((rate, index) => {
    const filled = rate !== null && Number.isFinite(rate)
    const ratio = filled ? Math.min(Math.max(rate as number, 0), 1) : 0
    const barHeight = ratio * height
    return {
      index,
      x: index * slot + (slot - barWidth) / 2,
      y: height - barHeight,
      width: barWidth,
      height: barHeight,
      filled,
    }
  })
}

/** 折线用的点：x 均匀铺满宽度，y 按 value/max 反着算（0 在底部）。 */
export function linePoints(values: number[], width: number, height: number, max: number): Point[] {
  if (!values.length || width <= 0 || height <= 0) return []
  const top = max > 0 ? max : 1
  const step = values.length > 1 ? width / (values.length - 1) : 0
  return values.map((value, index) => ({
    x: values.length > 1 ? index * step : width / 2,
    y: height - (Math.min(Math.max(value, 0), top) / top) * height,
  }))
}

export function linePath(points: Point[]): string {
  if (!points.length) return ''
  return points
    .map((point, index) => `${index === 0 ? 'M' : 'L'}${round(point.x)} ${round(point.y)}`)
    .join(' ')
}

function round(value: number) {
  return Math.round(value * 100) / 100
}

/** 一年 371 个点塞进 640px 太密，按步长抽到 max 个以内（保留最后一个点）。 */
export function downsample<T>(items: T[], max: number): T[] {
  if (max <= 0 || items.length <= max) return items
  const step = items.length / max
  const picked: T[] = []
  for (let index = 0; index < max; index += 1) {
    picked.push(items[Math.min(items.length - 1, Math.floor(index * step))])
  }
  if (picked[picked.length - 1] !== items[items.length - 1]) picked.push(items[items.length - 1])
  return picked
}

export function lastOf(buckets: RetentionBucket[]): RetentionBucket | null {
  const usable = buckets.filter((bucket) => bucket.attempts > 0)
  return usable.length ? usable[usable.length - 1] : null
}

/** 哪一档开始掉到 70% 以下——就是「该复习了」的那个间隔。 */
export function firstWeakBucket(buckets: RetentionBucket[], threshold = 0.7, minSamples = 5): RetentionBucket | null {
  return (
    buckets.find(
      (bucket) => bucket.attempts >= minSamples && bucket.rate !== null && bucket.rate < threshold,
    ) ?? null
  )
}

export function retentionVerdict(buckets: RetentionBucket[]): Verdict {
  const usable = buckets.filter((bucket) => bucket.attempts >= 5 && bucket.rate !== null)
  if (!usable.length) {
    return { tone: 'info', text: '再复习几轮，这里会长出你自己的遗忘曲线。' }
  }
  const weak = firstWeakBucket(buckets)
  if (weak) {
    return {
      tone: 'warn',
      text: `隔 ${weak.label} 的回忆只剩 ${pct(weak.rate)}，这个间隔已经偏长，可以早点复习。`,
    }
  }
  const farthest = usable[usable.length - 1]
  return {
    tone: 'good',
    text: `每个间隔档的保持率都在 70% 以上，最长验证到 ${farthest.label}。`,
  }
}

export function ratingHint(row: CalibrationRow): string {
  if (!row.samples || row.forgotten_rate === null) return '还没有样本'
  if (row.samples < 8) return '样本还少'
  if (row.forgotten_rate >= 0.35) return '偏乐观'
  if (row.forgotten_rate <= 0.1 && row.rating !== 'again') return '偏保守'
  return '挺准'
}

export function calibrationVerdict(rows: CalibrationRow[], minSamples = 8): Verdict {
  const usable = rows.filter((row) => row.samples >= minSamples && row.forgotten_rate !== null)
  if (!usable.length) {
    return { tone: 'info', text: '样本还不够，多背几天就能看出自评准不准。' }
  }
  const optimistic = usable.filter((row) => (row.forgotten_rate as number) >= 0.3)
  if (optimistic.length) {
    const worst = optimistic.reduce((worst, row) =>
      (row.forgotten_rate as number) > (worst.forgotten_rate as number) ? row : worst,
    )
    return {
      tone: 'warn',
      text: `标「${worst.label}」之后，有 ${pct(worst.forgotten_rate)} 在下次又忘了——这一档点得偏乐观，可以往前挪一档。`,
    }
  }
  return { tone: 'good', text: '自评和下次实际表现对得上，评分尺度挺稳，保持现在的手感。' }
}

/** 进度曲线只关心「第一次有数据之后」：开头成片的全零日会把曲线压成贴地直线。 */
export function trimLeadingEmpty(points: ProgressPoint[]): ProgressPoint[] {
  const first = points.findIndex((point) => point.learned > 0 || point.mastered > 0)
  if (first === -1) return points.length ? [points[points.length - 1]] : []
  return points.slice(first)
}

/** 进度曲线的两条线共用一个纵轴，取两者最大值再圆整。 */
export function progressScale(points: ProgressPoint[]): number {
  const peak = points.reduce((max, point) => Math.max(max, point.learned, point.mastered), 0)
  return niceMax(peak)
}
