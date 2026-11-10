import { computed, ref, watch } from 'vue'

import * as api from '../api'
import { navigate } from '../lib/router'
import {
  buildQueue,
  requeueAgain,
  type StudyItem,
} from '../lib/study'

type Mode = 'card' | 'cloze'
type Order = 'alpha' | 'random'

const MODE_KEY = 'vocab.mode'
const ORDER_KEY = 'vocab.order'

function readStored<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const value = window.localStorage.getItem(key)
    return allowed.includes(value as T) ? (value as T) : fallback
  } catch {
    return fallback
  }
}

function store(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    /* storage can be blocked; the choice just won't persist */
  }
}

const user = ref<api.User | null>(null)
const dictionaries = ref<api.Dictionary[]>([])
const activeDictionary = ref<api.Dictionary | null>(null)
const queue = ref<StudyItem[]>([])
const index = ref(0)
const completed = ref(0)
const stats = ref<api.Statistics | null>(null)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const importResult = ref<api.ImportSummary | null>(null)
const mode = ref<Mode>(readStored<Mode>(MODE_KEY, ['card', 'cloze'], 'card'))
const order = ref<Order>(readStored<Order>(ORDER_KEY, ['alpha', 'random'], 'alpha'))
const bootstrapped = ref(false)

const currentItem = computed<StudyItem | null>(() => queue.value[index.value] ?? null)
const total = computed(() => queue.value.length)

watch(mode, (value) => store(MODE_KEY, value))
watch(order, (value) => store(ORDER_KEY, value))

function setError(value: unknown) {
  error.value = value instanceof Error ? value.message : '操作失败，请稍后重试'
  if (value instanceof api.ApiError && value.status === 401) {
    user.value = null
    navigate('/auth')
  }
}

function clearMessages() {
  error.value = ''
  notice.value = ''
}

function clearError() {
  error.value = ''
}

function resetSession() {
  queue.value = []
  index.value = 0
  completed.value = 0
  stats.value = null
  activeDictionary.value = null
}

async function bootstrap() {
  clearError()
  try {
    const result = await api.me()
    user.value = result.user
    await loadDictionaries()
  } catch {
    user.value = null
    dictionaries.value = []
  } finally {
    bootstrapped.value = true
  }
  return Boolean(user.value)
}

async function loadDictionaries() {
  dictionaries.value = await api.dictionaries()
  if (activeDictionary.value) {
    const fresh = dictionaries.value.find((item) => item.id === activeDictionary.value?.id)
    activeDictionary.value = fresh ?? null
  }
}

async function signIn(username: string, password: string) {
  loading.value = true
  clearMessages()
  try {
    const result = await api.login(username, password)
    user.value = result.user
    await loadDictionaries()
    navigate('/')
    return true
  } catch (cause) {
    setError(cause)
    return false
  } finally {
    loading.value = false
  }
}

async function signUp(username: string, password: string) {
  loading.value = true
  clearMessages()
  try {
    const result = await api.register(username, password)
    user.value = result.user
    await loadDictionaries()
    navigate('/')
    return true
  } catch (cause) {
    setError(cause)
    return false
  } finally {
    loading.value = false
  }
}

async function signOut() {
  await api.logout().catch(() => undefined)
  user.value = null
  dictionaries.value = []
  resetSession()
  clearMessages()
  navigate('/auth')
}

async function startStudy(dictionaryId: number) {
  loading.value = true
  clearMessages()
  try {
    if (!dictionaries.value.length) await loadDictionaries()
    const dictionary = dictionaries.value.find((item) => item.id === dictionaryId)
    if (!dictionary) {
      setError(new Error('这本词典不存在，或者已经被删除了'))
      navigate('/')
      return false
    }
    activeDictionary.value = dictionary
    await api.enroll(dictionaryId)
    const [study, review, currentStats] = await Promise.all([
      api.studyToday(dictionaryId, order.value),
      api.reviewToday(dictionaryId, order.value),
      api.statistics(dictionaryId),
    ])
    queue.value = buildQueue(review.words, study.words)
    index.value = 0
    completed.value = 0
    stats.value = currentStats
    if (!queue.value.length) {
      navigate(`/done/${dictionaryId}`)
    } else {
      navigate(`/study/${dictionaryId}`)
    }
    return true
  } catch (cause) {
    setError(cause)
    return false
  } finally {
    loading.value = false
  }
}

async function rate(rating: api.Rating) {
  const item = currentItem.value
  if (!item || loading.value) return
  loading.value = true
  clearError()
  try {
    const result = await api.answer(item.word.id, rating)
    completed.value += 1
    notice.value = result.next_review_label
    if (stats.value) {
      const isNew = item.kind === 'new' && item.repeats === 0
      const learned = stats.value.learned_words + (isNew ? 1 : 0)
      stats.value = {
        ...stats.value,
        learned_words: learned,
        today_new: stats.value.today_new + (isNew ? 1 : 0),
        today_completed: stats.value.today_completed + 1,
        remaining_new: Math.max(stats.value.remaining_new - (isNew ? 1 : 0), 0),
        progress_percent: stats.value.total_words
          ? Math.round((learned / stats.value.total_words) * 1000) / 10
          : 0,
      }
    }
    if (rating === 'again') queue.value = requeueAgain(queue.value, item)
    if (index.value + 1 >= queue.value.length) {
      stats.value = await api.statistics(item.word.dictionary)
      navigate(`/done/${item.word.dictionary}`)
    } else {
      index.value += 1
    }
  } catch (cause) {
    setError(cause)
  } finally {
    loading.value = false
  }
}

async function loadDone(dictionaryId: number) {
  loading.value = true
  clearError()
  try {
    if (!dictionaries.value.length) await loadDictionaries()
    const dictionary = dictionaries.value.find((item) => item.id === dictionaryId)
    if (!dictionary) {
      navigate('/')
      return
    }
    activeDictionary.value = dictionary
    stats.value = await api.statistics(dictionaryId)
  } catch (cause) {
    setError(cause)
    navigate('/')
  } finally {
    loading.value = false
  }
}

async function deleteDictionary(dictionaryId: number) {
  loading.value = true
  clearMessages()
  try {
    const result = await api.deleteDictionary(dictionaryId)
    if (activeDictionary.value?.id === dictionaryId) resetSession()
    await loadDictionaries()
    notice.value = result.detail
    return true
  } catch (cause) {
    setError(cause)
    return false
  } finally {
    loading.value = false
  }
}

async function importPersonal(name: string, file: File) {
  loading.value = true
  clearMessages()
  importResult.value = null
  try {
    const summary = await api.importPersonalDictionary(name, file)
    importResult.value = summary
    await loadDictionaries()
    return summary
  } catch (cause) {
    setError(cause)
    return null
  } finally {
    loading.value = false
  }
}

export function useSession() {
  return {
    user,
    dictionaries,
    activeDictionary,
    queue,
    index,
    completed,
    stats,
    loading,
    error,
    notice,
    importResult,
    mode,
    order,
    bootstrapped,
    currentItem,
    total,
    bootstrap,
    loadDictionaries,
    signIn,
    signUp,
    signOut,
    startStudy,
    rate,
    loadDone,
    deleteDictionary,
    importPersonal,
    resetSession,
    clearError,
    clearMessages,
    reportError: setError,
  }
}
