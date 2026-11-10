<script setup lang="ts">
import { computed } from 'vue'

import type { Statistics } from '../api'
import { formatDue, progressPercent } from '../lib/study'

const props = defineProps<{
  stats: Statistics | null
  dictionaryName: string
  completed: number
  reason: 'session-complete' | 'daily-limit' | 'all-learned' | 'no-words' | null
  loading: boolean
}>()

const emit = defineEmits<{
  (event: 'restart'): void
  (event: 'back'): void
}>()

const headline = computed(() => {
  switch (props.reason) {
    case 'no-words':
      return '这本词典还没有单词'
    case 'all-learned':
      return '这本词典的新词都学过了'
    case 'daily-limit':
      return '今天的新词额度用完了'
    default:
      return '这一轮结束了'
  }
})

const description = computed(() => {
  switch (props.reason) {
    case 'no-words':
      return '可以导入自己的词表，或者等管理员发布词库。'
    case 'all-learned':
      return props.stats && props.stats.due_reviews
        ? `新词已经全部学过，还有 ${props.stats.due_reviews} 个到期复习在等你。`
        : '新词已经全部学过，接下来靠复习巩固。'
    case 'daily-limit':
      return '每天 20 个新词更容易记牢。明天再来，或者先复习到期的词。'
    default:
      return `本次答题 ${props.completed} 次。答错的词已经安排在十分钟后重新出现。`
  }
})

const percent = computed(() =>
  props.stats ? progressPercent(props.stats.learned_words, props.stats.total_words) : 0,
)
</script>

<template>
  <section class="panel done-panel">
    <p class="eyebrow">{{ dictionaryName || '学习总结' }}</p>
    <h2>{{ headline }}</h2>
    <p class="lede">{{ description }}</p>

    <div v-if="stats" class="stats">
      <div>
        <strong>{{ completed }}</strong>
        <span>本次答题</span>
      </div>
      <div>
        <strong>{{ stats.today_new }}/{{ stats.new_limit }}</strong>
        <span>今日新词</span>
      </div>
      <div>
        <strong>{{ stats.mastered_words }}</strong>
        <span>已掌握</span>
      </div>
      <div>
        <strong>{{ stats.due_reviews }}</strong>
        <span>待复习</span>
      </div>
    </div>

    <div v-if="stats" class="done-progress">
      <div class="bar" :aria-label="`词典进度 ${percent}%`">
        <span :style="{ width: `${percent}%` }"></span>
      </div>
      <p class="muted">
        已学 {{ stats.learned_words }} / {{ stats.total_words }} 词（{{ percent }}%）
        <template v-if="stats.next_review_at"> · 下次复习：{{ formatDue(stats.next_review_at) }}</template>
      </p>
    </div>

    <div class="done-actions">
      <button class="primary" :disabled="loading" @click="emit('restart')">
        {{ loading ? '加载中…' : '再学一轮' }}
      </button>
      <button :disabled="loading" @click="emit('back')">返回词典</button>
    </div>
  </section>
</template>
