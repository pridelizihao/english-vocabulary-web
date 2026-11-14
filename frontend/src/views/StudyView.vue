<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { AnswerPayload, Rating } from '../api'
import { useSpeech } from '../composables/useSpeech'
import { sentenceAudioUrl } from '../lib/speech'
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
import { primaryPos } from '../lib/words'

const props = defineProps<{
  item: StudyItem
  index: number
  total: number
  mode: 'card' | 'cloze'
  loading: boolean
  dictionaryName: string
  newLearnedToday: number
  newLimit: number
  newLimitNote: string
  dueReviews: number
  canUndo: boolean
}>()

const emit = defineEmits<{
  (event: 'rate', payload: AnswerPayload): void
  (event: 'back'): void
  (event: 'undo'): void
  (event: 'known'): void
  (event: 'update:mode', mode: 'card' | 'cloze'): void
}>()

const revealed = ref(false)
// 卡片正面直接认输：没想起来就先看答案，这一题记「忘记了」，不再让人自评。
const gaveUp = ref(false)
const answer = ref<string[]>([])
const result = ref<'correct' | 'wrong' | null>(null)
const shaking = ref(false)
// 这一题累计错了几次：「再试一次」不清零，否则偷看之后重试就能洗白。
const attempts = ref(0)
// 是否看过答案：一旦看过就为真，这一题最高只能记「忘记了」。
const peeked = ref(false)
const {
  speak: speakWord,
  stop: stopSpeech,
  prefetch: prefetchSpeech,
  speakSentence,
  sentenceBusy,
  message: speechMessage,
  busy: speechBusy,
} = useSpeech()
const hintVisible = ref(true)

// 提前缓冲当前词的发音，按下「朗读」时就不用再等网络。
watch(
  () => props.item,
  (item) => {
    if (!item) return
    prefetchSpeech(item.word.spelling, [item.word.audio_url, item.word.pronunciation_url])
  },
  { immediate: true },
)
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
  gaveUp.value = false
  result.value = null
  shaking.value = false
  attempts.value = 0
  peeked.value = false
  speechMessage.value = ''
  hintVisible.value = true
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

// 手机上软键盘会占掉半个屏幕，并把底部操作区顶上去。这一题已经定论时就把
// 焦点交还给页面，键盘自己收起，评分/继续按钮才能露出来。
function dismissKeyboard() {
  const active = document.activeElement as HTMLElement | null
  if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) active.blur()
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
    dismissKeyboard()
    return
  }
  attempts.value += 1
  shaking.value = true
  window.setTimeout(() => {
    shaking.value = false
  }, 500)
  // First miss: keep the answer hidden and let the learner think again.
  result.value = attempts.value >= 2 ? 'wrong' : 'retry'
  if (result.value === 'wrong') dismissKeyboard()
}

function revealAnswer() {
  attempts.value = Math.max(attempts.value, 1)
  peeked.value = true
  answer.value = Array.from(word.value.spelling)
  result.value = 'wrong'
  dismissKeyboard()
}

function editAgain() {
  result.value = null
  focusFirstEmpty()
}

function restartAttempt() {
  // 试错次数和「看过答案」都不清零：这一题已经不算想起来了。
  result.value = null
  answer.value = buildClozeAnswer(word.value.spelling)
  focusFirstEmpty()
}

function toggleMode() {
  emit('update:mode', props.mode === 'card' ? 'cloze' : 'card')
}

function primaryAction() {
  if (props.mode === 'card') {
    if (!revealed.value) revealed.value = true
    return
  }
  if (result.value === 'correct') {
    submitEvidence(true)
    return
  }
  if (result.value === 'wrong') {
    restartAttempt()
    return
  }
  submitCloze()
}

/** 卡片模式：自评。`revealed` 表示这题是「没想起来、看了答案」才过的。 */
function emitRate(rating: Rating, revealed = false) {
  if (props.loading) return
  emit('rate', { mode: 'card', rating, revealed })
}

/** 正面按「想不起来」：直接看答案，这一题记「忘记了」。 */
function giveUp() {
  if (props.loading) return
  revealed.value = true
  gaveUp.value = true
}

