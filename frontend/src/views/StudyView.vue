<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { Rating } from '../api'
import { useSpeech } from '../composables/useSpeech'
import {
  RATINGS,
  RATING_META,
  buildClozeAnswer,
  checkCloze,
  clozeSlots,
  isClozeComplete,
  maskWordInExample,
  primaryMeaning,
  rateHint,
  splitExample,
  type StudyItem,
} from '../lib/study'

const props = defineProps<{
  item: StudyItem
  index: number
  total: number
  mode: 'card' | 'cloze'
  loading: boolean
  dictionaryName: string
  newLearnedToday: number
  newLimit: number
  dueReviews: number
  canUndo: boolean
}>()

const emit = defineEmits<{
  (event: 'rate', rating: Rating): void
  (event: 'back'): void
  (event: 'undo'): void
  (event: 'update:mode', mode: 'card' | 'cloze'): void
}>()

const revealed = ref(false)
const answer = ref<string[]>([])
const result = ref<'correct' | 'wrong' | null>(null)
const shaking = ref(false)
const attempts = ref(0)
const { speak: speakWord, stop: stopSpeech, message: speechMessage } = useSpeech()
const hintVisible = ref(false)
const fullMeaningVisible = ref(false)
const clozeBox = ref<HTMLElement | null>(null)

const word = computed(() => props.item.word)
const slots = computed(() => clozeSlots(word.value.spelling))
const noBlanks = computed(() => slots.value.every((slot) => slot.visible))
const complete = computed(() => isClozeComplete(word.value.spelling, answer.value))
const exampleParts = computed(() => splitExample(word.value.example, word.value.spelling))
const maskedExample = computed(() => maskWordInExample(word.value.example, word.value.spelling))
const shortMeaning = computed(() => primaryMeaning(word.value.meaning))
const kindLabel = computed(() => ({ new: '新词', review: '复习', practice: '练习' }[props.item.kind]))
const hasMoreMeaning = computed(() => shortMeaning.value !== word.value.meaning.trim())
const progress = computed(() => (props.total ? Math.round((props.index / props.total) * 100) : 0))


function reset() {
  stopSpeech()
  revealed.value = false
  result.value = null
  shaking.value = false
  attempts.value = 0
  speechMessage.value = ''
  hintVisible.value = false
  fullMeaningVisible.value = false
  answer.value = buildClozeAnswer(word.value.spelling)
  focusFirstEmpty()
}

watch(() => props.item, reset, { immediate: true })
watch(() => props.mode, reset)

function focusSlot(slotIndex: number) {
  nextTick(() => {
    const element = clozeBox.value?.querySelector<HTMLInputElement>(`input[data-index="${slotIndex}"]`)
    element?.focus()
  })
}

function focusFirstEmpty() {
  const first = slots.value.find((slot) => !slot.visible)
  if (first) focusSlot(first.index)
}

function focusNextHidden(after: number) {
  const next = slots.value.find((slot) => !slot.visible && slot.index > after)
  if (next) focusSlot(next.index)
}

function focusPreviousHidden(before: number) {
  const previous = [...slots.value].reverse().find((slot) => !slot.visible && slot.index < before)
  if (previous) focusSlot(previous.index)
}

function onInput(slotIndex: number, event: Event) {
  const input = event.target as HTMLInputElement
  const value = input.value.slice(-1)
  answer.value[slotIndex] = value
  input.value = value
  result.value = null
  if (value) focusNextHidden(slotIndex)
}

function onSlotKeydown(slotIndex: number, event: KeyboardEvent) {
  if (event.key === 'Backspace') {
    // Backspace removes the current letter; on an empty slot it clears the
    // previous one instead of leaving the caret stuck there.
    if (answer.value[slotIndex]) return
    event.preventDefault()
    const previous = [...slots.value].reverse().find((slot) => !slot.visible && slot.index < slotIndex)
    if (previous) {
      answer.value[previous.index] = ''
      focusSlot(previous.index)
    }
    return
  }
  if (event.key === 'ArrowLeft') {
    event.preventDefault()
    focusPreviousHidden(slotIndex)
    return
  }
  if (event.key === 'ArrowRight') {
    event.preventDefault()
    focusNextHidden(slotIndex)
  }
}

function submitCloze() {
  if (!complete.value || props.loading) return
  if (checkCloze(word.value.spelling, answer.value)) {
    result.value = 'correct'
    return
  }
  attempts.value += 1
  shaking.value = true
  window.setTimeout(() => {
    shaking.value = false
  }, 500)
  // First miss: keep the answer hidden and let the learner think again.
  result.value = attempts.value >= 2 ? 'wrong' : 'retry'
}

function revealAnswer() {
  attempts.value = Math.max(attempts.value, 2)
  answer.value = Array.from(word.value.spelling)
  result.value = 'wrong'
}

