import assert from 'node:assert/strict'
import test from 'node:test'

import { englishVoice, onlineSpeechUrl, sentenceAudioUrl } from '../src/lib/speech.ts'

test('englishVoice prefers a local English voice', () => {
  const voices = [
    { lang: 'zh-CN', name: 'Huihui', localService: true },
    { lang: 'en-US', name: 'Network', localService: false },
    { lang: 'en-GB', name: 'Zira', localService: true },
  ]
  assert.equal(englishVoice(voices)?.name, 'Zira')
})

test('englishVoice falls back to any English voice', () => {
  const voices = [
    { lang: 'zh-CN', name: 'Huihui', localService: true },
    { lang: 'en-US', name: 'Google US English', localService: false },
  ]
  assert.equal(englishVoice(voices)?.name, 'Google US English')
})

test('englishVoice ignores non-English voices', () => {
  assert.equal(englishVoice([{ lang: 'ja-JP', name: 'Kyoko', localService: true }]), undefined)
  assert.equal(englishVoice([]), undefined)
})

test('onlineSpeechUrl encodes the spelling', () => {
  assert.equal(onlineSpeechUrl('aboard'), 'https://dict.youdao.com/dictvoice?audio=aboard&type=2')
  assert.equal(
    onlineSpeechUrl(' take off '),
    'https://dict.youdao.com/dictvoice?audio=take%20off&type=2',
  )
  assert.equal(onlineSpeechUrl("don't"), "https://dict.youdao.com/dictvoice?audio=don't&type=2")
})

test('sentenceAudioUrl points at the cached server audio', () => {
  assert.equal(sentenceAudioUrl(42), '/api/words/42/example-audio')
})