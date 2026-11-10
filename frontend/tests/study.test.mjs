import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildClozeAnswer,
  buildQueue,
  checkCloze,
  clozeSlots,
  doneReason,
  formatDue,
  isClozeComplete,
  maskWordInExample,
  primaryMeaning,
  progressPercent,
  requeueAgain,
  revealCount,
  splitExample,
} from '../src/lib/study.ts'

const spellingOf = (slots) => slots.map((slot) => (slot.visible ? slot.char : '_')).join('')

test('cloze hides part of the word but never everything', () => {
  assert.equal(revealCount('abandon'), 2)
  assert.equal(spellingOf(clozeSlots('abandon')), 'ab_____')
  assert.equal(spellingOf(clozeSlots('go')), 'g_')
  assert.ok(clozeSlots('telecommunications').some((slot) => !slot.visible))
  assert.ok(clozeSlots('abandon').some((slot) => slot.visible))
})

test('non letter characters stay visible', () => {
  assert.equal(spellingOf(clozeSlots('ice cream')), 'ice _____')
  assert.equal(spellingOf(clozeSlots("don't")), "d__'_")
})

test('answers are prefilled only on visible positions', () => {
  const answer = buildClozeAnswer('abandon')
  assert.equal(answer.length, 7)
  assert.deepEqual(answer.slice(0, 2), ['a', 'b'])
  assert.deepEqual(answer.slice(2), ['', '', '', '', ''])
  assert.equal(isClozeComplete('abandon', answer), false)

  const filled = [...answer]
  filled[2] = 'a'
  filled[3] = 'n'
  filled[4] = 'd'
  filled[5] = 'o'
  filled[6] = 'n'
  assert.equal(isClozeComplete('abandon', filled), true)
  assert.equal(checkCloze('abandon', filled), true)

  const wrong = [...filled]
  wrong[5] = 'e'
  assert.equal(checkCloze('abandon', wrong), false)
})

test('cloze comparison ignores letter case', () => {
  const answer = buildClozeAnswer('Abandon')
  answer[2] = 'A'
  answer[3] = 'N'
  answer[4] = 'D'
  answer[5] = 'O'
  answer[6] = 'N'
  assert.equal(checkCloze('Abandon', answer), true)
})

test('a very short word has no blanks', () => {
  assert.equal(clozeSlots('a').every((slot) => slot.visible), true)
})

test('review words come before new words', () => {
  const word = { id: 1, spelling: 'x', preview: {} }
  const queue = buildQueue(
    [{ word: { ...word, id: 2 } }],
    [{ ...word, id: 3 }],
  )
  assert.deepEqual(queue.map((item) => item.kind), ['review', 'new'])
  assert.equal(queue[0].repeats, 0)
})

test('again requeues once at the end of the session', () => {
  const item = { word: { id: 1 }, kind: 'new', preview: {}, repeats: 0 }
  const queue = requeueAgain([item], item)
  assert.equal(queue.length, 2)
  assert.equal(queue[1].repeats, 1)
  const again = requeueAgain(queue, queue[1])
  assert.equal(again.length, 2)
})

test('done reason distinguishes empty, finished, daily limit and normal', () => {
  const base = { total_words: 10, remaining_new: 10, today_new: 0, new_limit: 20 }
  assert.equal(doneReason({ ...base, total_words: 0 }), 'no-words')
  assert.equal(doneReason({ ...base, remaining_new: 0 }), 'all-learned')
  assert.equal(doneReason({ ...base, remaining_new: 4, today_new: 20 }), 'daily-limit')
  assert.equal(doneReason({ ...base, remaining_new: 3497, today_new: 1 }), 'session-complete')
})

test('progress percent is clamped', () => {
  assert.equal(progressPercent(50, 200), 25)
  assert.equal(progressPercent(0, 0), 0)
  assert.equal(progressPercent(300, 200), 100)
})

test('formatDue describes the next review in human terms', () => {
  const now = new Date('2026-11-10T12:00:00+08:00')
  assert.equal(formatDue(null, now), '暂无安排')
  assert.equal(formatDue(new Date('2026-11-10T09:00:00+08:00').toISOString(), now), '已到期')
  assert.equal(formatDue(new Date('2026-11-10T20:00:00+08:00').toISOString(), now), '今天稍后')
  assert.equal(formatDue(new Date('2026-11-11T12:00:00+08:00').toISOString(), now), '明天')
  assert.equal(formatDue(new Date('2026-11-13T12:00:00+08:00').toISOString(), now), '3 天后')
  assert.equal(formatDue(new Date('2027-01-10T12:00:00+08:00').toISOString(), now), '2 个月后')
})

test('splitExample marks the target word and its inflections', () => {
  const parts = splitExample('He abandoned the plan in April.', 'abandon')
  const hits = parts.filter((part) => part.hit)
  assert.equal(hits.length, 1)
  assert.equal(hits[0].text, 'abandoned')
  assert.equal(parts.map((part) => part.text).join(''), 'He abandoned the plan in April.')
})

test('splitExample keeps text intact when the word is absent', () => {
  const parts = splitExample('Nothing to highlight here.', 'abandon')
  assert.deepEqual(parts, [{ text: 'Nothing to highlight here.', hit: false }])
})

test('splitExample matches plural, y-inflections and doubled consonants', () => {
  assert.equal(splitExample('She studies hard.', 'study').filter((part) => part.hit)[0].text, 'studies')
  assert.equal(splitExample('Two boxes arrived.', 'box').filter((part) => part.hit)[0].text, 'boxes')
  assert.equal(splitExample('It is running late.', 'run').filter((part) => part.hit)[0].text, 'running')
})

test('maskWordInExample hides the answer but keeps the context', () => {
  assert.equal(maskWordInExample('He abandoned the plan.', 'abandon'), 'He ____ the plan.')
  assert.equal(maskWordInExample('Abandon it now.', 'abandon'), '____ it now.')
  assert.equal(maskWordInExample('No match here.', 'abandon'), 'No match here.')
})

test('primaryMeaning keeps the leading senses and drops domain tags', () => {
  assert.equal(primaryMeaning('放弃, 抛弃, 遗弃, 使屈从; 放任, 无拘束'), '放弃，抛弃')
  assert.equal(primaryMeaning('爱滋病(获得性免疫缺陷综合征); 高级综合数据系统'), '爱滋病(获得性免疫缺陷综合征)')
  assert.equal(primaryMeaning('[计] 计算机; 电脑'), '计算机')
  assert.equal(primaryMeaning(''), '')
  assert.ok(primaryMeaning('a very long single sense without any punctuation '.repeat(2)).endsWith('…'))
})
