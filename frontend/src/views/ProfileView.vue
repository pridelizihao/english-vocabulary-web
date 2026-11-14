<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import * as api from '../api'
import type { ProfileDay, ProfileDictionary } from '../api'
import { useSession } from '../composables/useSession'
import {
  barRects,
  calibrationVerdict,
  downsample,
  linePath,
  linePoints,
  pct,
  progressScale,
  ratingHint,
  retentionVerdict,
  trimLeadingEmpty,
} from '../lib/chart'
import {
  buildHeatmap,
  dayLabel,
  heatLevel,
  recentDays,
  tooltipPlacement,
  WEEKDAY_LABELS,
} from '../lib/profile'
import { navigate } from '../lib/router'

const {
  profile, loading, user, startReview, startWrong, insights, loadInsights, bindEmail,
} = useSession()

const days = computed(() => profile.value?.daily ?? [])
const heatWrap = ref<HTMLElement | null>(null)
const heatWidth = ref(0)
const heatCell = ref(12)
const heatGap = ref(3)
let tapTimer: number | null = null
// 一周一列；容器越窄显示的周数越少，格子才能保持看得清的尺寸。
const heatWeeks = computed(() => {
  if (!heatWidth.value) return 53
  return Math.min(53, Math.max(13, Math.round((heatWidth.value - 22) / 14.5)))
})
const visibleDays = computed(() => days.value.slice(-(heatWeeks.value * 7)))
const heatmap = computed(() => buildHeatmap(visibleDays.value))
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

// --- 保持率 / 进度 / 评分校准 ---------------------------------------------
const CHART_WIDTH = 640
const CHART_HEIGHT = 170

const retention = computed(() => insights.value?.retention ?? [])
const retentionRects = computed(() =>
  barRects(retention.value.map((bucket) => bucket.rate), CHART_WIDTH, CHART_HEIGHT),
)
const retentionText = computed(() => retentionVerdict(retention.value))
const hasRetention = computed(() => retention.value.some((bucket) => bucket.attempts > 0))

const progressPoints = computed(() => downsample(trimLeadingEmpty(insights.value?.progress ?? []), 80))
const hasProgress = computed(() => progressPoints.value.some((point) => point.learned > 0 || point.mastered > 0))
const progressTop = computed(() => progressScale(progressPoints.value))
const learnedPath = computed(() =>
  linePath(linePoints(progressPoints.value.map((point) => point.learned), CHART_WIDTH, CHART_HEIGHT, progressTop.value)),
)
const masteredPath = computed(() =>
  linePath(linePoints(progressPoints.value.map((point) => point.mastered), CHART_WIDTH, CHART_HEIGHT, progressTop.value)),
)
const progressFirst = computed(() => progressPoints.value[0]?.date ?? '')
const progressLast = computed(() => progressPoints.value[progressPoints.value.length - 1]?.date ?? '')
const learnedTotal = computed(() => progressPoints.value[progressPoints.value.length - 1]?.learned ?? 0)
const masteredTotal = computed(() => progressPoints.value[progressPoints.value.length - 1]?.mastered ?? 0)

const calibration = computed(() => insights.value?.calibration ?? [])
const calibrationText = computed(() => calibrationVerdict(calibration.value))
const calibrationSamples = computed(() => insights.value?.sample.pairs ?? 0)

// --- 绑定邮箱 -------------------------------------------------------------
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const emailInput = ref('')
const emailCode = ref('')
const emailSending = ref(false)
const emailCooldown = ref(0)
const emailError = ref('')
let emailTimer: number | null = null

const emailValid = computed(() => EMAIL_RE.test(emailInput.value.trim()))
const emailCodeValid = computed(() => /^\d{6}$/.test(emailCode.value.trim()))

function stopEmailTimer() {
  if (emailTimer !== null) {
    window.clearInterval(emailTimer)
    emailTimer = null
  }
}

async function sendBindCode() {
  emailError.value = ''
  if (!emailValid.value) {
    emailError.value = '请输入正确的邮箱地址'
    return
  }
  emailSending.value = true
  try {
    const result = await api.sendEmailCode(emailInput.value.trim(), 'bind')
    stopEmailTimer()
    emailCooldown.value = Math.max(1, Math.round(result.retry_after))
    emailTimer = window.setInterval(() => {
      emailCooldown.value -= 1
      if (emailCooldown.value <= 0) stopEmailTimer()
    }, 1000)
  } catch (cause) {
    emailError.value = cause instanceof Error ? cause.message : '验证码发送失败，请稍后重试'
  } finally {
    emailSending.value = false
  }
}

async function confirmBind() {
  emailError.value = ''
  if (!emailCodeValid.value) {
    emailError.value = '验证码是 6 位数字'
    return
  }
  const ok = await bindEmail(emailInput.value.trim(), emailCode.value.trim())
  if (ok) {
    emailInput.value = ''
    emailCode.value = ''
  }
}

