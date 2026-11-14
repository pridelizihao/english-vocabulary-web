<script setup lang="ts">
import { computed } from 'vue'

import type { Statistics } from '../api'
import { formatDue, progressPercent, type DoneReason } from '../lib/study'

const props = defineProps<{
  stats: Statistics | null
  dictionaryName: string
  completed: number
  reason: DoneReason
  loading: boolean
}>()

const emit = defineEmits<{
  (event: 'extra'): void
  (event: 'review'): void
  (event: 'wrong'): void
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
      // 复习积压时额度会被削减，服务器给了具体原因（例如「先清复习，新词暂停一天」）。
      return props.stats?.new_limit_note
        || `今天 ${props.stats?.new_limit ?? 20} 个新词已经学完了，明天再来，或者先做一轮复习。`
    default:
      return props.completed > 0
        ? `本次答题 ${props.completed} 次。答错的词已经安排在十分钟后重新出现。`
        : '答错的词会在十分钟后重新出现，答对的词按 1 / 3 / 7 天逐步拉开间隔。'
  }
})

const percent = computed(() =>
  props.stats ? progressPercent(props.stats.learned_words, props.stats.total_words) : 0,
)

const extraLeft = computed(() =>
  props.stats ? Math.max(props.stats.extra_limit - props.stats.extra_used_today, 0) : 0,
)

const canStudyNew = computed(() => {
  if (!props.stats) return false
  // 额度被削减到 0（复习积压太多）时，不提供「再来 20 个」——按了也拿不到。
  if (props.stats.new_limit <= 0) return false
  const budgetLeft = props.stats.today_new < props.stats.new_limit
  return props.stats.remaining_new > 0 && (budgetLeft || extraLeft.value > 0)
})

const newButtonLabel = computed(() =>
  props.stats && props.stats.today_new < props.stats.new_limit ? '再学一轮' : '再来 20 个',
)

const canReview = computed(() => Boolean(props.stats && (props.stats.due_reviews > 0 || props.stats.learned_words > 0)))

const reviewButtonLabel = computed(() =>
  props.stats && props.stats.due_reviews > 0 ? `复习 ${props.stats.due_reviews} 个` : '提前复习',
)
</script>

<template>
  <section class="panel done-panel">
    <p class="eyebrow">{{ dictionaryName || '学习总结' }}</p>
    <h2>{{ headline }}</h2>
    <p class="lede">{{ description }}</p>

    <div v-if="stats" class="stats">
      <div v-if="completed > 0" title="这一轮作答的次数，含同一单词的重复">
        <strong>{{ completed }}</strong>
        <span>本次答题</span>
      </div>
      <div title="今天第一次学习的单词数 / 今日新词额度">
        <strong>{{ stats.new_limit > 0 ? `${stats.today_new}/${stats.new_limit}` : '暂停' }}</strong>
        <span>今日新词</span>
      </div>
      <div title="复习间隔达到 21 天（约连续答对 5 次）">
        <strong>{{ stats.mastered_words }}</strong>
        <span>已掌握</span>
      </div>
      <div title="下次复习时间已到、现在就该复习的单词数">
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
      <button v-if="canStudyNew" class="primary" :disabled="loading" @click="emit('extra')">
        {{ loading ? '加载中…' : newButtonLabel }}
      </button>
      <button v-if="canReview" :class="{ primary: !canStudyNew }" :disabled="loading" @click="emit('review')">
        {{ reviewButtonLabel }}
      </button>
      <button v-if="stats && stats.wrong_words > 0" :disabled="loading" @click="emit('wrong')">
        练错词 {{ stats.wrong_words }} 个
      </button>
      <button v-if="!canStudyNew && !canReview && !(stats && stats.wrong_words > 0)" disabled>今天学完了</button>
      <button :disabled="loading" @click="emit('back')">返回词典</button>
    </div>
    <p v-if="stats && !canStudyNew && !canReview && reason !== 'no-words' && reason !== 'all-learned'" class="done-hint muted">
      今天的新词额度已经用完，也没有可复习的词。明天再来，或者去背另一本词典。
    </p>
  </section>
</template>
