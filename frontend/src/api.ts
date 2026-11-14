const API_BASE = '/api'

export type Rating = 'again' | 'hard' | 'good' | 'easy'
export type RatingPreview = Record<Rating, string>
export type WordFilter = 'all' | 'new' | 'learning' | 'mastered' | 'due' | 'wrong'
export type WordSort = 'alpha' | 'recent' | 'due' | 'wrong'
export type ProgressStatus = 'new' | 'learning' | 'mastered' | 'retired'
export type StudyOrder = 'core' | 'alpha' | 'random'

export type User = { id: number; username: string; email: string; is_staff: boolean }

export type EmailPurpose = 'login' | 'reset' | 'bind'

export type EmailCodeSent = {
  detail: string
  sent: boolean
  expires_in: number
  retry_after: number
}

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

export type AnswerResult = Progress & {
  next_review_label: string
  preview: RatingPreview
  practice?: boolean
  is_new?: boolean
  is_extra?: boolean
  answer_log_id?: number
  duplicate?: boolean
  is_skip?: boolean
}

export type StudyToday = {
  dictionary_id: number
  words: Word[]
  total: number
  /** 今天的实际新词额度：复习积压多时会自动减少，甚至为 0。 */
  new_limit: number
  /** 满额是多少（固定 20），用来显示「10/20」时区分是不是被削减。 */
  new_limit_base: number
  /** 被削减时的中文说明，没削减就是空串。 */
  new_limit_note: string
  new_learned_today: number
  extra_used_today: number
  extra_limit: number
  extra_budget: number
  remaining_new: number
  due_reviews: number
}

export type ReviewToday = { dictionary_id: number; words: Progress[]; total: number; limit: number }

export type ProfileDay = {
  date: string
  new: number
  review: number
  practice: number
  extra: number
  answers: number
}

export type ProfileDictionary = {
  id: number
  name: string
  learned: number
  mastered: number
  due: number
  wrong: number
}

export type ProfileSummary = {
  days: number
  today: ProfileDay
  streak: number
  totals: { answers: number; active_days: number; learned: number; mastered: number; due: number }
  daily: ProfileDay[]
  dictionaries: ProfileDictionary[]
  extra: { used_today: number; limit: number }
}

export type RetentionBucket = {
  label: string
  low: number
  high: number | null
  attempts: number
  kept: number
  rate: number | null
}

export type ProgressPoint = { date: string; learned: number; mastered: number }

export type CalibrationRow = {
  rating: Rating
  label: string
  samples: number
  forgotten: number
  forgotten_rate: number | null
}

export type ProfileInsights = {
  days: number
  start: string
  retention: RetentionBucket[]
  progress: ProgressPoint[]
  calibration: CalibrationRow[]
  sample: { recall_answers: number; pairs: number }
}

export type Statistics = {
  total_words: number
  learned_words: number
  mastered_words: number
  /** 已归档（间隔够长或连对够多，不再进每日复习）的词数。 */
  retired_words: number
  due_reviews: number
  today_completed: number
  today_new: number
  new_limit: number
  remaining_new: number
  progress_percent: number
  next_review_at: string | null
  wrong_words: number
  extra_used_today: number
  extra_limit: number
}

export type WordListRow = {
  id: number
  spelling: string
  phonetic: string
  part_of_speech: string
  meaning: string
  status: ProgressStatus
  interval_days: number
  next_review_at: string | null
  wrong_count: number
  streak: number
}

export type WordList = {
  dictionary: { id: number; name: string; word_count: number }
  enrolled: boolean
  filter: WordFilter
  sort: WordSort
  query: string
  counts: Record<WordFilter, number>
  total: number
  page: number
  page_size: number
  pages: number
  results: WordListRow[]
}

export type AnswerHistoryEntry = {
  id: number
  rating: Rating
  rating_label: string
  created_at: string
  interval_before: number
  interval_after: number
  is_practice: boolean
}

export type WordDetail = Word & {
  dictionary: { id: number; name: string }
  progress: Progress | null
  history: AnswerHistoryEntry[]
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

export async function sendEmailCode(email: string, purpose: EmailPurpose = 'login') {
  await ensureCsrf()
  return request<EmailCodeSent>('/auth/email/send', {
    method: 'POST',
    body: JSON.stringify({ email, purpose }),
    headers: csrfHeaders(),
  })
}

export async function verifyEmailCode(email: string, code: string, purpose: EmailPurpose = 'login') {
  resetCsrf()
  await ensureCsrf()
  const result = await request<{ user: User; created?: boolean }>('/auth/email/verify', {
    method: 'POST',
    body: JSON.stringify({ email, code, purpose }),
    headers: csrfHeaders(),
  })
  resetCsrf()
  return result
}

export async function resetPasswordWithCode(email: string, code: string, password: string) {
  resetCsrf()
  await ensureCsrf()
  const result = await request<{ detail: string; user: User }>('/auth/password/reset', {
    method: 'POST',
    body: JSON.stringify({ email, code, password }),
    headers: csrfHeaders(),
  })
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

export async function studyToday(dictionaryId: number, order: StudyOrder, extra = 0) {
  const suffix = extra > 0 ? `&extra=${extra}` : ''
  return request<StudyToday>(`/study/today?dictionary_id=${dictionaryId}&order=${order}${suffix}`)
}

export async function reviewToday(dictionaryId: number, order: StudyOrder) {
  return request<ReviewToday>(`/review/today?dictionary_id=${dictionaryId}&order=${order}`)
}

export async function answer(
  wordId: number,
  rating: Rating,
  options: { practice?: boolean; clientToken?: string; known?: boolean } = {},
) {
  await ensureCsrf()
  return request<AnswerResult>(`/study/${wordId}/answer`, {
    method: 'POST',
    body: JSON.stringify({
      rating,
      practice: Boolean(options.practice),
      ...(options.clientToken ? { client_token: options.clientToken } : {}),
      ...(options.known ? { known: true } : {}),
    }),
    headers: csrfHeaders(),
  })
}

export async function reviewEarly(dictionaryId: number, order: 'weak' | 'due' | 'random' = 'weak', limit = 20) {
  return request<ReviewToday & { mode: string }>(
    `/review/early?dictionary_id=${dictionaryId}&order=${order}&limit=${limit}`,
  )
}

export async function profileSummary(days = 30) {
  return request<ProfileSummary>(`/profile/summary?days=${days}`)
}

export async function profileInsights(days = 180) {
  return request<ProfileInsights>(`/profile/insights?days=${days}`)
}

export async function statistics(dictionaryId: number) {
  return request<Statistics>(`/statistics?dictionary_id=${dictionaryId}`)
}

export async function dictionaryWords(dictionaryId: number, query: string) {
  const suffix = query ? `?${query}` : ''
  return request<WordList>(`/dictionaries/${dictionaryId}/words${suffix}`)
}

export async function wordDetail(wordId: number) {
  return request<WordDetail>(`/words/${wordId}`)
}

/** 把已归档的词放回复习队列（间隔清零，马上到期）。 */
export async function relearnWord(wordId: number) {
  return request<Progress>(`/words/${wordId}/relearn`, { method: 'POST' })
}

export async function wrongWords(dictionaryId: number, limit = 20) {
  return request<ReviewToday>(`/review/wrong?dictionary_id=${dictionaryId}&limit=${limit}`)
}

export async function undoAnswer(answerLogId: number) {
  await ensureCsrf()
  return request<{ detail: string; word_id: number; deleted_progress: boolean }>(
    `/answers/${answerLogId}/undo`,
    { method: 'POST', headers: csrfHeaders() },
  )
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
