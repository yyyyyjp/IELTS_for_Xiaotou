<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import type { Book, Question } from '../types'
import { buildSegments, normalize, player } from '../audio'
import { toast } from '../toast'
import ExplainDialog from '../components/ExplainDialog.vue'
import VocabSheet from '../components/VocabSheet.vue'

const props = defineProps<{ bookId: string }>()
const router = useRouter()

type Phase = 'input' | 'wrong' | 'correct' | 'skipped'

const book = ref<Book | null>(null)
const questions = ref<Question[]>([])
const idx = ref(0)
const phase = ref<Phase>('input')
const typed = ref<string[]>([])
const oks = ref<boolean[]>([])
const attempts = ref(0)
const plays = ref(0)
const playsMap = ref<Record<number, number>>({})
const playing = ref(false)
const showTrans = ref(false)
const showExplain = ref(false)
const showVocab = ref(false)
const finished = ref(false)
const ready = ref(false)
const stats = ref({ direct: 0, rewrite: 0, skip: 0 })

const MAX_PLAYS = 2
const mode = ref<'ielts' | 'free'>(
  localStorage.getItem('tifo-mode') === 'free' ? 'free' : 'ielts',
)

const q = computed(() => questions.value[idx.value] ?? null)
const segs = computed(() => (q.value ? buildSegments(q.value.text, q.value.answers) : []))
const blankCount = computed(() => segs.value.filter((s) => s.type === 'blank').length)
const isPassage = computed(() => blankCount.value > 2 || (q.value?.text.length ?? 0) > 110)
const playsLeft = computed(() => (mode.value === 'ielts' ? Math.max(0, MAX_PLAYS - plays.value) : -1))
const accuracy = computed(() => {
  const total = questions.value.length || 1
  return Math.round(((stats.value.direct + stats.value.rewrite) / total) * 100)
})

const widthCh = (v: string) => `${Math.min(18, Math.max(5, (v || '').length + 1))}ch`

// ---------------------------------------------------------- 数据
async function load() {
  try {
    const [b, qs] = await Promise.all([api.book(props.bookId), api.questions(props.bookId)])
    book.value = b
    questions.value = qs.items
    ready.value = true
    if (!qs.items.length) return
    const firstTodo = qs.items.findIndex((x) => x.status !== 'correct')
    await goto(firstTodo > 0 ? firstTodo : 0)
  } catch (e) {
    toast((e as Error).message)
    router.replace('/')
  }
}

async function goto(i: number) {
  if (i < 0 || i >= questions.value.length) return
  idx.value = i
  const cur = questions.value[i]
  typed.value = new Array(cur.answers.length).fill('')
  oks.value = []
  phase.value = 'input'
  attempts.value = 0
  showTrans.value = false
  finished.value = false
  plays.value = playsMap.value[cur.id] ?? 0
  await nextTick()
  focusBlank(0)
  if (mode.value === 'free' || plays.value < MAX_PLAYS) {
    window.setTimeout(() => play(), 340)
  }
}

// ---------------------------------------------------------- 播放
async function play() {
  if (!q.value || playing.value) return
  if (mode.value === 'ielts' && plays.value >= MAX_PLAYS) {
    toast('雅思模式：本题已播完')
    return
  }
  plays.value++
  playsMap.value[q.value.id] = plays.value
  playing.value = true
  try {
    await player.playQuestion(q.value)
  } finally {
    playing.value = false
  }
}

// ---------------------------------------------------------- 判题
function focusBlank(i = 0) {
  const inputs = document.querySelectorAll<HTMLInputElement>('#sentence input[data-bn]')
  const el = inputs[i] ?? inputs[0]
  el?.focus()
  el?.select()
}

function tabNext(shift: boolean): boolean {
  const inputs = [...document.querySelectorAll<HTMLInputElement>('#sentence input[data-bn]')]
  if (inputs.length <= 1) return false
  const k = inputs.indexOf(document.activeElement as HTMLInputElement)
  const target = inputs[k + (shift ? -1 : 1)]
  if (target) {
    target.focus()
    target.select()
  } else if (!shift) {
    submit()
  }
  return true
}

async function save(status: string, final: string) {
  if (!q.value) return
  try {
    await api.saveProgress({
      questionId: q.value.id,
      status,
      attempts: attempts.value,
      final,
    })
  } catch {
    /* 进度保存失败不打断练习 */
  }
}

async function submit() {
  if (finished.value) return exit()
  if (phase.value === 'correct' || phase.value === 'skipped') return next()
  if (!q.value) return
  if (!typed.value.some((v) => (v ?? '').trim())) {
    toast('未填入')
    return
  }
  const blanks = segs.value.filter((s) => s.type === 'blank')
  const res = blanks.map((b, i) => normalize(typed.value[i] ?? '') === normalize(b.value))
  oks.value = res
  attempts.value++
  const first = attempts.value === 1

  if (res.every(Boolean)) {
    phase.value = 'correct'
    if (first) stats.value.direct++
    else stats.value.rewrite++
    q.value.status = 'correct'
    q.value.final = first ? 'direct' : 'rewrite'
    q.value.attempts = attempts.value
    save('correct', first ? 'direct' : 'rewrite')
    beep()
  } else {
    phase.value = 'wrong'
    q.value.status = 'wrong'
    q.value.attempts = attempts.value
    save('wrong', '')
    toast(`${res.filter((x) => !x).length} 空不对`)
    await nextTick()
    const inputs = document.querySelectorAll<HTMLInputElement>('#sentence input[data-bn]')
    inputs[res.indexOf(false)]?.focus()
  }
}

