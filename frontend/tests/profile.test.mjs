import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildHeatmap,
  dayLabel,
  heatLevel,
  maxAnswers,
  recentDays,
  WEEKDAY_LABELS,
} from '../src/lib/profile.ts'

const day = (date, answers = 0) => ({
  date,
  new: answers,
  review: 0,
  practice: 0,
  extra: 0,
  answers,
})

test('heatLevel maps activity to four buckets', () => {
  assert.equal(heatLevel(0), 0)
  assert.equal(heatLevel(1), 1)
  assert.equal(heatLevel(9), 1)
  assert.equal(heatLevel(10), 2)
  assert.equal(heatLevel(29), 2)
  assert.equal(heatLevel(30), 3)
  assert.equal(heatLevel(120), 3)
})

test('dayLabel turns an ISO date into a short label', () => {
  assert.equal(dayLabel('2026-11-10'), '11/10')
})

test('recentDays keeps the last N days', () => {
  const days = [day('2026-11-08', 1), day('2026-11-09', 2), day('2026-11-10', 3)]
  assert.deepEqual(recentDays(days, 2).map((item) => item.answers), [2, 3])
})

test('maxAnswers returns the busiest day', () => {
  assert.equal(maxAnswers([day('2026-11-08', 3), day('2026-11-09', 12), day('2026-11-10', 7)]), 12)
  assert.equal(maxAnswers([]), 0)
})

test('buildHeatmap pads the first week and fills column-major weeks', () => {
  const daily = ['04', '05', '06', '07', '08', '09', '10'].map((value) => day(`2026-11-${value}`, 1))
  const { columns, months } = buildHeatmap(daily)
  // 2026-11-04 is a Wednesday, so Monday/Tuesday of that week are padded
  assert.equal(columns[0][0], null)
  assert.equal(columns[0][1], null)
  assert.equal(columns[0][2].date, '2026-11-04')
  assert.equal(columns.length, 2)
  assert.equal(columns[1][0].date, '2026-11-09')
  assert.equal(columns[1][1].date, '2026-11-10')
  assert.equal(columns[1][6], null)
  assert.deepEqual(months, [{ label: '11月', index: 0 }])
})

test('buildHeatmap labels month changes', () => {
  const daily = []
  for (let index = 0; index < 31; index += 1) daily.push(day(`2026-10-${String(index + 1).padStart(2, '0')}`, 1))
  for (let index = 1; index <= 30; index += 1) daily.push(day(`2026-11-${String(index).padStart(2, '0')}`, 1))
  const { months } = buildHeatmap(daily)
  assert.deepEqual(months.map((month) => month.label), ['10月', '11月'])
  assert.ok(months[1].index > months[0].index)
})

test('buildHeatmap handles an empty range', () => {
  assert.deepEqual(buildHeatmap([]), { columns: [], months: [] })
})

test('weekday labels match the seven heatmap rows', () => {
  assert.equal(WEEKDAY_LABELS.length, 7)
  assert.equal(WEEKDAY_LABELS[0], '一')
  assert.equal(WEEKDAY_LABELS[6], '日')
})