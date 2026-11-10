import { onBeforeUnmount, onMounted, ref } from 'vue'

import { englishVoice, onlineSpeechUrl } from '../lib/speech'

const NO_AUDIO_MESSAGE = '朗读失败：浏览器没有放出声音（可能被拦截，或没有可用的英文语音）'

/**
 * Speak one word. Order: provided audio (dictionary / pronunciation URL) →
 * system English voice → online fallback. Shared by the study card, the cloze
 * mode and the word detail page so the fallback chain stays in one place.
 */
export function useSpeech() {
  const message = ref('')
  const availableVoices = ref<SpeechSynthesisVoice[]>([])
  const available = typeof window !== 'undefined' && 'speechSynthesis' in window
  let player: HTMLAudioElement | null = null

  function refreshVoices() {
    if (!available) return
    try {
      availableVoices.value = window.speechSynthesis.getVoices()
    } catch {
      availableVoices.value = []
    }
  }

  function stop() {
    if (player) {
      player.pause()
      player.src = ''
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

  function playUrl(url: string) {
    return new Promise<boolean>((resolve) => {
      try {
        const audio = new Audio(url)
        player = audio
        let settled = false
        let timer = 0
        const finish = (ok: boolean) => {
          if (settled) return
          settled = true
          window.clearTimeout(timer)
          resolve(ok)
        }
        timer = window.setTimeout(() => finish(false), 6000)
        audio.onerror = () => finish(false)
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
      timer = window.setTimeout(() => finish(false), 2500)
      utterance.onstart = () => finish(true)
      utterance.onerror = () => finish(false)
      try {
        synth.speak(utterance)
      } catch {
        finish(false)
      }
    })
  }

  async function speak(spelling: string, providedUrls: (string | null | undefined)[] = []) {
    message.value = ''
    stop()
    for (const url of providedUrls) {
      if (url && (await playUrl(url))) return true
    }
    if (await speakLocally(spelling)) return true
    if (await playUrl(onlineSpeechUrl(spelling))) return true
    message.value = NO_AUDIO_MESSAGE
    return false
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

  return { speak, stop, message, available }
}