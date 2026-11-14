<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import type { WordDetail } from '../api'
import * as api from '../api'
import { useSpeech } from '../composables/useSpeech'
import { useSession } from '../composables/useSession'
import { navigate } from '../lib/router'
import { sentenceAudioUrl } from '../lib/speech'
import { formatDue, primaryMeaning, splitExample } from '../lib/study'
import { browseMemory, formatMoment, primaryPos, statusLabel } from '../lib/words'

const props = defineProps<{ dictionaryId: number; wordId: number }>()

const { loadWord, loading, reportError, notice } = useSession()
const { speak, speakSentence, sentenceBusy, prefetch, message } = useSpeech()
const detail = ref<WordDetail | null>(null)
const relearning = ref(false)

const exampleParts = computed(() => (detail.value ? splitExample(detail.value.example, detail.value.spelling) : []))
const shortMeaning = computed(() => (detail.value ? primaryMeaning(detail.value.meaning) : ''))
const progress = computed(() => detail.value?.progress ?? null)

async function load() {
  if (!props.wordId) return
  detail.value = await loadWord(props.wordId)
  if (detail.value) {
    prefetch(detail.value.spelling, [detail.value.audio_url, detail.value.pronunciation_url])
  }
}

function backToWords() {
  const query = browseMemory[props.dictionaryId] ?? ''
  navigate(`/words/${props.dictionaryId}${query ? `?${query}` : ''}`)
}

function readAloud() {
  if (!detail.value) return
  speak(detail.value.spelling, [detail.value.audio_url, detail.value.pronunciation_url])
}

// 已归档的词不再进每日复习；想重学就把它放回队列（间隔清零、马上到期）。
async function relearn() {
  if (!detail.value || relearning.value) return
  relearning.value = true
  try {
    await api.relearnWord(detail.value.id)
    await load()
    notice.value = '已放回复习队列，下次打开背词就会出现'
  } catch (cause) {
    reportError(cause)
  } finally {
    relearning.value = false
  }
}

onMounted(load)
watch(() => props.wordId, load)
</script>

<template>
  <section class="content-section detail-section">
    <button class="link-button back" @click="backToWords">← 返回词表</button>

    <div v-if="loading && !detail" class="panel loading-panel" aria-busy="true">
      <p class="muted">正在加载单词…</p>
    </div>

    <template v-else-if="detail">
      <article class="panel word-detail">
        <div class="word-row">
          <h2 :class="{ long: detail.spelling.length > 10 }">{{ detail.spelling }}</h2>
          <button class="speak-button" title="朗读单词" aria-label="朗读单词" @click="readAloud">🔊 朗读</button>
        </div>
        <p class="phonetic">
          {{ detail.phonetic || '暂无音标' }}
          <span v-if="detail.part_of_speech" class="pos">{{ primaryPos(detail.part_of_speech) }}</span>
        </p>
        <p v-if="message" class="speech-hint">{{ message }}</p>

        <p class="detail-meaning">{{ shortMeaning }}</p>
        <p v-if="detail.meaning !== shortMeaning" class="meaning-full">{{ detail.meaning }}</p>
        <p v-if="detail.example" class="example">
          <span v-for="(part, partIndex) in exampleParts" :key="partIndex" :class="{ hit: part.hit }">{{ part.text }}</span>
        </p>
        <p v-if="detail.example_translation" class="example-translation">{{ detail.example_translation }}</p>
        <button
          v-if="detail.example"
          class="link-button sentence-speak"
          :disabled="sentenceBusy"
          @click="speakSentence(detail.example, sentenceAudioUrl(detail.id))"
        >
          {{ sentenceBusy ? '🔊 生成中…' : '🔊 朗读例句' }}
        </button>
      </article>

      <section class="panel detail-panel">
        <header class="detail-panel-head">
          <strong>记忆状态</strong>
          <span class="muted">{{ detail.dictionary.name }}</span>
        </header>
        <div v-if="progress" class="detail-stats">
          <div><strong>{{ statusLabel(progress.status) }}</strong><span>状态</span></div>
          <div><strong>{{ progress.interval_days }} 天</strong><span>当前间隔</span></div>
          <div><strong>{{ formatDue(progress.next_review_at) }}</strong><span>下次复习</span></div>
          <div><strong>{{ progress.review_count }}</strong><span>复习次数</span></div>
          <div><strong>{{ progress.wrong_count }}</strong><span>答错次数</span></div>
          <div><strong>{{ progress.streak }}</strong><span>连续答对</span></div>
        </div>
        <p v-else class="muted">还没有学过这个词，去背词时它会出现。</p>
        <p v-if="progress" class="mastered-progress">
          <template v-if="progress.status === 'retired'">已归档，不再参与每日复习。</template>
          <template v-else-if="detail.steps_to_mastered === 0">已达到「已掌握」（间隔 ≥ 21 天）。</template>
          <template v-else>
            距「已掌握」还差
            <strong>{{ detail.steps_to_mastered }} 次</strong>
            连续答对（间隔跨过 21 天就算掌握，之后还会继续复习）。
          </template>
        </p>
        <p v-if="progress?.status === 'retired'" class="retired-note">
          这个词间隔已经很长（或连续答对足够多次），已移出每日复习队列，不会再来打扰你。
          <button class="link-button" :disabled="relearning" @click="relearn">
            {{ relearning ? '正在放回…' : '重新学习' }}
          </button>
        </p>
      </section>

      <section v-if="progress" class="panel detail-panel">
        <header class="detail-panel-head">
          <strong>最近作答</strong>
          <span class="muted">最近 10 条</span>
        </header>
        <ul v-if="detail.history.length" class="history-list">
          <li v-for="entry in detail.history" :key="entry.id">
            <span class="history-rating" :class="entry.rating">{{ entry.rating_label }}</span>
            <span v-if="entry.mode === 'cloze'" class="history-evidence">
              {{ entry.revealed ? '看答案' : '填空' }}<template v-if="(entry.attempts ?? 1) > 1">· 错 {{ entry.attempts }} 次</template>
            </span>
            <span v-else class="history-evidence">自评</span>
            <span class="muted">{{ formatMoment(entry.created_at) }}</span>
            <span class="history-interval">
              {{ entry.is_practice ? '仅练习' : `${entry.interval_before} → ${entry.interval_after} 天` }}
            </span>
          </li>
        </ul>
        <p v-else class="muted">还没有作答记录。</p>
      </section>
    </template>

    <p v-else class="empty panel">
      这个词不存在，或者已经被删除了。
      <button class="link-button" @click="backToWords">返回词表</button>
    </p>
  </section>
</template>