let observer: ResizeObserver | null = null

onMounted(() => {
  if (typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(() => measureHeatmap())
  }
  nextTick(measureHeatmap)
  loadInsights(180)
})
onBeforeUnmount(() => {
  observer?.disconnect()
  stopEmailTimer()
  clearTapTimer()
})

watch(heatWrap, (element) => {
  if (element && observer) observer.observe(element)
  nextTick(measureHeatmap)
})
watch(heatmap, () => nextTick(measureHeatmap))

// 格子边长按容器宽度算：正好铺满一行、保持正方形，不出现横向滚动。
function measureHeatmap() {
  const element = heatWrap.value
  if (!element) return
  const width = element.clientWidth
  if (width && width !== heatWidth.value) heatWidth.value = width
  const columns = heatmap.value.columns.length
  if (!columns) return
  const available = width - 22
  let gap = 3
  let cell = (available - (columns - 1) * gap) / columns
  if (cell < 8) {
    gap = 2
    cell = (available - (columns - 1) * gap) / columns
  }
  heatCell.value = Math.max(3, Math.round(cell * 100) / 100)
  heatGap.value = gap
}

function showTooltip(event: MouseEvent, day: ProfileDay | null) {
  if (!day) {
    tooltip.value = null
    return
  }
  const { left, top } = tooltipPlacement(
    event.clientX,
    event.clientY,
    window.innerWidth,
    window.innerHeight,
  )
  tooltip.value = { x: left, y: top, day }
}

function hideTooltip() {
  // 触摸屏上没有「移出」这件事，点一下之后由定时器负责收起；
  // 否则浏览器补发的 mouseleave 会立刻把刚弹出的提示关掉。
  if (tapTimer !== null) return
  tooltip.value = null
}

// 手机没有 hover：点格子看数字，3.5 秒后自己收起来，不挡住下面的内容。
function tapTooltip(event: MouseEvent, day: ProfileDay | null) {
  clearTapTimer()
  if (!day) {
    tooltip.value = null
    return
  }
  showTooltip(event, day)
  tapTimer = window.setTimeout(() => {
    tapTimer = null
    tooltip.value = null
  }, 3500)
}

