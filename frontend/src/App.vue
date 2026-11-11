<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'

import { useSession } from './composables/useSession'
import { doneReason } from './lib/study'
import { navigate, route } from './lib/router'
import AuthView from './views/AuthView.vue'
import DictionariesView from './views/DictionariesView.vue'
import DoneView from './views/DoneView.vue'
import ProfileView from './views/ProfileView.vue'
import StudyView from './views/StudyView.vue'
import WordDetailView from './views/WordDetailView.vue'
import WordsView from './views/WordsView.vue'

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
  startReview,
  startWrong,
  loadProfile,
  rate,
  markKnown,
  undo,
  canUndo,
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
    // Always refresh: the cards show per-user progress, which changes after a
    // study session or an import, so a cached list goes stale immediately.
    try {
      await loadDictionaries()
    } catch (cause) {
      reportError(cause)
    }
  } else if (current.name === 'study') {
    if (activeDictionary.value?.id !== current.dictionaryId || !currentItem.value) {
      await startStudy(current.dictionaryId)
    }
  } else if (current.name === 'done') {
    // Stats change while studying, so always refresh instead of reusing the
    // snapshot captured when the session started.
    await loadDone(current.dictionaryId)
  } else if (current.name === 'profile') {
    await loadProfile(371)
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

function currentDictionaryId() {
  const current = route.value
  if (current.name === 'study' || current.name === 'done') return current.dictionaryId
  return activeDictionary.value?.id
}

function goProfile() {
  navigate('/profile')
}

function onExtra() {
  const dictionaryId = currentDictionaryId()
  if (dictionaryId) startStudy(dictionaryId, { extra: 20 })
}

function onReview() {
  const dictionaryId = currentDictionaryId()
  if (!dictionaryId) return
  startReview(dictionaryId, stats.value && stats.value.due_reviews > 0 ? 'due' : 'early')
}

function onWrong() {
  const dictionaryId = currentDictionaryId()
  if (dictionaryId) startWrong(dictionaryId)
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
        <button class="link-button user-link" @click="goProfile">{{ user.username }}</button>
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

    <WordsView v-else-if="route.name === 'words'" :dictionary-id="route.dictionaryId" />

    <WordDetailView
      v-else-if="route.name === 'word'"
      :dictionary-id="route.dictionaryId"
      :word-id="route.wordId"
    />

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
      :can-undo="canUndo"
      @rate="rate"
      @undo="undo"
      @known="markKnown"
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
      @extra="onExtra"
      @review="onReview"
      @wrong="onWrong"
      @back="goDictionaries"
    />

    <ProfileView v-else-if="route.name === 'profile'" />

    <section v-else class="panel loading-panel" aria-busy="true">
      <p class="muted">正在载入学习进度…</p>
    </section>
  </main>
</template>
