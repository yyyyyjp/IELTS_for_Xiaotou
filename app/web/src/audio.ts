import type { Question } from './types'

/** 浏览器内置合成的兜底音色：Edge 的 Natural 音色 > Chrome 的 UK 音色 > 任意英音 */
function scoreVoice(v: SpeechSynthesisVoice): number {
  const name = v.name || ''
  const lang = (v.lang || '').replace('_', '-')
  let s = 0
  if (/^en-GB/i.test(lang)) s += 100
  else if (/^en-AU/i.test(lang)) s += 40
  else if (/^en-NZ/i.test(lang)) s += 35
  else if (/^en/i.test(lang)) s += 8
  else return -1

  if (/Natural|Neural/i.test(name)) s += 60
  if (/Sonia|Libby|Maisie|Natasha|Ryan|Thomas/i.test(name)) s += 55
  if (/Google UK English/i.test(name)) s += 45
  return s
}

/**
 * 统一播放出口：
 * 1) 后端已生成的 neural mp3（首选）
 * 2) 内置真题的远程真人录音
 * 3) 浏览器 speechSynthesis（断网兜底）
 */
export class Player {
  private audio: HTMLAudioElement | null = null
  private voices: SpeechSynthesisVoice[] = []
  private token = 0

  constructor() {
    if ('speechSynthesis' in window) {
      const load = () => {
        this.voices = window.speechSynthesis.getVoices()
      }
      load()
      window.speechSynthesis.onvoiceschanged = load
    }
  }

  get bestVoice(): SpeechSynthesisVoice | null {
    let best: SpeechSynthesisVoice | null = null
    let bestScore = 0
    for (const v of this.voices) {
      const s = scoreVoice(v)
      if (s > bestScore) {
        bestScore = s
        best = v
      }
    }
    return best
  }

  get browserVoiceLabel(): string {
    return this.bestVoice?.name ?? ''
  }

  stop(): void {
    this.token++
    if (this.audio) {
      try {
        this.audio.pause()
      } catch {
        /* 已停止 */
      }
      this.audio = null
    }
    if ('speechSynthesis' in window) {
      try {
        window.speechSynthesis.cancel()
      } catch {
        /* ignore */
      }
    }
  }

  /** 播放一道题；返回的 Promise 在音频结束时 resolve（被打断也 resolve） */
  playQuestion(q: Question): Promise<void> {
    const src = q.audioUrl || q.sourceAudio
    if (src) {
      this.stop()
      const myToken = this.token
      return new Promise<void>((resolve) => {
        const a = new Audio(src)
        this.audio = a
        let settled = false
        const done = () => {
          if (settled) return
          settled = true
          resolve()
        }
        a.onended = done
        a.onerror = () => {
          this.audio = null
          if (myToken !== this.token) return done()
          this.speakBrowser(q.text).then(done)
        }
        a.play().catch(() => {
          this.audio = null
          if (myToken !== this.token) return done()
          this.speakBrowser(q.text).then(done)
        })
      })
    }
    return this.speakBrowser(q.text)
  }

  speak(text: string): Promise<void> {
    return this.speakBrowser(text)
  }

  /** 分段串行播，规避 Chrome 单条 utterance 静默截断 */
  private speakBrowser(text: string): Promise<void> {
    const synth = window.speechSynthesis
    const raw = (text || '').trim()
    if (!synth || !raw) return Promise.resolve()

    this.stop()
    const myToken = this.token
    const chunks =
      raw.match(/[^.!?;]+[.!?;]+["')\]]?|[^.!?;]+$/g)?.map((s) => s.trim()).filter(Boolean) ?? [raw]

    return new Promise<void>((resolve) => {
      let i = 0
      const step = () => {
        if (myToken !== this.token || i >= chunks.length) return resolve()
        const u = new SpeechSynthesisUtterance(chunks[i++])
        u.lang = 'en-GB'
        u.rate = 0.95
        u.pitch = 1
        const v = this.bestVoice
        if (v) u.voice = v
        u.onend = () => {
          if (myToken === this.token) setTimeout(step, 150)
        }
        u.onerror = () => {
          if (myToken === this.token) setTimeout(step, 150)
        }
        synth.speak(u)
      }
      step()
    })
  }
}

export const player = new Player()

/** 把整段文本切成「文本 / 空」序列，用于渲染填空 */
export function buildSegments(text: string, answers: string[]): Array<{
  type: 'text' | 'blank'
  value: string
  index: number
}> {
  const t = text || ''
  const list = (answers || []).map((a) => a.trim()).filter(Boolean)
  if (!list.length || !t) return t ? [{ type: 'text', value: t, index: 0 }] : []

  const hits: Array<{ start: number; end: number; value: string }> = []
  let cursor = 0
  for (const a of list) {
    const re = new RegExp('(^|[^A-Za-z])(' + escapeRe(a) + ')(?![A-Za-z])', 'gi')
    re.lastIndex = cursor
    let m = re.exec(t)
    if (!m) {
      re.lastIndex = 0
      m = re.exec(t)
    }
    if (!m) continue
    const start = m.index + m[1].length
    hits.push({ start, end: start + m[2].length, value: m[2] })
    cursor = start + m[2].length
  }
  hits.sort((a, b) => a.start - b.start)

  const segs: Array<{ type: 'text' | 'blank'; value: string; index: number }> = []
  let p = 0
  let bi = 0
  for (const h of hits) {
    if (h.start < p) continue
    if (h.start > p) segs.push({ type: 'text', value: t.slice(p, h.start), index: -1 })
    segs.push({ type: 'blank', value: h.value, index: bi++ })
    p = h.end
  }
  if (p < t.length) segs.push({ type: 'text', value: t.slice(p), index: -1 })
  if (bi === 0) return [{ type: 'text', value: t, index: 0 }]
  return segs
}

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

export const normalize = (s: string): string =>
  (s || '').trim().toLowerCase().replace(/\s+/g, ' ')
