<script setup lang="ts">
import { computed, ref } from 'vue'

import { useSession } from '../composables/useSession'

const { loading, signIn, signUp } = useSession()

const isRegister = ref(false)
const username = ref('')
const password = ref('')
const localError = ref('')

const canSubmit = computed(
  () => username.value.trim().length >= 3 && password.value.length >= 8 && !loading.value,
)

async function submit() {
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
  if (isRegister.value) {
    await signUp(name, password.value)
  } else {
    await signIn(name, password.value)
  }
}

function toggleMode() {
  isRegister.value = !isRegister.value
  localError.value = ''
}
</script>

<template>
  <section class="auth-layout">
    <div class="auth-copy">
      <p class="eyebrow">WORD MEMORY</p>
      <h1>{{ isRegister ? '开始你的第一轮记忆' : '每天二十个词，记牢一整个词表' }}</h1>
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
      <p class="eyebrow">{{ isRegister ? '创建账号' : '欢迎回来' }}</p>
      <h2>{{ isRegister ? '注册' : '登录' }}</h2>
      <form @submit.prevent="submit">
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
            :placeholder="isRegister ? '至少 8 位' : '输入密码'"
          />
        </label>
        <p v-if="localError" class="error inline">{{ localError }}</p>
        <button class="primary wide" type="submit" :disabled="!canSubmit">
          {{ loading ? '处理中…' : isRegister ? '注册并开始' : '登录' }}
        </button>
      </form>
      <button class="link-button switch" @click="toggleMode">
        {{ isRegister ? '已有账号？去登录' : '还没有账号？注册一个' }}
      </button>
    </div>
  </section>
</template>