function skip() {
  if (finished.value) return exit()
  if (phase.value === 'correct' || phase.value === 'skipped') return next()
  phase.value = 'skipped'
  stats.value.skip++
  if (q.value) {
    q.value.status = 'skipped'
    q.value.attempts = attempts.value
  }
  save('skipped', '')
}

function next() {
  if (idx.value + 1 >= questions.value.length) return finish()
  goto(idx.value + 1)
}

function finish() {
  finished.value = true
  player.stop()
}

function exit() {
  player.stop()
  router.push('/')
}

function toggleTrans() {
  showTrans.value = !showTrans.value
}

function setMode(m: 'ielts' | 'free') {
  mode.value = m
  localStorage.setItem('tifo-mode', m)
  if (m === 'ielts' && q.value) {
    plays.value = 0
    playsMap.value[q.value.id] = 0
  }
}

// ---------------------------------------------------------- 音效
let sctx: AudioContext | null = null
function beep() {
  try {
    const AC = window.AudioContext
    if (!AC) return
    if (!sctx || sctx.state === 'closed') sctx = new AC()
    const ctx = sctx
    if (ctx.state === 'suspended') void ctx.resume()
    const t0 = ctx.currentTime
    const tone = (freq: number, at: number, dur: number) => {
      const o = ctx.createOscillator()
      const g = ctx.createGain()
      o.connect(g)
      g.connect(ctx.destination)
      o.type = 'sine'
      o.frequency.value = freq
      g.gain.setValueAtTime(0, t0 + at)
      g.gain.linearRampToValueAtTime(0.16, t0 + at + 0.02)
      g.gain.exponentialRampToValueAtTime(0.01, t0 + at + dur)
      o.start(t0 + at)
      o.stop(t0 + at + dur)
    }
    tone(523.25, 0, 0.15)
    tone(783.99, 0.1, 0.3)
  } catch {
    /* 音效失败无所谓 */
  }
}

// ---------------------------------------------------------- 键盘
const alt = { down: false, other: false }
const ctrl = { down: false, other: false }

function onKeyDown(e: KeyboardEvent) {
  const tag = (e.target as HTMLElement)?.tagName
  const typing = tag === 'INPUT' || tag === 'TEXTAREA'

  if (e.key === 'Alt') {
    alt.down = true
    alt.other = false
    return
  }
  if (e.key === 'Control' || e.key === 'Meta') {
    ctrl.down = true
    ctrl.other = false
    return
  }
  if (alt.down) alt.other = true
  if (e.ctrlKey || e.metaKey) ctrl.other = true

  if (e.key === 'Escape') {
    if (showExplain.value) {
      showExplain.value = false
      return
    }
    if (showVocab.value) {
      showVocab.value = false
      return
    }
    exit()
    return
  }
  if (showExplain.value || showVocab.value) return

  if (e.key === 'Tab') {
    e.preventDefault()
    if (!tabNext(e.shiftKey)) play()
    return
  }
  if ((e.key === ' ' || e.code === 'Space') && !typing) {
    e.preventDefault()
    play()
    return
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    if (idx.value > 0) goto(idx.value - 1)
    else toast('已是第一题')
    return
  }
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    skip()
    return
  }
  if (e.key === 'Enter' && !typing) {
    e.preventDefault()
    if (e.repeat) return
    submit()
  }
}

function onKeyUp(e: KeyboardEvent) {
  if (e.key === 'Alt') {
    const tap = alt.down && !alt.other
    alt.down = false
    alt.other = false
    if (tap && !showExplain.value && !showVocab.value) toggleTrans()
    return
  }
  if (e.key === 'Control' || e.key === 'Meta') {
    const tap = ctrl.down && !ctrl.other
    ctrl.down = false
    ctrl.other = false
    if (tap && !showVocab.value) showExplain.value = !showExplain.value
  }
}

function onJump(i: number) {
  showVocab.value = false
  goto(i)
}

onMounted(() => {
  player.stop()
  window.addEventListener('keydown', onKeyDown)
  window.addEventListener('keyup', onKeyUp)
  void load()
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeyDown)
  window.removeEventListener('keyup', onKeyUp)
  player.stop()
})
</script>

