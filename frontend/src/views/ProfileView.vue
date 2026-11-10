<script setup lang="ts">
import { computed, ref } from 'vue'

import type { ProfileDay, ProfileDictionary } from '../api'
import { useSession } from '../composables/useSession'
import { buildHeatmap, dayLabel, heatLevel, recentDays, WEEKDAY_LABELS } from '../lib/profile'
import { navigate } from '../lib/router'

const { profile, loading, user, startReview } = useSession()

const days = computed(() => profile.value?.daily ?? [])
const heatmap = computed(() => buildHeatmap(days.value))
const week = computed(() => recentDays(days.value, 7))
const weekTotals = computed(() =>
  week.value.reduce(
    (total, day) => ({
      answers: total.answers + day.answers,
      new: total.new + day.new,
      review: total.review + day.review,
      practice: total.practice + day.practice,
    }),
    { answers: 0, new: 0, review: 0, practice: 0 },
  ),
)

const tooltip = ref<{ x: number; y: number; day: ProfileDay } | null>(null)

function showTooltip(event: MouseEvent, day: ProfileDay | null) {
  if (!day) {
    tooltip.value = null
    return
  }
  tooltip.value = { x: event.clientX, y: event.clientY, day }
}

function hideTooltip() {
  tooltip.value = null
}

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
        <p class="lede">最近一年的答题热力图，按天记录新词、复习和练习；连续天数只算有答题的日子。</p>
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
          <strong>学习热力图</strong>
          <span class="heat-legend">
            少
            <i class="heat-cell level-0"></i>
            <i class="heat-cell level-1"></i>
            <i class="heat-cell level-2"></i>
            <i class="heat-cell level-3"></i>
            多
          </span>
        </header>

        <div class="heatmap-scroll">
          <div class="heatmap-wrap" :style="{ width: `${Math.max(heatmap.columns.length * 15, 120)}px` }">
            <div class="heatmap-months">
              <span
                v-for="month in heatmap.months"
                :key="month.index"
                :style="{ left: `${month.index * 15}px` }"
              >{{ month.label }}</span>
            </div>
            <div class="heatmap-body">
              <div class="heatmap-weekdays">
                <span v-for="(label, index) in WEEKDAY_LABELS" :key="index">{{ label }}</span>
              </div>
              <div
                class="heatmap-grid"
                :style="{
                  gridTemplateColumns: `repeat(${heatmap.columns.length}, 12px)`,
                  gridTemplateRows: 'repeat(7, 12px)',
                }"
              >
                <template v-for="(column, columnIndex) in heatmap.columns" :key="columnIndex">
                  <div
                    v-for="(day, dayIndex) in column"
                    :key="`${columnIndex}-${dayIndex}`"
                    class="heat-cell"
                    :class="day ? `level-${heatLevel(day.answers)}` : 'empty'"
                    :title="day ? `${day.date}：${day.answers} 次` : ''"
                    @mouseenter="showTooltip($event, day)"
                    @mouseleave="hideTooltip"
                  ></div>
                </template>
              </div>
            </div>
          </div>
        </div>

        <p class="muted profile-caption">
          今天 {{ profile.today.answers }} 次 · 新词 {{ profile.today.new }} · 复习 {{ profile.today.review }}
          <template v-if="profile.today.practice"> · 练习 {{ profile.today.practice }}</template>
          <template v-if="profile.today.extra"> · 额外新词 {{ profile.today.extra }}</template>
          <br />
          最近 7 天：答题 {{ weekTotals.answers }} · 新词 {{ weekTotals.new }} · 复习 {{ weekTotals.review }}
          <template v-if="weekTotals.practice"> · 练习 {{ weekTotals.practice }}</template>
        </p>
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

    <div v-if="tooltip" class="heat-tooltip" :style="{ left: `${tooltip.x + 14}px`, top: `${tooltip.y + 14}px` }">
      <strong>{{ tooltip.day.date }}</strong>
      <div class="heat-tooltip-row"><span>答题</span><b>{{ tooltip.day.answers }}</b></div>
      <div class="heat-tooltip-row"><span>新词</span><b>{{ tooltip.day.new }}</b></div>
      <div class="heat-tooltip-row"><span>复习</span><b>{{ tooltip.day.review }}</b></div>
      <div v-if="tooltip.day.practice" class="heat-tooltip-row"><span>练习</span><b>{{ tooltip.day.practice }}</b></div>
    </div>
  </section>
</template>