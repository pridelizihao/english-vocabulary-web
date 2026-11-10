/** 朗读相关的纯函数：挑英文语音、拼在线朗读地址（可在 node 里直接测）。 */

export type VoiceLike = { lang: string; name?: string; localService?: boolean }

/** 优先本地语音，避免 Chrome 把网络语音排到很后面时一直不出声。 */
export function englishVoice<T extends VoiceLike>(voices: T[]): T | undefined {
  const english = voices.filter((voice) => voice.lang.toLowerCase().startsWith('en'))
  return english.find((voice) => voice.localService) ?? english[0]
}

export function onlineSpeechUrl(spelling: string) {
  return `https://dict.youdao.com/dictvoice?audio=${encodeURIComponent(spelling.trim())}&type=2`
}