function clearTapTimer() {
  if (tapTimer === null) return
  window.clearTimeout(tapTimer)
  tapTimer = null
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
        <p class="lede">答题热力图，按天记录新词、复习和练习（最多近一年，屏幕窄时自动缩短）；连续天数只算有答题的日子。</p>
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

      <p v-if="profile.closest_to_mastered" class="closest-mastered">
        <template v-if="profile.closest_to_mastered.steps === 0">
          离「已掌握」最近的是 <strong>{{ profile.closest_to_mastered.spelling }}</strong>，已经达标。
        </template>
        <template v-else>
          离「已掌握」最近的是 <strong>{{ profile.closest_to_mastered.spelling }}</strong>（间隔 {{ profile.closest_to_mastered.interval_days }} 天），再连续答对 <strong>{{ profile.closest_to_mastered.steps }} 次</strong>就到 21 天。
        </template>
      </p>

      <section class="panel profile-panel">
        <header class="profile-panel-head">
          <strong>账号邮箱</strong>
          <span class="muted">用于验证码登录和找回密码</span>
        </header>

        <p v-if="user?.email" class="muted email-bound">
          已绑定 <strong>{{ user.email }}</strong>，忘记密码时可以用它收验证码。
        </p>
        <template v-else>
          <p class="muted email-bound">
            还没绑定邮箱。绑定后可以用邮箱验证码登录，忘记密码也能自己重置，不用找人帮忙。
          </p>
          <form class="bind-form" @submit.prevent="confirmBind">
            <div class="code-row">
              <input v-model="emailInput" type="email" placeholder="邮箱地址" required />
              <button
                type="button"
                class="code-button"
                :disabled="emailSending || emailCooldown > 0"
                @click="sendBindCode"
              >
                {{ emailSending ? '发送中…' : emailCooldown > 0 ? `${emailCooldown} 秒后重发` : '发送验证码' }}
              </button>
            </div>
            <input
              v-model="emailCode"
              class="bind-code"
              inputmode="numeric"
              maxlength="6"
              pattern="\d{6}"
              placeholder="6 位验证码"
              required
            />
            <button class="primary wide" type="submit" :disabled="!emailValid || !emailCodeValid || loading">
              绑定邮箱
            </button>
            <p v-if="emailError" class="error inline">{{ emailError }}</p>
          </form>
        </template>
      </section>

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

        <div
          ref="heatWrap"
          class="heatmap-wrap"
          :style="{ '--heat-cell': `${heatCell}px`, '--heat-gap': `${heatGap}px` }"
        >
            <div class="heatmap-months">
              <span
                v-for="month in heatmap.months"
                :key="month.index"
                :style="{ left: `${(month.index / Math.max(heatmap.columns.length, 1)) * 100}%` }"
              >{{ month.label }}</span>
            </div>
            <div class="heatmap-body">
              <div class="heatmap-weekdays">
                <span v-for="(label, index) in WEEKDAY_LABELS" :key="index">{{ label }}</span>
              </div>
              <div
                class="heatmap-grid"
                :style="{ gridTemplateColumns: `repeat(${heatmap.columns.length}, minmax(0, 1fr))` }"
              >
                <template v-for="(column, columnIndex) in heatmap.columns" :key="columnIndex">
                  <div
                    v-for="(day, dayIndex) in column"
                    :key="`${columnIndex}-${dayIndex}`"
                    class="heat-cell"
                    :class="day ? `level-${heatLevel(day.answers)}` : 'is-empty'"
                    :title="day ? `${day.date}：${day.answers} 次` : ''"
                    @mouseenter="showTooltip($event, day)"
                    @mouseleave="hideTooltip"
                    @click="tapTooltip($event, day)"
                  ></div>
                </template>
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
          <strong>记忆保持率</strong>
          <span class="muted">按「上次见面 → 这次回忆」的间隔分档</span>
        </header>

        <template v-if="hasRetention">
          <div class="chart-wrap">
            <svg
              class="chart"
              :viewBox="`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`"
              role="img"
              aria-label="不同间隔下的保持率"
            >
              <rect
                v-for="rect in retentionRects"
                :key="rect.index"
                :x="rect.x"
                :y="rect.filled ? rect.y : CHART_HEIGHT - 2"
                :width="rect.width"
                :height="rect.filled ? Math.max(rect.height, 2) : 2"
                rx="4"
                :class="rect.filled ? 'chart-bar' : 'chart-bar is-empty'"
              />
            </svg>
            <div class="chart-axis">
              <div v-for="bucket in retention" :key="bucket.label" class="chart-tick">
                <b>{{ pct(bucket.rate) }}</b>
                <span>{{ bucket.label }}</span>
                <em>{{ bucket.attempts ? `${bucket.attempts} 次` : '—' }}</em>
              </div>
            </div>
          </div>
          <p class="chart-note" :class="`tone-${retentionText.tone}`">{{ retentionText.text }}</p>
        </template>
        <p v-else class="muted">
          还没有足够的复习记录。等你把第一批词放下几天再回来，这里会显示记忆能撑多久。
        </p>
      </section>

      <section class="panel profile-panel">
        <header class="profile-panel-head">
          <strong>累计进度</strong>
          <span class="chart-legend">
            <i class="dot learned"></i>已学 {{ learnedTotal }}
            <i class="dot mastered"></i>已掌握 {{ masteredTotal }}
          </span>
        </header>

        <template v-if="hasProgress">
          <div class="chart-wrap">
            <span class="chart-y top">{{ progressTop }}</span>
            <span class="chart-y bottom">0</span>
            <svg
              class="chart"
              :viewBox="`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`"
              role="img"
              aria-label="累计已学与已掌握单词数"
            >
              <path :d="learnedPath" class="chart-line learned" />
              <path :d="masteredPath" class="chart-line mastered" />
            </svg>
            <div class="chart-axis is-spread">
              <span>{{ progressFirst }}</span>
              <span>{{ progressLast }}</span>
            </div>
          </div>
        </template>
        <p v-else class="muted">还没有学习记录。</p>
      </section>

      <section class="panel profile-panel">
        <header class="profile-panel-head">
          <strong>评分校准</strong>
          <span class="muted">只看卡片模式的自评 vs 下次实际表现</span>
        </header>

        <template v-if="calibrationSamples">
          <table class="calibration-table">
            <thead>
              <tr>
                <th>你点的</th>
                <th>次数</th>
                <th>下次忘了</th>
                <th>判断</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in calibration" :key="row.rating">
                <td>{{ row.label }}</td>
                <td>{{ row.samples || '—' }}</td>
                <td>
                  <span class="rate-value">{{ pct(row.forgotten_rate) }}</span>
                </td>
                <td class="calibration-hint">{{ ratingHint(row) }}</td>
              </tr>
            </tbody>
          </table>
          <p class="chart-note" :class="`tone-${calibrationText.tone}`">{{ calibrationText.text }}</p>
        </template>
        <p v-else class="muted">
          同一个词被复习两次以上之后，这里会显示你的评分尺度准不准。
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
            <div class="profile-dictionary-actions">
              <button :disabled="loading || item.learned === 0" @click="review(item)">
                {{ item.due > 0 ? `复习 ${item.due} 个` : '提前复习' }}
              </button>
              <button v-if="item.wrong > 0" :disabled="loading" @click="startWrong(item.id)">
                练错词 {{ item.wrong }} 个
              </button>
            </div>
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