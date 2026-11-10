import type { WordFilter, WordSort } from '../api'

export type WordsQueryState = {
  q: string
  filter: WordFilter
  sort: WordSort
  page: number
}

export const WORD_FILTERS: { value: WordFilter; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'new', label: '未学' },
  { value: 'learning', label: '学习中' },
  { value: 'mastered', label: '已掌握' },
  { value: 'due', label: '待复习' },
  { value: 'wrong', label: '易错' },
]

export const WORD_SORTS: { value: WordSort; label: string }[] = [
  { value: 'alpha', label: '字母顺序' },
  { value: 'recent', label: '最近学习' },
  { value: 'due', label: '最快到期' },
  { value: 'wrong', label: '错得最多' },
]

export const STATUS_LABELS: Record<string, string> = {
  new: '未学',
  learning: '学习中',
  mastered: '已掌握',
}

/** Last list query per dictionary, so the detail page can return to it. */
export const browseMemory: Record<number, string> = {}

export function isWordFilter(value: unknown): value is WordFilter {
  return WORD_FILTERS.some((item) => item.value === value)
}

export function isWordSort(value: unknown): value is WordSort {
  return WORD_SORTS.some((item) => item.value === value)
}

/** Query string for /api/dictionaries/{id}/words; defaults are omitted. */
export function buildWordsQuery(state: Partial<WordsQueryState>): string {
  const params = new URLSearchParams()
  const q = (state.q ?? '').trim()
  if (q) params.set('q', q)
  if (state.filter && state.filter !== 'all') params.set('filter', state.filter)
  if (state.sort && state.sort !== 'alpha') params.set('sort', state.sort)
  const page = Math.floor(state.page ?? 1)
  if (Number.isFinite(page) && page > 1) params.set('page', String(page))
  return params.toString()
}

export function clampPage(page: number, pages: number) {
  const total = Math.max(1, Math.floor(pages) || 1)
  if (!Number.isFinite(page)) return 1
  return Math.min(Math.max(1, Math.floor(page)), total)
}

const TOKEN_ALPHABET = 'abcdefghijklmnopqrstuvwxyz0123456789'

/**
 * Idempotency token for one answer attempt. `crypto.randomUUID` only exists in
 * secure contexts and the app is served over plain HTTP, so use getRandomValues
 * (which is available on insecure origins) and fall back to Math.random.
 */
export function randomToken(length = 32) {
  const size = Math.max(8, Math.floor(length) || 32)
  let out = ''
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    const buffer = new Uint8Array(size)
    crypto.getRandomValues(buffer)
    for (let index = 0; index < size; index += 1) {
      out += TOKEN_ALPHABET[buffer[index] % TOKEN_ALPHABET.length]
    }
    return out
  }
  for (let index = 0; index < size; index += 1) {
    out += TOKEN_ALPHABET[Math.floor(Math.random() * TOKEN_ALPHABET.length)]
  }
  return out
}

export function statusLabel(status: string) {
  return STATUS_LABELS[status] ?? '未学'
}

/** Dictionaries store "n.;vt.;[计]" — the list only needs the first tag. */
export function primaryPos(value: string) {
  const [first] = (value || '').split(';')
  return (first ?? '').trim()
}

/** Short local timestamp for the answer history list. */
export function formatMoment(iso: string) {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}