import { onBeforeUnmount, onMounted, ref } from 'vue'

import { englishVoice, onlineSpeechUrl } from '../lib/speech'

const NO_AUDIO_MESSAGE = '朗读失败：浏览器没有放出声音（可能被拦截，或没有可用的英文语音）'
const SENTENCE_FAILED_MESSAGE = '例句语音暂时没读出来，稍后再试'
const LOCAL_VOICE_TIMEOUT = 900
const AUDIO_TIMEOUT = 4000
const AUDIO_CACHE_SIZE = 8

/**
 * Speak one word. Order: provided audio (dictionary / pronunciation URL) →
 * system English voice → online fallback. Shared by the study card, the cloze
 * mode and the word detail page so the fallback chain stays in one place.
 *
 * Audio elements are preloaded ahead of time (`prefetch`) and reused, so the
 * second play — and the online fallback after a slow voice — starts instantly.
 */
export function useSpeech() {
  const message = ref('')
  const busy = ref(false)
  const sentenceBusy = ref(false)
  const availableVoices = ref<SpeechSynthesisVoice[]>([])
  const available = typeof window !== 'undefined' && 'speechSynthesis' in window
  const audioCache = new Map<string, HTMLAudioElement>()
  let player: HTMLAudioElement | null = null

  function refreshVoices() {
    if (!available) return
    try {
      availableVoices.value = window.speechSynthesis.getVoices()
    } catch {
      availableVoices.value = []
    }
  }

  /** Buffer an audio URL without playing it (autoplay rules don't apply). */
  function preload(url: string | null | undefined) {
    if (!url || audioCache.has(url)) return
    try {
      const audio = new Audio()
      audio.preload = 'auto'
      audio.src = url
      audio.load()
      audioCache.set(url, audio)
      if (audioCache.size > AUDIO_CACHE_SIZE) {
        const oldest = audioCache.keys().next().value
        if (oldest) audioCache.delete(oldest)
      }
    } catch {
      // 浏览器可能禁用音频，忽略即可，真正播放时会再试
    }
  }

  /** Warm the cache for the word about to be shown. */
  function prefetch(spelling: string, providedUrls: (string | null | undefined)[] = []) {
    for (const url of providedUrls) preload(url)
    preload(onlineSpeechUrl(spelling))
  }

  function stop() {
    if (player) {
      try {
        player.pause()
        player.currentTime = 0
      } catch {
        // 元素还没加载出元数据时忽略
      }
      player = null
    }
    if (available) {
      try {
        window.speechSynthesis.cancel()
      } catch {
        // 浏览器可能禁用 speechSynthesis，忽略即可
      }
    }
  }

  function playUrl(url: string, timeout = AUDIO_TIMEOUT) {
    return new Promise<boolean>((resolve) => {
      try {
        let audio = audioCache.get(url)
        if (!audio) {
          preload(url)
          audio = audioCache.get(url)
        }
        if (!audio) {
          resolve(false)
          return
        }
        player = audio
        let settled = false
        let timer = 0
        const finish = (ok: boolean) => {
          if (settled) return
          settled = true
          window.clearTimeout(timer)
          resolve(ok)
        }
        timer = window.setTimeout(() => finish(false), timeout)
        audio.onerror = () => finish(false)
        try {
          audio.pause()
          audio.currentTime = 0
        } catch {
          // 未加载完成时设置 currentTime 会抛错，忽略
        }
        audio.play().then(() => finish(true)).catch(() => finish(false))
      } catch {
        resolve(false)
      }
    })
  }

  function speakLocally(spelling: string) {
    return new Promise<boolean>((resolve) => {
      if (!available) {
        resolve(false)
        return
      }
      const voice = englishVoice(availableVoices.value)
      // 没有英文语音时不硬试，直接走在线发音。
      if (!voice) {
        resolve(false)
        return
      }
      const synth = window.speechSynthesis
      const utterance = new SpeechSynthesisUtterance(spelling)
      utterance.voice = voice
      utterance.lang = voice.lang || 'en-US'
      utterance.rate = 0.9
      let settled = false
      let timer = 0
      const finish = (ok: boolean) => {
        if (settled) return
        settled = true
        window.clearTimeout(timer)
        if (!ok) {
          try {
            synth.cancel()
          } catch {
            // 已停止或浏览器不支持，忽略
          }
        }
        resolve(ok)
      }
      timer = window.setTimeout(() => finish(false), LOCAL_VOICE_TIMEOUT)
      utterance.onstart = () => finish(true)
      utterance.onerror = () => finish(false)
      try {
        synth.speak(utterance)
      } catch {
        finish(false)
      }
    })
  }

  /** System voice for one sentence; resolves false when nothing starts. */
  function speakSentenceLocally(text: string) {
    if (!available) return Promise.resolve(false)
    const voice = englishVoice(availableVoices.value)
    if (!voice) return Promise.resolve(false)
    return new Promise<boolean>((resolve) => {
      const synth = window.speechSynthesis
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.voice = voice
      utterance.lang = voice.lang || 'en-US'
      utterance.rate = 0.95
      let settled = false
      let timer = 0
      const finish = (ok: boolean) => {
        if (settled) return
        settled = true
        window.clearTimeout(timer)
        if (!ok) {
          try {
            synth.cancel()
          } catch {
            // 浏览器可能禁用 speechSynthesis，忽略
          }
        }
        resolve(ok)
      }
      timer = window.setTimeout(() => finish(false), 1500)
      utterance.onstart = () => finish(true)
      utterance.onerror = () => finish(false)
      try {
        synth.speak(utterance)
      } catch {
        finish(false)
      }
    })
  }

  async function speakSentence(text: string, fallbackUrl?: string) {
    const trimmed = text.trim()
    if (!trimmed) return false
    message.value = ''
    stop()
    sentenceBusy.value = true
    try {
      if (await speakSentenceLocally(trimmed)) return true
      // The server caches an edge-tts MP3 for the sentence; first play may take
      // a couple of seconds, later plays are instant.
      if (fallbackUrl && (await playUrl(fallbackUrl, 15000))) return true
      message.value = SENTENCE_FAILED_MESSAGE
      return false
    } finally {
      sentenceBusy.value = false
    }
  }

  async function speak(spelling: string, providedUrls: (string | null | undefined)[] = []) {
    message.value = ''
    stop()
    busy.value = true
    try {
      // Start buffering the online fallback immediately: if the local voice is
      // slow to start, the fallback then has nothing to download.
      const online = onlineSpeechUrl(spelling)
      for (const url of providedUrls) preload(url)
      preload(online)

      for (const url of providedUrls) {
        if (url && (await playUrl(url))) return true
      }
      if (await speakLocally(spelling)) return true
      if (await playUrl(online)) return true
      message.value = NO_AUDIO_MESSAGE
      return false
    } finally {
      busy.value = false
    }
  }

  onMounted(() => {
    if (!available) return
    refreshVoices()
    window.speechSynthesis.addEventListener('voiceschanged', refreshVoices)
  })

  onBeforeUnmount(() => {
    if (available) window.speechSynthesis.removeEventListener('voiceschanged', refreshVoices)
    stop()
  })

  return { speak, speakSentence, stop, prefetch, message, busy, sentenceBusy, available }
}