<template>
  <div class="stage">
    <div class="stage-top">
      <div class="pill">
        <b>{{ book?.name ?? '加载中' }}</b>
        <span class="tag">{{ playsLeft < 0 ? '宽松模式' : `剩余 ${playsLeft} 次播放` }}</span>
      </div>
      <div class="seg">
        <button :class="{ on: mode === 'ielts' }" @click="setMode('ielts')">雅思模式</button>
        <button :class="{ on: mode === 'free' }" @click="setMode('free')">宽松</button>
      </div>
      <div class="grow" />
      <button class="iconbtn" :class="{ pulse: playing }" @click="play">▶ 播放</button>
      <button class="iconbtn" @click="showVocab = true">词表</button>
      <button class="iconbtn" @click="exit">退出</button>
    </div>

    <div class="stage-board">
      <div v-if="ready && q" class="card" :class="{ compact: phase === 'correct' || phase === 'skipped' || finished }">
        <div class="banner"><i /><span>{{ q.title }}</span></div>

        <div v-if="finished" class="sentence" style="font-size: 30px">本组完成</div>

        <div v-else id="sentence" class="sentence" :class="{ passage: isPassage }">
          <template v-for="(s, i) in segs" :key="i">
            <template v-if="s.type === 'text'">{{ s.value }}</template>
            <template v-else>
              <span v-if="phase === 'correct'" class="blank-ok">{{ s.value }}</span>
              <span v-else-if="phase === 'skipped'" class="blank-ok reveal">{{ s.value }}</span>
              <span v-else-if="phase === 'wrong' && oks[s.index]" class="blank-ok">{{ s.value }}</span>
              <span v-else class="slot" :class="{ wrong: phase === 'wrong' && !oks[s.index] }" :style="{ width: widthCh(s.value) }">
                <input
                  v-model="typed[s.index]"
                  :data-bn="s.index"
                  type="text"
                  autocomplete="off"
                  autocapitalize="off"
                  spellcheck="false"
                  @keydown.enter.prevent="submit"
                />
              </span>
            </template>
          </template>
        </div>

        <div v-if="finished" class="keyhints">
          <div class="kh primary"><kbd>Enter</kbd><span>返回词库</span></div>
        </div>

        <div v-else class="keyhints">
          <template v-if="phase === 'correct' || phase === 'skipped'">
            <div class="kh primary"><kbd>Enter</kbd><span>下一题</span></div>
            <div class="khsep" />
            <div class="kh"><kbd>Tab</kbd><span>发音</span></div>
            <div class="kh"><kbd>Ctrl</kbd><span>解析</span></div>
            <div class="kh"><kbd>↓</kbd><span>跳过</span></div>
          </template>
          <template v-else>
            <div class="kh"><kbd>Tab</kbd><span>{{ blankCount > 1 ? '下一个空' : '发音' }}</span></div>
            <div class="kh"><kbd>Space</kbd><span>发音</span></div>
            <div class="kh"><kbd>Alt</kbd><span>翻译</span></div>
            <div class="kh"><kbd>Ctrl</kbd><span>解析</span></div>
            <div class="khsep" />
            <div class="kh"><kbd>↑</kbd><span>上一题</span></div>
            <div class="kh primary"><kbd>Enter</kbd><span>提交</span></div>
            <div class="kh"><kbd>↓</kbd><span>跳过</span></div>
          </template>
        </div>
      </div>

      <div v-if="showTrans && q" class="trans-bar">翻译：{{ q.translation || '暂无翻译' }}</div>

      <div v-if="finished" class="reveal-strip">
        <div class="r">
          <div class="k">正确率</div>
          <div class="v en">{{ accuracy }}%　<small style="color: rgba(255, 255, 255, 0.5)">{{ stats.direct + stats.rewrite }} / {{ questions.length }} 题</small></div>
        </div>
        <div class="r">
          <div class="k">明细</div>
          <div class="v">一次正确 {{ stats.direct }} · 重写正确 {{ stats.rewrite }} · 跳过 {{ stats.skip }}</div>
        </div>
      </div>

      <div v-else-if="q && (phase === 'correct' || phase === 'skipped')" class="reveal-strip">
        <div class="r">
          <div class="k">答案</div>
          <div class="v en">{{ q.answers.join(' / ') }}</div>
        </div>
        <div class="r">
          <div class="k">原文</div>
          <div class="v">{{ q.text }}</div>
        </div>
        <div class="r">
          <div class="k">翻译</div>
          <div class="v">{{ q.translation || '暂无翻译' }}</div>
        </div>
      </div>

      <div class="stat-row">
        <b>{{ idx + 1 }}</b> / {{ questions.length }} 题
        <i>·</i>一次正确 <b>{{ stats.direct }}</b>
        <i>·</i>重写正确 <b>{{ stats.rewrite }}</b>
        <i>·</i>跳过 <b>{{ stats.skip }}</b>
      </div>
    </div>

    <ExplainDialog v-if="showExplain && q" :question="q" @close="showExplain = false" />
    <VocabSheet
      v-if="showVocab"
      :questions="questions"
      :book-id="bookId"
      :current="idx"
      @close="showVocab = false"
      @jump="onJump"
      @reset="load"
    />
  </div>
</template>
