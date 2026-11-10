<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { WordFilter, WordList, WordSort } from '../api'
import { useSession } from '../composables/useSession'
import { navigate, replace, route } from '../lib/router'
import { primaryMeaning } from '../lib/study'
import {
  WORD_FILTERS,
  WORD_SORTS,
  browseMemory,
  buildWordsQuery,
  clampPage,
  isWordFilter,
  isWordSort,
  primaryPos,
  statusLabel,
} from '../lib/words'

const props = defineProps<{ dictionaryId: number }>()

const { loadWords, loading, startStudy, startWrong } = useSession()

const initial = new URLSearchParams(route.value.name === 'words' ? route.value.query : '')
const q = ref(initial.get('q') ?? '')
const filter = ref<WordFilter>(isWordFilter(initial.get('filter')) ? (initial.get('filter') as WordFilter) : 'all')
const sort = ref<WordSort>(isWordSort(initial.get('sort')) ? (initial.get('sort') as WordSort) : 'alpha')
const page = ref(clampPage(Number(initial.get('page') ?? 1), 9999))
const data = ref<WordList | null>(null)

let requestSeq = 0
let debounce = 0

function queryString() {
  return buildWordsQuery({ q: q.value, filter: filter.value, sort: sort.value, page: page.value })
}

async function load() {
  const seq = (requestSeq += 1)
  const query = queryString()
  browseMemory[props.dictionaryId] = query
  replace({ name: 'words', dictionaryId: props.dictionaryId, query })
  const result = await loadWords(props.dictionaryId, query)
  if (seq !== requestSeq) return
  data.value = result
  if (result && result.page !== page.value) page.value = result.page
}

// The hash is the source of truth when someone edits it or follows a deep
// link; local state changes go through the handlers below instead.
watch(
  () => (route.value.name === 'words' ? route.value.query : null),
  (query) => {
    if (query === null) return
    const params = new URLSearchParams(query)
    const nextQuery = params.get('q') ?? ''
    const nextFilter = isWordFilter(params.get('filter')) ? (params.get('filter') as WordFilter) : 'all'
    const nextSort = isWordSort(params.get('sort')) ? (params.get('sort') as WordSort) : 'alpha'
    const nextPage = clampPage(Number(params.get('page') ?? 1), 9999)
    if (nextQuery === q.value && nextFilter === filter.value && nextSort === sort.value && nextPage === page.value) {
      return
    }
    q.value = nextQuery
    filter.value = nextFilter
    sort.value = nextSort
    page.value = nextPage
    load()
  },
)

watch(q, () => {
  window.clearTimeout(debounce)
  debounce = window.setTimeout(() => {
    page.value = 1
    load()
  }, 300)
})

watch(
  () => props.dictionaryId,
  () => {
    q.value = ''
    filter.value = 'all'
    sort.value = 'alpha'
    page.value = 1
    load()
  },
)

function setFilter(value: WordFilter) {
  if (filter.value === value) return
  filter.value = value
  page.value = 1
  load()
}

function applySort() {
  page.value = 1
  load()
}

function goPage(target: number) {
  const next = clampPage(target, data.value?.pages ?? 1)
  if (next === page.value) return
  page.value = next
  load()
}

onMounted(load)
onBeforeUnmount(() => window.clearTimeout(debounce))
</script>

<template>
  <section class="content-section words-section">
    <div class="hero words-hero">
      <div>
        <button class="link-button back" @click="navigate('/')">← 词典列表</button>
        <p class="eyebrow">{{ data?.dictionary.name || '词表' }}</p>
        <h2>浏览与搜索</h2>
        <p class="lede">
          共 {{ data?.dictionary.word_count ?? 0 }} 个单词
          <template v-if="data"> · 当前筛选 {{ data.total }} 个</template>
        </p>
      </div>
      <button v-if="data" class="primary" :disabled="loading" @click="startStudy(props.dictionaryId)">
        {{ data.enrolled ? '继续学习' : '开始学习这本词典' }}
      </button>
    </div>

    <div class="word-toolbar">
      <label class="search-field">
        <span class="sr-only">搜索单词</span>
        <input v-model="q" type="search" maxlength="50" placeholder="搜索拼写或中文释义" />
      </label>
      <label class="sort-field">
        <span class="muted">排序</span>
        <select v-model="sort" @change="applySort">
          <option v-for="option in WORD_SORTS" :key="option.value" :value="option.value">{{ option.label }}</option>
        </select>
      </label>
    </div>

    <div class="filter-chips" role="group" aria-label="按学习状态筛选">
      <button
        v-for="chip in WORD_FILTERS"
        :key="chip.value"
        :class="{ active: filter === chip.value }"
        :aria-pressed="filter === chip.value"
        @click="setFilter(chip.value)"
      >
        {{ chip.label }}
        <span v-if="data" class="chip-count">{{ data.counts[chip.value] }}</span>
      </button>
      <button
        v-if="filter === 'wrong' && data && data.total > 0"
        class="primary chip-action"
        :disabled="loading"
        @click="startWrong(props.dictionaryId)"
      >
        练这些错词
      </button>
    </div>

    <div v-if="loading && !data" class="panel loading-panel" aria-busy="true">
      <p class="muted">正在加载词表…</p>
    </div>

    <div v-else-if="data && data.results.length" class="word-list">
      <a
        v-for="row in data.results"
        :key="row.id"
        class="word-item"
        :href="`#/words/${props.dictionaryId}/${row.id}`"
      >
        <span class="word-main">
          <strong>{{ row.spelling }}</strong>
          <span v-if="row.phonetic" class="phonetic">{{ row.phonetic }}</span>
          <span v-if="row.part_of_speech" class="pos">{{ primaryPos(row.part_of_speech) }}</span>
        </span>
        <span class="word-meaning">{{ primaryMeaning(row.meaning, 60) }}</span>
        <span class="word-status" :class="row.status">{{ statusLabel(row.status) }}</span>
      </a>
    </div>

    <p v-else-if="data" class="empty panel">
      <template v-if="q">没有找到包含「{{ q }}」的单词，换个拼写或中文释义试试。</template>
      <template v-else-if="filter !== 'all'">这个筛选下还没有单词。</template>
      <template v-else>这本词典还没有单词，可以先导入自己的词表。</template>
    </p>

    <div v-if="data && data.pages > 1" class="pagination">
      <button :disabled="loading || data.page <= 1" @click="goPage(data.page - 1)">上一页</button>
      <span class="muted">第 {{ data.page }} / {{ data.pages }} 页</span>
      <button :disabled="loading || data.page >= data.pages" @click="goPage(data.page + 1)">下一页</button>
    </div>
  </section>
</template>