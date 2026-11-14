import assert from 'node:assert/strict'
import test from 'node:test'

import {
  WORD_FILTERS,
  WORD_SORTS,
  buildWordsQuery,
  clampPage,
  formatMoment,
  isWordFilter,
  isWordSort,
  primaryPos,
  randomToken,
  statusLabel,
} from '../src/lib/words.ts'

test('buildWordsQuery omits defaults and encodes values', () => {
  assert.equal(buildWordsQuery({}), '')
  assert.equal(buildWordsQuery({ q: '  ', filter: 'all', sort: 'alpha', page: 1 }), '')
  assert.equal(buildWordsQuery({ q: ' abandon ' }), 'q=abandon')

  const full = buildWordsQuery({ q: '能力', filter: 'wrong', sort: 'due', page: 3 })
  assert.equal(full, 'q=%E8%83%BD%E5%8A%9B&filter=wrong&sort=due&page=3')

  const parsed = new URLSearchParams(full)
  assert.equal(parsed.get('q'), '能力')
  assert.equal(parsed.get('page'), '3')
})

test('clampPage keeps pages inside the valid range', () => {
  assert.equal(clampPage(1, 5), 1)
  assert.equal(clampPage(9, 5), 5)
  assert.equal(clampPage(0, 5), 1)
  assert.equal(clampPage(3.7, 5), 3)
  assert.equal(clampPage(Number.NaN, 5), 1)
  assert.equal(clampPage(4, 0), 1)
})

test('randomToken is url safe and unique enough', () => {
  const token = randomToken()
  assert.match(token, /^[a-z0-9]{32}$/)
  assert.match(randomToken(8), /^[a-z0-9]{8}$/)
  assert.equal(randomToken(2).length, 8)
  assert.notEqual(randomToken(), randomToken())
})

test('filter and sort metadata stay in sync with the guards', () => {
  assert.deepEqual(
    WORD_FILTERS.map((item) => item.value),
    ['all', 'new', 'learning', 'mastered', 'due', 'wrong'],
  )
  assert.deepEqual(
    WORD_SORTS.map((item) => item.value),
    ['alpha', 'recent', 'due', 'wrong'],
  )
  assert.ok(WORD_FILTERS.every((item) => item.label.length > 0))
  assert.ok(WORD_SORTS.every((item) => item.label.length > 0))

  assert.equal(isWordFilter('wrong'), true)
  assert.equal(isWordFilter('bogus'), false)
  assert.equal(isWordFilter(null), false)
  assert.equal(isWordSort('recent'), true)
  assert.equal(isWordSort('bogus'), false)
})

test('primaryPos keeps only the first tag', () => {
  assert.equal(primaryPos('n.;[计];其它'), 'n.')
  assert.equal(primaryPos('vt. ; n.'), 'vt.')
  assert.equal(primaryPos(''), '')
})

test('statusLabel falls back to unlearned', () => {
  assert.equal(statusLabel('mastered'), '已掌握')
  assert.equal(statusLabel('learning'), '学习中')
  assert.equal(statusLabel('retired'), '已归档')
  assert.equal(statusLabel('new'), '未学')
  assert.equal(statusLabel('unknown'), '未学')
})

test('formatMoment renders a short local timestamp', () => {
  assert.equal(formatMoment(new Date(2026, 0, 2, 3, 4, 5).toISOString()), '01-02 03:04')
  assert.equal(formatMoment('not-a-date'), '')
})
