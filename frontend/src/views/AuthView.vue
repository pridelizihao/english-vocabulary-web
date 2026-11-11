<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import * as api from '../api'
import { useSession } from '../composables/useSession'

const { loading, signIn, signUp, signInWithEmailCode, resetPassword } = useSession()

type Mode = 'login' | 'register' | 'email' | 'reset'

const mode = ref<Mode>('login')
const username = ref('')
const password = ref('')
const email = ref('')
const code = ref('')
const localError = ref('')
const hint = ref('')
const sending = ref(false)
const cooldown = ref(0)
let timer: number | null = null

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

const emailValid = computed(() => EMAIL_RE.test(email.value.trim()))
const codeValid = computed(() => /^\d{6}$/.test(code.value.trim()))
const canSubmitPassword = computed(
  () => username.value.trim().length >= 3 && password.value.length >= 8 && !loading.value,
)
const canSubmitEmail = computed(() => emailValid.value && codeValid.value && !loading.value)
const canSubmitReset = computed(
  () => emailValid.value && codeValid.value && password.value.length >= 8 && !loading.value,
)
const codeButtonLabel = computed(() => {
  if (sending.value) return '发送中…'
  if (cooldown.value > 0) return `${cooldown.value} 秒后重发`
  return '发送验证码'
})

onBeforeUnmount(stopTimer)

function stopTimer() {
  if (timer !== null) {
    window.clearInterval(timer)
    timer = null
  }
}

function startCooldown(seconds: number) {
  stopTimer()
  cooldown.value = Math.max(1, Math.round(seconds || 60))
  timer = window.setInterval(() => {
    cooldown.value -= 1
    if (cooldown.value <= 0) stopTimer()
  }, 1000)
}

watch(mode, () => {
  localError.value = ''
  hint.value = ''
  code.value = ''
})

function switchMode(next: Mode) {
  mode.value = next
}

function errorText(cause: unknown) {
  return cause instanceof Error ? cause.message : '操作失败，请稍后重试'
}

async function sendCode() {
  localError.value = ''
  hint.value = ''
  if (!emailValid.value) {
    localError.value = '请先填写一个正确的邮箱地址'
    return
  }
  sending.value = true
  try {
    const result = await api.sendEmailCode(email.value.trim(), mode.value === 'reset' ? 'reset' : 'login')
    startCooldown(result.retry_after)
    hint.value = result.sent
      ? `验证码已经发出，${Math.round(result.expires_in / 60)} 分钟内有效，请查收邮箱（也看一眼垃圾箱）`
      : '如果这个邮箱注册过账号，验证码已经发出'
  } catch (cause) {
    localError.value = errorText(cause)
    if (cause instanceof api.ApiError && cause.status === 429) startCooldown(60)
  } finally {
    sending.value = false
  }
}

async function submitPassword() {
  localError.value = ''
  const name = username.value.trim()
  if (!/^[\w.@+-]{3,30}$/.test(name)) {
    localError.value = '用户名需为 3-30 位字母、数字或 _ . @ + -'
    return
  }
  if (password.value.length < 8) {
    localError.value = '密码至少需要 8 位'
    return
  }
  if (mode.value === 'register') {
    await signUp(name, password.value)
  } else {
    await signIn(name, password.value)
  }
}

async function submitEmail() {
  localError.value = ''
  if (!emailValid.value) {
    localError.value = '请输入正确的邮箱地址'
    return
  }
  if (!codeValid.value) {
    localError.value = '验证码是 6 位数字'
    return
  }
  await signInWithEmailCode(email.value.trim(), code.value.trim())
}

async function submitReset() {
  localError.value = ''
  if (password.value.length < 8) {
    localError.value = '密码至少需要 8 位'
    return
  }
  await resetPassword(email.value.trim(), code.value.trim(), password.value)
  password.value = ''
}
</script>

