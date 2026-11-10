<script setup lang="ts">
import { computed } from 'vue'

import type { ProfileDictionary } from '../api'
import { useSession } from '../composables/useSession'
import { barPercent, dayLabel, heatLevel, maxAnswers, recentDays } from '../lib/profile'
import { navigate } from '../lib/router'

const { profile, loading, user, startReview } = useSession()

const days = computed(() => profile.value?.daily ?? [])
const week = computed(() => recentDays(days.value, 7))
const weekMax = computed(() => Math.max(maxAnswers(week.value), 1))

function review(item: ProfileDictionary) {
  startReview(item.id, item.due > 0 ? 'due' : 'early')
}
</script>

<template>
  <section class="content-section profile-section">
    <div class="hero profile-hero">
      <div>
        <p class="eyebrow">学习数据</p>
        <h2>{{ user?.username || '我' }} 的学习习惯</h2>
        <p class="lede">按天记录答题量：新词、复习和练习分开统计，连续天数只算有答题的日子。</p>
      </div>
      <button class="link-button" @click="navigate('/')">← 返回词典</button>
    </div>

    <div v-if="loading && !profile" class="panel loading-panel" aria-busy="true">
      <p class="muted">正在加载学习数据…</p>
    </div>

    <template v-else-if="profile">
      <div class="profile-cards">
        <div class="profile-card">
          <strong>{{ profile.today.answers }}</strong>
          <span>今日答题</span>
        </div>
        <div class="profile-card">
          <strong>{{ profile.streak }}</strong>
          <span>连续天数</span>
        </div>
        <div class="profile-card">
          <strong>{{ profile.totals.answers }}</strong>
          <span>累计答题</span>
        </div>
        <div class="profile-card">
          <strong>{{ profile.totals.learned }}</strong>
          <span>已学单词</span>
        </div>
        <div class="profile-card">
          <strong>{{ profile.totals.mastered }}</strong>
          <span>已掌握</span>
        </div>
      </div>

      <section class="panel profile-panel">
        <header class="profile-panel-head">
          <strong>最近 30 天</strong>
          <span class="heat-legend">
            少
            <i class="heat-cell level-0"></i>
            <i class="heat-cell level-1"></i>
            <i class="heat-cell level-2"></i>
            <i class="heat-cell level-3"></i>
            多
          </span>
        </header>
        <div class="heatmap">
          <div
            v-for="day in days"
            :key="day.date"
            class="heat-cell"
            :class="`level-${heatLevel(day.answers)}`"
            :title="`${day.date}：${day.answers} 次（新词 ${day.new} · 复习 ${day.review} · 练习 ${day.practice}）`"
          ></div>
        </div>
        <p class="muted profile-caption">
          今天 {{ profile.today.answers }} 次 · 新词 {{ profile.today.new }} · 复习 {{ profile.today.review }}
          <template v-if="profile.today.practice"> · 练习 {{ profile.today.practice }}</template>
          <template v-if="profile.today.extra"> · 额外新词 {{ profile.today.extra }}</template>
        </p>
      </section>

      <section class="panel profile-panel">
        <header class="profile-panel-head">
          <strong>最近 7 天</strong>
          <span class="muted">新词 + 复习</span>
        </header>
        <div class="week-chart">
          <div v-for="day in week" :key="day.date" class="week-column">
            <div class="week-bars">
              <span class="bar-new" :style="{ height: `${barPercent(day.new, weekMax)}%` }" :title="`新词 ${day.new}`"></span>
              <span class="bar-review" :style="{ height: `${barPercent(day.review, weekMax)}%` }" :title="`复习 ${day.review}`"></span>
            </div>
            <span class="week-label">{{ dayLabel(day.date) }}</span>
          </div>
        </div>
      </section>

      <section class="panel profile-panel">
        <header class="profile-panel-head">
          <strong>按词典</strong>
          <span class="muted">已学 / 掌握 / 待复习</span>
        </header>
        <div class="profile-dictionaries">
          <div v-for="item in profile.dictionaries" :key="item.id" class="profile-dictionary">
            <div>
              <strong>{{ item.name }}</strong>
              <p class="muted">{{ item.learned }} 已学 · {{ item.mastered }} 掌握 · {{ item.due }} 待复习</p>
            </div>
            <button :disabled="loading || item.learned === 0" @click="review(item)">
              {{ item.due > 0 ? `复习 ${item.due} 个` : '提前复习' }}
            </button>
          </div>
          <p v-if="!profile.dictionaries.length" class="muted">还没有学习记录，先去背几个词吧。</p>
        </div>
      </section>
    </template>
  </section>
</template>