function editAgain() {
  result.value = null
  focusFirstEmpty()
}

function restartAttempt() {
  attempts.value = 0
  result.value = null
  answer.value = buildClozeAnswer(word.value.spelling)
  focusFirstEmpty()
}

function primaryAction() {
  if (props.mode === 'card') {
    if (!revealed.value) revealed.value = true
    return
  }
  if (result.value === 'correct') {
    emitRate('good')
    return
  }
  if (result.value === 'wrong') {
    restartAttempt()
    return
  }
  submitCloze()
}

function emitRate(rating: Rating) {
  if (props.loading) return
  emit('rate', rating)
}

// 朗读顺序：词典自带音频 → 系统英文语音 → 在线发音（有道），见 useSpeech。
function speak() {
  speakWord(word.value.spelling, [word.value.audio_url, word.value.pronunciation_url])
}

function onWindowKeydown(event: KeyboardEvent) {
  if (props.loading) return
  if (event.key === 'Escape' && props.mode === 'cloze' && result.value !== 'correct') {
    event.preventDefault()
    revealAnswer()
    return
  }
  const target = event.target as HTMLElement | null
  const typing = Boolean(
    target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable),
  )
  if (typing) {
    if (event.key === 'Enter' && props.mode === 'cloze') {
      event.preventDefault()
      primaryAction()
    }
    return
  }
  if (props.canUndo && (event.key === 'u' || event.key === 'U' || (event.ctrlKey && event.key === 'z'))) {
    event.preventDefault()
    emit('undo')
    return
  }
  // Let Enter/Space on a focused button behave like a normal click.
  if (target?.tagName === 'BUTTON') return
  if (props.mode === 'card') {
    if (!revealed.value && (event.key === ' ' || event.key === 'Enter')) {
      event.preventDefault()
      revealed.value = true
      return
    }
    if (revealed.value) {
      const position = ['1', '2', '3', '4'].indexOf(event.key)
      if (position >= 0) {
        event.preventDefault()
        emitRate(RATINGS[position])
      }
    }
    return
  }
  if (event.key === 'Enter') {
    event.preventDefault()
    primaryAction()
  }
}

onMounted(() => {
  window.addEventListener('keydown', onWindowKeydown)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onWindowKeydown)
  stopSpeech()
})
</script>

