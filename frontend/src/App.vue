<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'

import { useSession } from './composables/useSession'
import { doneReason } from './lib/study'
import { navigate, route } from './lib/router'
import AuthView from './views/AuthView.vue'
import DictionariesView from './views/DictionariesView.vue'
import DoneView from './views/DoneView.vue'
import StudyView from './views/StudyView.vue'

const {
  user,
  dictionaries,
  activeDictionary,
  currentItem,
  index,
  total,
  completed,
  stats,
  loading,
  error,
  notice,
  mode,
  bootstrapped,
  bootstrap,
  signOut,
  startStudy,
  rate,
  loadDone,
  loadDictionaries,
  clearError,
  reportError,
} = useSession()

const reason = computed(() => {
  if (!stats.value) return 'session-complete'
  return doneReason({
    total_words: stats.value.total_words,
    remaining_new: stats.value.remaining_new,
    today_new: stats.value.today_new,
    new_limit: stats.value.new_limit,
  })
})

async function syncRoute() {
  const current = route.value
  if (!bootstrapped.value) await bootstrap()
  if (current.name === 'auth') {
    if (user.value) navigate('/')
    return
  }
  if (!user.value) {
    navigate('/auth')
    return
  }
  if (current.name === 'dictionaries') {
    if (!dictionaries.value.length) {
      try {
        await loadDictionaries()
      } catch (cause) {
        reportError(cause)
      }
    }
  } else if (current.name === 'study') {
    if (activeDictionary.value?.id !== current.dictionaryId || !currentItem.value) {
      await startStudy(current.dictionaryId)
    }
  } else if (current.name === 'done') {
    if (!stats.value || activeDictionary.value?.id !== current.dictionaryId) {
      await loadDone(current.dictionaryId)
    }
  }
}

onMounted(syncRoute)
watch(route, syncRoute)

watch(notice, (value) => {
  if (!value) return
  window.setTimeout(() => {
    if (notice.value === value) notice.value = ''
  }, 2600)
})

function goDictionaries() {
  navigate('/')
}

function handleMode(value: 'card' | 'cloze') {
  mode.value = value
}

function onRestart() {
  const current = route.value
  const dictionaryId = current.name === 'study' || current.name === 'done'
    ? current.dictionaryId
    : activeDictionary.value?.id
  if (dictionaryId) startStudy(dictionaryId)
}
</script>

<template>
  <main class="page">
    <header class="app-header">
      <a class="brand" href="#/" @click.prevent="goDictionaries">
        <span class="brand-mark">W</span>
        <span class="brand-text">
          <strong>英语单词背诵</strong>
          <small>间隔重复 · 每天二十个</small>
        </span>
      </a>
      <div v-if="user" class="user-bar">
        <span class="muted">{{ user.username }}</span>
        <button class="link-button" @click="signOut">退出</button>
      </div>
    </header>

    <p v-if="error" class="error banner" role="alert">
      <span>{{ error }}</span>
      <button class="dismiss" aria-label="关闭提示" @click="clearError">×</button>
    </p>
    <p v-if="notice" class="toast" role="status">{{ notice }}</p>

    <AuthView v-if="route.name === 'auth'" />

    <DictionariesView v-else-if="route.name === 'dictionaries'" />

    <StudyView
      v-else-if="route.name === 'study' && currentItem"
      :item="currentItem"
      :index="index"
      :total="total"
      :mode="mode"
      :loading="loading"
      :dictionary-name="activeDictionary?.name ?? ''"
      :new-learned-today="stats?.today_new ?? 0"
      :new-limit="stats?.new_limit ?? 20"
      :due-reviews="stats?.due_reviews ?? 0"
      @rate="rate"
      @back="goDictionaries"
      @update:mode="handleMode"
    />

    <DoneView
      v-else-if="route.name === 'done'"
      :stats="stats"
      :dictionary-name="activeDictionary?.name ?? ''"
      :completed="completed"
      :reason="reason"
      :loading="loading"
      @restart="onRestart"
      @back="goDictionaries"
    />

    <section v-else class="panel loading-panel" aria-busy="true">
      <p class="muted">正在载入学习进度…</p>
    </section>
  </main>
</template>