<template>
  <section class="auth-layout">
    <div class="auth-copy">
      <p class="eyebrow">WORD MEMORY</p>
      <h1>{{ mode === 'register' ? '开始你的第一轮记忆' : '每天二十个词，记牢一整个词表' }}</h1>
      <p class="lede">
        卡片和填空两种模式交替练习，答错的词十分钟后再来一遍，答对的词按
        1 / 3 / 7 天逐步拉开间隔。
      </p>
      <ul class="feature-list">
        <li><strong>今日任务</strong><span>每天最多 20 个新词，加上到期的复习</span></li>
        <li><strong>自动安排</strong><span>每个词都有下一次出现的时间，不用自己算</span></li>
        <li><strong>个人词表</strong><span>导入自己的 CSV / JSON / Excel，只有你看得见</span></li>
      </ul>
    </div>

    <div class="panel auth-panel">
      <div class="auth-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          :aria-selected="mode === 'login' || mode === 'register'"
          :class="{ active: mode === 'login' || mode === 'register' }"
          @click="switchMode('login')"
        >账号密码</button>
        <button
          type="button"
          role="tab"
          :aria-selected="mode === 'email' || mode === 'reset'"
          :class="{ active: mode === 'email' || mode === 'reset' }"
          @click="switchMode('email')"
        >邮箱验证码</button>
      </div>

      <template v-if="mode === 'login' || mode === 'register'">
        <p class="eyebrow">{{ mode === 'register' ? '创建账号' : '欢迎回来' }}</p>
        <h2>{{ mode === 'register' ? '注册' : '登录' }}</h2>
        <form @submit.prevent="submitPassword">
          <label>
            用户名
            <input
              v-model="username"
              required
              minlength="3"
              maxlength="30"
              autocomplete="username"
              placeholder="3-30 位字母或数字"
            />
          </label>
          <label>
            密码
            <input
              v-model="password"
              type="password"
              required
              minlength="8"
              autocomplete="current-password"
              :placeholder="mode === 'register' ? '至少 8 位' : '输入密码'"
            />
          </label>
          <p v-if="localError" class="error inline">{{ localError }}</p>
          <button class="primary wide" type="submit" :disabled="!canSubmitPassword">
            {{ loading ? '处理中…' : mode === 'register' ? '注册并开始' : '登录' }}
          </button>
        </form>
        <div class="auth-links">
          <button v-if="mode === 'login'" class="link-button" @click="switchMode('reset')">忘记密码？</button>
          <button class="link-button" @click="switchMode(mode === 'register' ? 'login' : 'register')">
            {{ mode === 'register' ? '已有账号？去登录' : '还没有账号？注册一个' }}
          </button>
        </div>
      </template>

      <template v-else-if="mode === 'email'">
        <p class="eyebrow">邮箱验证码</p>
        <h2>登录 / 注册</h2>
        <p class="muted auth-hint">没注册过的邮箱验证后会自动创建账号，连密码都不用设。</p>
        <form @submit.prevent="submitEmail">
          <label>
            邮箱
            <input
              v-model="email"
              type="email"
              required
              autocomplete="email"
              placeholder="you@example.com"
            />
          </label>
          <label>
            验证码
            <div class="code-row">
              <input
                v-model="code"
                inputmode="numeric"
                autocomplete="one-time-code"
                maxlength="6"
                pattern="\d{6}"
                required
                placeholder="6 位数字"
              />
              <button type="button" class="code-button" :disabled="sending || cooldown > 0" @click="sendCode">
                {{ codeButtonLabel }}
              </button>
            </div>
          </label>
          <p v-if="hint" class="muted inline-note">{{ hint }}</p>
          <p v-if="localError" class="error inline">{{ localError }}</p>
          <button class="primary wide" type="submit" :disabled="!canSubmitEmail">
            {{ loading ? '处理中…' : '验证并进入' }}
          </button>
        </form>
        <div class="auth-links">
          <button class="link-button" @click="switchMode('login')">用账号密码登录</button>
        </div>
      </template>

      <template v-else>
        <p class="eyebrow">重置密码</p>
        <h2>忘记密码</h2>
        <p class="muted auth-hint">邮箱验证通过后会直接登录，然后就可以改密码了。</p>
        <form @submit.prevent="submitReset">
          <label>
            注册邮箱
            <input v-model="email" type="email" required autocomplete="email" placeholder="you@example.com" />
          </label>
          <label>
            验证码
            <div class="code-row">
              <input
                v-model="code"
                inputmode="numeric"
                autocomplete="one-time-code"
                maxlength="6"
                pattern="\d{6}"
                required
                placeholder="6 位数字"
              />
              <button type="button" class="code-button" :disabled="sending || cooldown > 0" @click="sendCode">
                {{ codeButtonLabel }}
              </button>
            </div>
          </label>
          <label>
            新密码
            <input
              v-model="password"
              type="password"
              required
              minlength="8"
              autocomplete="new-password"
              placeholder="至少 8 位"
            />
          </label>
          <p v-if="hint" class="muted inline-note">{{ hint }}</p>
          <p v-if="localError" class="error inline">{{ localError }}</p>
          <button class="primary wide" type="submit" :disabled="!canSubmitReset">
            {{ loading ? '处理中…' : '重置并登录' }}
          </button>
        </form>
        <div class="auth-links">
          <button class="link-button" @click="switchMode('login')">返回登录</button>
        </div>
      </template>
    </div>
  </section>
</template>