<template>
  <section class="content-section study-section">
    <div class="study-heading">
      <div class="study-heading-main">
        <button class="link-button back" @click="emit('back')">← {{ dictionaryName }}</button>
        <p class="eyebrow">
          <span class="kind-badge" :class="item.kind">{{ kindLabel }}</span>
          今日新词 {{ newLearnedToday }}/{{ newLimit }}
          <template v-if="dueReviews"> · 待复习 {{ dueReviews }}</template>
        </p>
      </div>
      <div class="study-tools">
        <div class="mode-switch" role="group" aria-label="练习模式">
          <button
            :class="{ active: mode === 'card' }"
            :aria-pressed="mode === 'card'"
            @click="emit('update:mode', 'card')"
          >
            卡片
          </button>
          <button
            :class="{ active: mode === 'cloze' }"
            :aria-pressed="mode === 'cloze'"
            @click="emit('update:mode', 'cloze')"
          >
            填空
          </button>
        </div>
        <button v-if="canUndo" class="link-button undo-button" :disabled="loading" @click="emit('undo')">
          撤销上一题 <kbd>U</kbd>
        </button>
        <span class="counter">{{ index + 1 }} / {{ total }}</span>
      </div>
    </div>

    <div class="bar study-bar" aria-hidden="true">
      <span :style="{ width: `${progress}%` }"></span>
    </div>

    <section v-if="mode === 'card'" class="card">
      <div class="word-row">
        <h3 :class="{ long: word.spelling.length > 10 }">{{ word.spelling }}</h3>
        <button class="speak-button" title="朗读单词" aria-label="朗读单词" @click="speak">🔊 朗读</button>
      </div>
      <p class="phonetic">
        {{ word.phonetic || '暂无音标' }}
        <span v-if="word.part_of_speech" class="pos">{{ word.part_of_speech }}</span>
      </p>
      <p v-if="speechMessage" class="speech-hint">{{ speechMessage }}</p>

      <button v-if="!revealed" class="primary wide reveal-button" :disabled="loading" @click="revealed = true">
        显示答案 <kbd>空格</kbd>
      </button>

      <div v-else class="answer">
        <strong>{{ shortMeaning }}</strong>
        <button v-if="hasMoreMeaning" class="link-button meaning-toggle" @click="fullMeaningVisible = !fullMeaningVisible">
          {{ fullMeaningVisible ? '收起完整释义' : '完整释义' }}
        </button>
        <p v-if="fullMeaningVisible" class="meaning-full">{{ word.meaning }}</p>
        <p v-if="word.example" class="example">
          <span v-for="(part, partIndex) in exampleParts" :key="partIndex" :class="{ hit: part.hit }">{{ part.text }}</span>
        </p>
        <p v-if="word.example_translation" class="example-translation">{{ word.example_translation }}</p>
        <div class="ratings">
          <button
            v-for="(rating, position) in RATINGS"
            :key="rating"
            class="rate-button"
            :class="RATING_META[rating].className"
            :disabled="loading"
            @click="emitRate(rating)"
          >
            <span class="rate-label">{{ RATING_META[rating].label }}</span>
            <span class="rate-hint">{{ item.kind === 'practice' ? '仅记录' : rateHint(item.preview, rating) }}</span>
            <kbd>{{ position + 1 }}</kbd>
          </button>
        </div>
      </div>
    </section>

    <section v-else class="card cloze-card">
      <p class="cloze-label">根据中文释义补全单词</p>
      <p class="meaning-hint">{{ shortMeaning }}</p>
      <div ref="clozeBox" class="cloze-word" :class="{ shake: shaking }">
        <template v-for="slot in slots" :key="slot.index">
          <span v-if="slot.visible" class="cloze-fixed">{{ slot.char }}</span>
          <input
            v-else
            :data-index="slot.index"
            :value="answer[slot.index]"
            maxlength="1"
            autocomplete="off"
            autocapitalize="none"
            spellcheck="false"
            @input="onInput(slot.index, $event)"
            @keydown="onSlotKeydown(slot.index, $event)"
          />
        </template>
      </div>
      <p v-if="word.phonetic" class="phonetic">{{ word.phonetic }}</p>
      <button class="speak-button" title="朗读单词" aria-label="朗读单词" @click="speak">🔊 朗读</button>
      <p v-if="speechMessage" class="speech-hint">{{ speechMessage }}</p>

      <div v-if="word.example" class="cloze-hint">
        <button class="link-button" @click="hintVisible = !hintVisible">
          {{ hintVisible ? '收起例句提示' : '例句提示' }}
        </button>
        <template v-if="hintVisible">
          <p class="example">{{ maskedExample }}</p>
          <p v-if="word.example_translation" class="example-translation">{{ word.example_translation }}</p>
        </template>
      </div>

      <p v-if="noBlanks" class="muted">这个词太短，没有需要填的空，直接继续即可。</p>

      <div v-if="!result" class="cloze-actions">
        <button class="primary" :disabled="(!complete && !noBlanks) || loading" @click="noBlanks ? emitRate('good') : submitCloze()">
          {{ noBlanks ? '继续' : '检查答案' }} <kbd>回车</kbd>
        </button>
        <button v-if="!noBlanks" class="link-button" @click="revealAnswer">不会，看答案 <kbd>Esc</kbd></button>
      </div>

      <div v-else-if="result === 'correct'" class="cloze-result">
        <strong class="correct">回答正确</strong>
        <p v-if="item.kind === 'practice'">练习已记录，不改变复习间隔</p>
        <p v-else>下次复习：{{ item.preview?.good || '按计划' }}</p>
        <button class="primary" :disabled="loading" @click="emitRate('good')">继续 <kbd>回车</kbd></button>
      </div>

      <div v-else-if="result === 'retry'" class="cloze-result">
        <strong class="wrong">还不对</strong>
        <p>还有一次机会，再想想；实在想不起来就按 Esc 看答案。</p>
        <div class="cloze-actions">
          <button class="primary" :disabled="loading" @click="editAgain">继续填 <kbd>回车</kbd></button>
          <button :disabled="loading" @click="revealAnswer">看答案 <kbd>Esc</kbd></button>
        </div>
      </div>

      <div v-else class="cloze-result">
        <strong class="wrong">正确答案</strong>
        <p class="cloze-answer">{{ word.spelling }}</p>
        <div class="cloze-actions">
          <button class="primary" :disabled="loading" @click="restartAttempt">再试一次</button>
          <button :disabled="loading" @click="emitRate('hard')">记为模糊</button>
        </div>
      </div>
    </section>

    <p v-if="mode === 'card'" class="keyboard-hint muted">
      快捷键：<kbd>空格</kbd> 看答案 · <kbd>1</kbd>–<kbd>4</kbd> 评分 · <kbd>U</kbd> 撤销 · <kbd>回车</kbd> 确认
    </p>
    <p v-else class="keyboard-hint muted">
      快捷键：<kbd>回车</kbd> 检查 · <kbd>Esc</kbd> 看答案 · <kbd>Backspace</kbd> 回退 · <kbd>U</kbd> 撤销
    </p>
  </section>
</template>
