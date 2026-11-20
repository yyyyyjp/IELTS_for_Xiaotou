let current: HTMLAudioElement | null = null
let seq = 0
let cachedVoices: SpeechSynthesisVoice[] = []

function stopCurrent(): void {
  if (!current) return
  try {
    current.pause()
    current.src = ''
  } catch {
    /* ignore */
  }
  current = null
}

function pickVoice(): SpeechSynthesisVoice | null {
  if (!('speechSynthesis' in window)) return null
  if (cachedVoices.length === 0) cachedVoices = window.speechSynthesis.getVoices()
  const score = (voice: SpeechSynthesisVoice) => {
    const name = voice.name || ''
    const lang = (voice.lang || '').replace('_', '-')
    let value = 0
    if (/^en-GB/i.test(lang)) value += 100
    else if (/^en-AU/i.test(lang)) value += 40
    else if (/^en/i.test(lang)) value += 8
    else return -1
    if (/Natural|Neural/i.test(name)) value += 60
    if (/Sonia|Libby|Maisie|Natasha|Ryan|Thomas/i.test(name)) value += 55
    return value
  }
  let best: SpeechSynthesisVoice | null = null
  let bestScore = 0
  for (const voice of cachedVoices) {
    const value = score(voice)
    if (value > bestScore) {
      bestScore = value
      best = voice
    }
  }
  return best
}

function speak(text: string): void {
  if (!('speechSynthesis' in window) || !text) return
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = 'en-GB'
  utterance.rate = 0.95
  const voice = pickVoice()
  if (voice) utterance.voice = voice
  window.speechSynthesis.speak(utterance)
}

export function stopAudio(): void {
  seq += 1
  stopCurrent()
  if ('speechSynthesis' in window) window.speechSynthesis.cancel()
}

export async function playUrl(url: string, fallbackText = ''): Promise<void> {
  const id = ++seq
  stopCurrent()
  if (!url) {
    speak(fallbackText)
    return
  }
  try {
    const audio = new Audio(url)
    audio.preload = 'auto'
    current = audio
    await audio.play()
    await new Promise<void>((resolve) => {
      audio.onended = () => resolve()
      audio.onerror = () => resolve()
    })
    if (id === seq) current = null
  } catch {
    if (id === seq && fallbackText) speak(fallbackText)
  }
}

const prefetched: HTMLAudioElement[] = []

export function prefetch(url: string): void {
  if (!url) return
  const audio = new Audio()
  audio.preload = 'auto'
  audio.src = url
  prefetched.push(audio)
  if (prefetched.length > 6) prefetched.shift()
}
