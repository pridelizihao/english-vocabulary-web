const API_BASE = '/api'

function csrfToken() {
  return document.cookie.split('; ').find((item) => item.startsWith('csrftoken='))?.split('=')[1] ?? ''
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const isForm = options.body instanceof FormData
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: 'include',
    headers: { ...(isForm ? {} : { 'Content-Type': 'application/json' }), ...(options.headers ?? {}) },
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(payload.detail ?? '请求失败，请稍后重试')
  return payload as T
}

export type User = { id: number; username: string; is_staff?: boolean }
export type Dictionary = { id: number; name: string; description: string; level: string; version: string; word_count: number }
export type Word = { id: number; dictionary: number; spelling: string; phonetic: string; meaning: string; example: string; audio_url: string; cloze: string }
export type StudyResponse = { dictionary_id: number; words: Word[]; total: number; completed_today: number; remaining_new: number }
export type Progress = { id: number; word: Word; status: string; review_count: number; wrong_count: number; next_review_at: string; last_review_at: string | null; interval_days: number }

export async function prepareCsrf() { await request('/auth/csrf', { method: 'GET' }) }
export async function login(username: string, password: string) { await prepareCsrf(); return request<{ user: User }>('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }), headers: { 'X-CSRFToken': csrfToken() } }) }
export async function register(username: string, password: string) { await prepareCsrf(); return request<{ user: User }>('/auth/register', { method: 'POST', body: JSON.stringify({ username, password }), headers: { 'X-CSRFToken': csrfToken() } }) }
export async function me() { return request<{ user: User }>('/auth/me') }
export async function logout() { await prepareCsrf(); return request<{ detail: string }>('/auth/logout', { method: 'POST', headers: { 'X-CSRFToken': csrfToken() } }) }
export async function dictionaries() { return request<Dictionary[]>('/dictionaries/') }
export async function enroll(dictionaryId: number) { await prepareCsrf(); return request(`/dictionaries/${dictionaryId}/enroll`, { method: 'POST', headers: { 'X-CSRFToken': csrfToken() } }) }
export async function studyToday(dictionaryId: number, order: 'alpha' | 'random') { return request<StudyResponse>(`/study/today?dictionary_id=${dictionaryId}&order=${order}`) }
export async function reviewToday(dictionaryId: number, order: 'alpha' | 'random') { return request<{ words: Progress[] }>(`/review/today?dictionary_id=${dictionaryId}&order=${order}`) }
export async function answer(wordId: number, rating: string) { await prepareCsrf(); return request(`/study/${wordId}/answer`, { method: 'POST', body: JSON.stringify({ rating }), headers: { 'X-CSRFToken': csrfToken() } }) }
export async function statistics(dictionaryId: number) { return request<{ total_words: number; learned_words: number; mastered_words: number; due_reviews: number; today_completed: number; progress_percent: number }>(`/statistics?dictionary_id=${dictionaryId}`) }
export async function importDictionary(dictionaryId: number, file: File) {
  await prepareCsrf()
  const body = new FormData(); body.append('dictionary_id', String(dictionaryId)); body.append('file', file)
  return request('/admin/dictionaries/import', { method: 'POST', body, headers: { 'X-CSRFToken': csrfToken() } })
}
export async function importPersonalDictionary(name: string, file: File) {
  await prepareCsrf(); const body = new FormData(); body.append('name', name); body.append('file', file)
  return request<{ dictionary_id: number; name: string; created: number; skipped: number }>('/dictionaries/import', { method: 'POST', body, headers: { 'X-CSRFToken': csrfToken() } })
}
