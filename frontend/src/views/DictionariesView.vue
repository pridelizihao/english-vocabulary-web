<script setup lang="ts">
import { ref } from 'vue'

import type { ImportSummary } from '../api'
import { useSession } from '../composables/useSession'
import { progressPercent } from '../lib/study'

const {
  dictionaries,
  loading,
  order,
  importResult,
  startStudy,
  deleteDictionary,
  importPersonal,
} = useSession()

const dictName = ref('')
const file = ref<File | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const localError = ref('')
const confirmingId = ref<number | null>(null)
const deletingId = ref<number | null>(null)

function setOrder(value: 'core' | 'alpha' | 'random') {
  order.value = value
}

function pickFile(event: Event) {
  const input = event.target as HTMLInputElement
  file.value = input.files?.[0] ?? null
  localError.value = ''
}

function resetFile() {
  file.value = null
  if (fileInput.value) fileInput.value.value = ''
}

async function submitImport() {
  localError.value = ''
  if (!file.value) {
    localError.value = '请先选择一个 CSV / JSON / XLSX 文件'
    return
  }
  const summary = await importPersonal(dictName.value, file.value)
  if (summary) resetFile()
}

function summaryText(summary: ImportSummary) {
  const parts = [`导入 ${summary.created} 个新词`, `更新 ${summary.updated} 个`]
  if (summary.skipped) parts.push(`跳过 ${summary.skipped} 行`)
  if (summary.merged) parts.push(`合并重复 ${summary.merged} 行`)
  const firstError = summary.errors[0]
  if (firstError) parts.push(`第 ${firstError.line} 行：${firstError.error}`)
  return parts.join('，')
}

function askRemove(id: number) {
  confirmingId.value = id
}

async function confirmRemove(id: number) {
  deletingId.value = id
  const ok = await deleteDictionary(id)
  deletingId.value = null
  if (ok) confirmingId.value = null
}

function downloadTemplate() {
  const csv = 'word,meaning,phonetic,part_of_speech,example\nabandon,放弃,/əˈbændən/,verb,He abandoned the plan.\n'
  const blob = new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'word-template.csv'
  anchor.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <section class="content-section">
    <div class="hero">
      <div>
        <p class="eyebrow">选择词典</p>
        <h2>今天想背哪一本？</h2>
        <p class="lede">
          每日新词上限 20 个，到期复习会优先排队。已经掌握的词会自动拉开间隔，不必再手动安排。
        </p>
      </div>
      <div class="order-switch" role="group" aria-label="新词顺序" title="考试核心：按 CEFR 等级优先 B1/B2，专有名词排最后">
        <span class="muted">新词顺序</span>
        <button :class="{ active: order === 'core' }" :aria-pressed="order === 'core'" @click="setOrder('core')">
          考试核心
        </button>
        <button :class="{ active: order === 'alpha' }" :aria-pressed="order === 'alpha'" @click="setOrder('alpha')">
          字母
        </button>
        <button :class="{ active: order === 'random' }" :aria-pressed="order === 'random'" @click="setOrder('random')">
          乱序
        </button>
      </div>
    </div>

    <div v-if="loading && !dictionaries.length" class="dictionary-grid" aria-busy="true">
      <div v-for="index in 2" :key="index" class="dictionary-card skeleton">
        <span class="skeleton-line short"></span>
        <span class="skeleton-line"></span>
        <span class="skeleton-line half"></span>
      </div>
    </div>

    <div v-else class="dictionary-grid">
      <article v-for="dictionary in dictionaries" :key="dictionary.id" class="dictionary-card">
        <button class="dictionary-open" :disabled="loading" @click="startStudy(dictionary.id)">
          <span class="tag-row">
            <span class="tag">{{ dictionary.level || (dictionary.is_personal ? '个人词典' : '英语词汇') }}</span>
            <span v-if="dictionary.is_personal" class="tag ghost">个人</span>
          </span>
          <strong>{{ dictionary.name }}</strong>
          <span class="description">{{ dictionary.description || '开始建立你的词汇量' }}</span>
          <span class="card-stats">
            {{ dictionary.word_count }} 词 · 已学 {{ dictionary.learned_words }}
          </span>
          <span class="bar" :aria-label="`已学 ${progressPercent(dictionary.learned_words, dictionary.word_count)}%`">
            <span :style="{ width: `${progressPercent(dictionary.learned_words, dictionary.word_count)}%` }"></span>
          </span>
        </button>
        <div class="card-footer">
          <span v-if="dictionary.due_reviews" class="due-badge">{{ dictionary.due_reviews }} 个待复习</span>
          <span v-else class="muted">暂无到期复习</span>
          <a class="link-button" :href="`#/words/${dictionary.id}`">查看词表</a>
          <template v-if="dictionary.is_owned">
            <template v-if="confirmingId === dictionary.id">
              <span class="muted">确认删除？</span>
              <button class="link-button danger" :disabled="deletingId === dictionary.id" @click="confirmRemove(dictionary.id)">
                {{ deletingId === dictionary.id ? '删除中…' : '删除' }}
              </button>
              <button class="link-button" @click="confirmingId = null">取消</button>
            </template>
            <button v-else class="link-button danger" @click="askRemove(dictionary.id)">删除</button>
          </template>
        </div>
      </article>
    </div>

    <p v-if="!loading && !dictionaries.length" class="empty panel">
      还没有可以学习的词典。可以在下面导入自己的词表，或者在后台发布官方词典。
    </p>

    <section class="import-box">
      <header>
        <strong>导入个人词典</strong>
        <span class="muted">支持 CSV / JSON / XLSX，至少需要 word 和 meaning 两列，只有你自己能看到</span>
      </header>
      <div class="import-row">
        <input v-model="dictName" maxlength="120" placeholder="词典名称（留空则用文件名）" />
        <label class="file-picker">
          <input ref="fileInput" type="file" accept=".csv,.json,.xlsx,.xlsm" @change="pickFile" />
          <span>{{ file?.name || '选择文件' }}</span>
        </label>
        <button class="primary" :disabled="loading || !file" @click="submitImport">
          {{ loading ? '导入中…' : '导入' }}
        </button>
      </div>
      <p v-if="localError" class="error inline">{{ localError }}</p>
      <p v-if="importResult" class="success">{{ summaryText(importResult) }}</p>
      <button class="link-button" @click="downloadTemplate">下载 CSV 模板</button>
    </section>
  </section>
</template>
