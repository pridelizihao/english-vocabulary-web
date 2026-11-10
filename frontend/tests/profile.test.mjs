import assert from 'node:assert/strict'
import test from 'node:test'

import { barPercent, dayLabel, heatLevel, maxAnswers, recentDays } from '../src/lib/profile.ts'

const day = (answers, extra = {}) => ({
  date: '2026-11-10',
  new: 0,
  review: 0,
  practice: 0,
  extra: 0,
  answers,
  ...extra,
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
  const days = [day(1), day(2), day(3)]
  assert.deepEqual(recentDays(days, 2).map((item) => item.answers), [2, 3])
})

test('maxAnswers returns the busiest day', () => {
  assert.equal(maxAnswers([day(3), day(12), day(7)]), 12)
  assert.equal(maxAnswers([]), 0)
})

test('barPercent keeps small values visible and clamps to 100', () => {
  assert.equal(barPercent(0, 40), 0)
  assert.equal(barPercent(1, 40), 6)
  assert.equal(barPercent(20, 40), 50)
  assert.equal(barPercent(80, 40), 100)
  assert.equal(barPercent(5, 0), 0)
})