/** 填空模式：只交证据，评多少由服务器按「错几次 / 看没看答案」决定。 */
function submitEvidence(correct: boolean) {
  if (props.loading) return
  emit('rate', {
    mode: 'cloze',
    correct,
    attempts: Math.max(attempts.value, 1),
    revealed: peeked.value,
  })
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
  // Alt+M works even while typing into a blank; a plain "m" must stay a letter.
  if (event.altKey && (event.code === 'KeyM' || event.key.toLowerCase() === 'm')) {
    event.preventDefault()
    toggleMode()
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
  if (event.key === 'm' || event.key === 'M') {
    event.preventDefault()
    toggleMode()
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
    if (!revealed.value) {
      // 正面两条路：空格 = 想起来了（看答案核实），1 = 没想起来。
      if (event.key === ' ' || event.key === 'Enter') {
        event.preventDefault()
        revealed.value = true
        return
      }
      if (event.key === '1') {
        event.preventDefault()
        giveUp()
      }
      return
    }
    if (gaveUp.value) {
      // 已经看过答案、记了「忘记了」，只剩继续。
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        emitRate('again', true)
      }
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
          <template v-if="newLimit > 0">今日新词 {{ newLearnedToday }}/{{ newLimit }}</template>
          <template v-else>今天不排新词</template>
          <template v-if="dueReviews"> · 待复习 {{ dueReviews }}</template>
        </p>
      </div>
      <div class="study-tools">
        <div class="mode-switch" role="group" aria-label="练习模式" title="卡片 / 填空切换（M；填空输入时 Alt+M）">
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

    <p v-if="newLimitNote" class="budget-note">{{ newLimitNote }}</p>

    <section v-if="mode === 'card'" class="card">
      <div class="word-row">
        <h3 :class="{ long: word.spelling.length > 10 }">{{ word.spelling }}</h3>
        <button class="speak-button" title="朗读单词" aria-label="朗读单词" :aria-busy="speechBusy" @click="speak">
          {{ speechBusy ? '🔊 播放中…' : '🔊 朗读' }}
        </button>
      </div>
      <p class="phonetic">
        {{ word.phonetic || '暂无音标' }}
        <span v-if="word.part_of_speech" class="pos">{{ primaryPos(word.part_of_speech) }}</span>
      </p>
      <p v-if="speechMessage" class="speech-hint">{{ speechMessage }}</p>

      <div v-if="!revealed" class="card-choices">
        <button class="give-up-button" :disabled="loading" @click="giveUp">
          想不起来 <kbd>1</kbd>
        </button>
        <button class="primary reveal-button" :disabled="loading" @click="revealed = true">
          显示答案 <kbd>空格</kbd>
        </button>
      </div>

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
        <button
          v-if="word.example"
          class="link-button sentence-speak"
          :disabled="sentenceBusy"
          @click="speakSentence(word.example, sentenceAudioUrl(word.id))"
        >
          {{ sentenceBusy ? '🔊 生成中…' : '🔊 朗读例句' }}
        </button>
        <div v-if="gaveUp" class="gave-up-panel">
          <p class="muted">这一题记「忘记了」，{{ item.preview?.again || '10 分钟后' }}再来一次。</p>
          <button class="primary" :disabled="loading" @click="emitRate('again', true)">
            继续 <kbd>回车</kbd>
          </button>
        </div>
        <div v-else class="ratings">
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
            autocorrect="off"
            enterkeyhint="go"
            spellcheck="false"
            :aria-label="`第 ${slot.index + 1} 个字母`"
            @input="onInput(slot.index, $event)"
            @keydown="onSlotKeydown(slot.index, $event)"
          />
        </template>
      </div>
      <p v-if="word.phonetic" class="phonetic">{{ word.phonetic }}</p>
      <button class="speak-button" title="朗读单词" aria-label="朗读单词" :aria-busy="speechBusy" @click="speak">
        {{ speechBusy ? '🔊 播放中…' : '🔊 朗读' }}
      </button>
      <p v-if="speechMessage" class="speech-hint">{{ speechMessage }}</p>

      <div v-if="word.example" class="cloze-hint">
        <template v-if="hintVisible">
          <p class="example">{{ maskedExample }}</p>
          <p v-if="word.example_translation" class="example-translation">{{ word.example_translation }}</p>
        </template>
        <button class="link-button hint-toggle" @click="hintVisible = !hintVisible">
          {{ hintVisible ? '隐藏例句' : '显示例句' }}
        </button>
      </div>

      <p v-if="noBlanks" class="muted">这个词太短，没有需要填的空，直接继续即可。</p>

      <div v-if="!result" class="cloze-actions">
        <button class="primary" :disabled="(!complete && !noBlanks) || loading" @click="noBlanks ? submitEvidence(true) : submitCloze()">
          {{ noBlanks ? '继续' : '检查答案' }} <kbd>回车</kbd>
        </button>
        <button v-if="!noBlanks" class="link-button" @click="revealAnswer">不会，看答案 <kbd>Esc</kbd></button>
      </div>

      <div v-else-if="result === 'correct'" class="cloze-result">
        <strong class="correct">{{ peeked ? '填对了，但看过答案' : '回答正确' }}</strong>
        <p v-if="item.kind === 'practice'">练习已记录，不改变复习间隔</p>
        <p v-else-if="peeked">这一题按「忘记」处理，{{ item.preview?.again || '10 分钟后' }}再来一次</p>
        <p v-else>下次复习：{{ item.preview?.good || '按计划' }}</p>
        <button class="primary" :disabled="loading" @click="submitEvidence(true)">继续 <kbd>回车</kbd></button>
      </div>

      <div v-else-if="result === 'retry'" class="cloze-result">
        <strong class="wrong">还不对</strong>
        <p>再想想；实在想不起来就按 Esc 看答案——看了答案这一题就算没想起来。</p>
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
          <button :disabled="loading" @click="submitEvidence(false)">记不住，过</button>
        </div>
      </div>
    </section>

    <div v-if="item.kind !== 'practice'" class="known-row">
      <button class="link-button known-button" :disabled="loading" @click="emit('known')">
        我已经会了，移出复习
      </button>
    </div>

    <p v-if="mode === 'card' && !revealed" class="keyboard-hint muted">
      快捷键：<kbd>1</kbd> 想不起来 · <kbd>空格</kbd> 想起来了、看答案 · <kbd>M</kbd> 切换模式 · <kbd>U</kbd> 撤销
    </p>
    <p v-else-if="mode === 'card' && gaveUp" class="keyboard-hint muted">
      快捷键：<kbd>回车</kbd> 继续 · <kbd>U</kbd> 撤销
    </p>
    <p v-else-if="mode === 'card'" class="keyboard-hint muted">
      快捷键：<kbd>1</kbd>–<kbd>4</kbd> 评分 · <kbd>M</kbd> 切换模式 · <kbd>U</kbd> 撤销
    </p>
    <p v-else class="keyboard-hint muted">
      快捷键：<kbd>回车</kbd> 检查 · <kbd>Esc</kbd> 看答案 · <kbd>Alt</kbd>+<kbd>M</kbd> 切换模式 · <kbd>U</kbd> 撤销
    </p>
  </section>
</template>
