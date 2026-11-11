import assert from 'node:assert/strict'
import test from 'node:test'

import {
  barRects,
  calibrationVerdict,
  downsample,
  firstWeakBucket,
  linePath,
  linePoints,
  niceMax,
  pct,
  progressScale,
  ratingHint,
  retentionVerdict,
  trimLeadingEmpty,
} from '../src/lib/chart.ts'

const bucket = (label, attempts, rate) => ({
  label,
  low: 1,
  high: null,
  attempts,
  kept: rate === null ? 0 : Math.round(attempts * rate),
  rate,
})

const calibrationRow = (rating, label, samples, forgottenRate) => ({
  rating,
  label,
  samples,
  forgotten: Math.round(samples * (forgottenRate ?? 0)),
  forgotten_rate: forgottenRate,
})

test('niceMax rounds up to a readable axis maximum', () => {
  assert.equal(niceMax(0), 1)
  assert.equal(niceMax(-5), 1)
  assert.equal(niceMax(7), 10)
  assert.equal(niceMax(12), 20)
  assert.equal(niceMax(130), 200)
  assert.equal(niceMax(350), 500)
  assert.equal(niceMax(1000), 1000)
})

test('pct renders a percentage or an em dash', () => {
  assert.equal(pct(0.5), '50%')
  assert.equal(pct(0.666), '67%')
  assert.equal(pct(1), '100%')
  assert.equal(pct(null), '—')
})

test('barRects keeps bars inside the plot and blanks empty buckets', () => {
  const rects = barRects([1, 0.5, null, 0], 400, 100)
  assert.equal(rects.length, 4)
  assert.equal(rects[0].height, 100)
  assert.equal(rects[0].y, 0)
  assert.equal(rects[1].height, 50)
  assert.equal(rects[1].y, 50)
  assert.equal(rects[2].filled, false)
  assert.equal(rects[2].height, 0)
  assert.equal(rects[3].filled, true)
  assert.equal(rects[3].height, 0)
  // 同一档里柱子等宽、互不重叠。
  assert.ok(rects[0].width < 100)
  assert.ok(rects[1].x >= rects[0].x + rects[0].width)
})

test('barRects tolerates empty input', () => {
  assert.deepEqual(barRects([], 400, 100), [])
  assert.deepEqual(barRects([0.3], 0, 100), [])
})

test('linePoints puts zero at the bottom and max at the top', () => {
  const points = linePoints([0, 50, 100], 200, 100, 100)
  assert.equal(points.length, 3)
  assert.equal(points[0].y, 100)
  assert.equal(points[1].y, 50)
  assert.equal(points[2].y, 0)
  assert.equal(points[0].x, 0)
  assert.equal(points[2].x, 200)
})

test('linePoints clamps values above the axis maximum', () => {
  const points = linePoints([250], 100, 100, 100)
  assert.equal(points[0].y, 0)
})

test('linePath builds a move-then-line path', () => {
  assert.equal(linePath([]), '')
  assert.equal(
    linePath([
      { x: 0, y: 10 },
      { x: 5, y: 20.126 },
    ]),
    'M0 10 L5 20.13',
  )
})

test('downsample thins a long series and keeps the last point', () => {
  const series = Array.from({ length: 371 }, (_, index) => index)
  const thinned = downsample(series, 80)
  assert.ok(thinned.length <= 81)
  assert.equal(thinned[0], 0)
  assert.equal(thinned[thinned.length - 1], 370)
  assert.deepEqual(downsample([1, 2, 3], 10), [1, 2, 3])
})

test('firstWeakBucket finds where retention drops under 70%', () => {
  const buckets = [
    bucket('1 天', 30, 0.95),
    bucket('2–3 天', 20, 0.8),
    bucket('4–7 天', 12, 0.55),
    bucket('8–14 天', 3, 0.2),
  ]
  assert.equal(firstWeakBucket(buckets).label, '4–7 天')
  // 样本不足的档位不当真。
  assert.equal(firstWeakBucket([bucket('1 天', 30, 0.9), bucket('8–14 天', 2, 0.1)]), null)
})

test('retentionVerdict explains the curve in plain Chinese', () => {
  assert.equal(retentionVerdict([]).tone, 'info')
  assert.equal(retentionVerdict([bucket('1 天', 3, 0.9)]).tone, 'info')

  const weak = retentionVerdict([
    bucket('1 天', 40, 0.95),
    bucket('8–14 天', 10, 0.4),
  ])
  assert.equal(weak.tone, 'warn')
  assert.match(weak.text, /8–14 天/)
  assert.match(weak.text, /40%/)

  const healthy = retentionVerdict([bucket('1 天', 40, 0.95), bucket('4–7 天', 10, 0.9)])
  assert.equal(healthy.tone, 'good')
  assert.match(healthy.text, /70%/)
})

test('ratingHint labels each rating scale', () => {
  assert.equal(ratingHint(calibrationRow('easy', '很熟', 0, null)), '还没有样本')
  assert.equal(ratingHint(calibrationRow('easy', '很熟', 3, 0.5)), '样本还少')
  assert.equal(ratingHint(calibrationRow('easy', '很熟', 20, 0.4)), '偏乐观')
  assert.equal(ratingHint(calibrationRow('good', '记住了', 20, 0.05)), '偏保守')
  assert.equal(ratingHint(calibrationRow('good', '记住了', 20, 0.2)), '挺准')
  assert.equal(ratingHint(calibrationRow('again', '忘记了', 20, 0.02)), '挺准')
})

test('calibrationVerdict calls out an optimistic self rating', () => {
  assert.equal(calibrationVerdict([]).tone, 'info')
  assert.equal(
    calibrationVerdict([calibrationRow('easy', '很熟', 3, 0.9)]).tone,
    'info',
  )

  const optimistic = calibrationVerdict([
    calibrationRow('easy', '很熟', 25, 0.42),
    calibrationRow('good', '记住了', 40, 0.15),
  ])
  assert.equal(optimistic.tone, 'warn')
  assert.match(optimistic.text, /很熟/)
  assert.match(optimistic.text, /42%/)

  const steady = calibrationVerdict([
    calibrationRow('easy', '很熟', 25, 0.1),
    calibrationRow('good', '记住了', 40, 0.15),
  ])
  assert.equal(steady.tone, 'good')
})

test('progressScale shares one axis for both lines', () => {
  assert.equal(progressScale([]), 1)
  assert.equal(progressScale([{ date: '2026-01-01', learned: 30, mastered: 4 }]), 50)
  assert.equal(progressScale([{ date: '2026-01-01', learned: 800, mastered: 12 }]), 1000)
})

test('trimLeadingEmpty drops the flat run before the first lesson', () => {
  const points = [
    { date: '2026-05-16', learned: 0, mastered: 0 },
    { date: '2026-06-01', learned: 0, mastered: 0 },
    { date: '2026-11-01', learned: 3, mastered: 0 },
    { date: '2026-11-11', learned: 80, mastered: 4 },
  ]
  const trimmed = trimLeadingEmpty(points)
  assert.equal(trimmed.length, 2)
  assert.equal(trimmed[0].date, '2026-11-01')
  // 一点数据都没有时保留最后一个点，避免空数组把图例算崩。
  assert.deepEqual(trimLeadingEmpty([points[0], points[1]]).map((p) => p.date), ['2026-06-01'])
  assert.deepEqual(trimLeadingEmpty([]), [])
})
