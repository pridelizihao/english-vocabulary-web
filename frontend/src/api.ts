const API_BASE = '/api'

export type Rating = 'again' | 'hard' | 'good' | 'easy'
export type RatingPreview = Record<Rating, string>

export type User = { id: number; username: string; is_staff: boolean }

export type Dictionary = {
  id: number
  name: string
  description: string
  level: string
  version: string
  status: string
  created_at: string
  word_count: number
  learned_words: number
  due_reviews: number
  is_personal: boolean
  is_owned: boolean
}

export type Word = {
  id: number
  dictionary: number
  spelling: string
  phonetic: string
  pronunciation_url: string
  part_of_speech: string
  meaning: string
  example: string
  example_translation: string
  audio_url: string
  preview: RatingPreview
}

export type Progress = {
  id: number
  word: Word
  status: 'new' | 'learning' | 'mastered'
  review_count: number
  wrong_count: number
  streak: number
  ease: number
  next_review_at: string
  last_review_at: string | null
  first_learned_at: string | null
  interval_days: number
}

export type AnswerResult = Progress & { next_review_label: string; preview: RatingPreview }

export type StudyToday = {
  dictionary_id: number
  words: Word[]
  total: number
  new_limit: number
  new_learned_today: number
  remaining_new: number
  due_reviews: number
}

export type ReviewToday = { dictionary_id: number; words: Progress[]; total: number; limit: number }

export type Statistics = {
  total_words: number
  learned_words: number
  mastered_words: number
  due_reviews: number
  today_completed: number
  today_new: number
  new_limit: number
  remaining_new: number
  progress_percent: number
  next_review_at: string | null
}

export type ImportSummary = {
  dictionary_id: number
  name: string
  dictionary_created: boolean
  total_rows: number
  created: number
  updated: number
  skipped: number
  merged: number
  errors: { line: number; error: string }[]
}

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

const STATUS_FALLBACK: Record<number, string> = {
  401: '登录状态已过期，请重新登录',
  403: '没有权限进行这个操作',
  404: '请求的内容不存在',
  429: '操作太频繁了，请稍后再试',
}

function fallbackMessage(status: number) {
  if (status >= 500) return '服务器出错了，请稍后再试'
  return STATUS_FALLBACK[status] ?? `请求失败（${status}）`
}

function csrfToken() {
  return document.cookie.split('; ').find((item) => item.startsWith('csrftoken='))?.split('=')[1] ?? ''
}

let csrfReady: Promise<void> | null = null

export function resetCsrf() {
  csrfReady = null
}

async function request<T>(path: string, options: RequestInit = {}, timeoutMs = 30000): Promise<T> {
  const isForm = options.body instanceof FormData
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...options,
      credentials: 'include',
      signal: controller.signal,
      headers: {
        ...(isForm ? {} : { 'Content-Type': 'application/json' }),
        ...(options.headers ?? {}),
      },
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError('请求超时了，请检查网络或稍后重试', 0)
    }
    throw new ApiError('网络连接失败，请确认后端服务已启动', 0)
  } finally {
    window.clearTimeout(timer)
  }

  const payload = response.status === 204 ? null : await response.json().catch(() => null)
  if (!response.ok) {
    const detail = payload && typeof payload === 'object' && typeof (payload as { detail?: unknown }).detail === 'string'
      ? (payload as { detail: string }).detail
      : ''
    throw new ApiError(detail || fallbackMessage(response.status), response.status)
  }
  return payload as T
}

async function ensureCsrf() {
  if (!csrfReady) {
    csrfReady = request<{ detail: string }>('/auth/csrf').then(() => undefined).catch((error) => {
      csrfReady = null
      throw error
    })
  }
  return csrfReady
}

function csrfHeaders(): Record<string, string> {
  return { 'X-CSRFToken': csrfToken() }
}

export async function login(username: string, password: string) {
  resetCsrf()
  await ensureCsrf()
  const result = await request<{ user: User }>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
    headers: csrfHeaders(),
  })
  resetCsrf()
  return result
}

export async function register(username: string, password: string) {
  resetCsrf()
  await ensureCsrf()
  const result = await request<{ user: User }>('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
    headers: csrfHeaders(),
  })
  resetCsrf()
  return result
}

export async function me() {
  return request<{ user: User }>('/auth/me')
}

export async function logout() {
  await ensureCsrf()
  const result = await request<{ detail: string }>('/auth/logout', { method: 'POST', headers: csrfHeaders() })
  resetCsrf()
  return result
}

export async function dictionaries() {
  return request<Dictionary[]>('/dictionaries/')
}

export async function enroll(dictionaryId: number) {
  await ensureCsrf()
  return request(`/dictionaries/${dictionaryId}/enroll`, { method: 'POST', headers: csrfHeaders() })
}

export async function deleteDictionary(dictionaryId: number) {
  await ensureCsrf()
  return request<{ detail: string }>(`/dictionaries/${dictionaryId}/`, {
    method: 'DELETE',
    headers: csrfHeaders(),
  })
}

export async function studyToday(dictionaryId: number, order: 'alpha' | 'random') {
  return request<StudyToday>(`/study/today?dictionary_id=${dictionaryId}&order=${order}`)
}

export async function reviewToday(dictionaryId: number, order: 'alpha' | 'random') {
  return request<ReviewToday>(`/review/today?dictionary_id=${dictionaryId}&order=${order}`)
}

export async function answer(wordId: number, rating: Rating) {
  await ensureCsrf()
  return request<AnswerResult>(`/study/${wordId}/answer`, {
    method: 'POST',
    body: JSON.stringify({ rating }),
    headers: csrfHeaders(),
  })
}

export async function statistics(dictionaryId: number) {
  return request<Statistics>(`/statistics?dictionary_id=${dictionaryId}`)
}

export async function importPersonalDictionary(name: string, file: File) {
  await ensureCsrf()
  const body = new FormData()
  if (name.trim()) body.append('name', name.trim())
  body.append('file', file)
  return request<ImportSummary>('/dictionaries/import', {
    method: 'POST',
    body,
    headers: csrfHeaders(),
  }, 120000)
}

export async function importOfficialDictionary(dictionaryId: number, file: File) {
  await ensureCsrf()
  const body = new FormData()
  body.append('dictionary_id', String(dictionaryId))
  body.append('file', file)
  return request<ImportSummary>('/admin/dictionaries/import', {
    method: 'POST',
    body,
    headers: csrfHeaders(),
  }, 120000)
}
