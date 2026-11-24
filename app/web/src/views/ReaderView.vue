<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { t } from '../i18n'
import { refreshVocabCounts } from '../state'
import { toast } from '../toast'
import type {
  Attempt,
  Cite,
  LexEntry,
  PackDetail,
  ReadingResultItem,
  ReviewItem,
  ReviewRow,
  ReviewSection,
  Sentence,
} from '../types'
import { resolveLemma, lookup, tokenize } from '../utils/words'
import { fmtDuration, fmtShort } from '../utils/format'
import AppButton from '../components/AppButton.vue'
import GuidePane from '../components/GuidePane.vue'
import Icon from '../components/Icon.vue'
import QuestionRail from '../components/QuestionRail.vue'
import ReviewOverview from '../components/ReviewOverview.vue'
import ReviewRail from '../components/ReviewRail.vue'
import Segmented from '../components/Segmented.vue'
import WordPopover from '../components/WordPopover.vue'

const props = defineProps<{ id: string }>()

const router = useRouter()

const loading = ref(true)
const failed = ref(false)
const pack = ref<PackDetail | null>(null)
const savedMap = ref<Record<string, number>>({})

const showAll = ref(false)
const openIds = reactive(new Set<string>())
const hiddenIds = reactive(new Set<string>())

const tab = ref<'text' | 'guide'>('text')
const railMode = ref<'questions' | 'overview'>('questions')
const openNo = ref<number | null>(null)
const openGap = ref<number | null>(null)
const quizMode = ref(false)

const answers = ref<Record<number, string>>({})
const quizSubmitted = ref(false)
const submitting = ref(false)
const quizResults = ref<ReadingResultItem[]>([])
const sessionId = ref('')
const startedLocal = ref(Date.now())
const finishedMs = ref(0)
const now = ref(Date.now())
let timer = 0

interface PopoverState {
  word: string
  lemma: string
  entry: LexEntry | null
  context: string
  contextZh: string
  sentenceId: string
  para: number
  x: number
  y: number
  saved: boolean
}

const popover = ref<PopoverState | null>(null)
const busyWord = ref(false)

const attempt = computed<Attempt | null>(() => pack.value?.attempt ?? null)
const canReview = computed(() => Boolean(attempt.value))
const isReview = computed(() => canReview.value && !quizMode.value)
const hasGuide = computed(() => Boolean(pack.value?.hasGuide || pack.value?.guide))

const source = computed(() => {
  if (!pack.value) return ''
  return [pack.value.meta.book, pack.value.meta.test, pack.value.meta.passage]
    .filter(Boolean)
    .join(' · ')
})

const questionsCount = computed(() => pack.value?.counts.questions ?? 0)
const vocabCount = computed(() => Object.keys(savedMap.value).length)
const answered = computed(
  () => Object.values(answers.value).filter((value) => value !== '').length,
)

const synthesized = computed<ReadingResultItem[]>(() => {
  if (!pack.value) return []
  return pack.value.questionGroups.flatMap((group) =>
    group.items.map((question) => ({
      no: question.no,
      group: group.id,
      mine: question.mine ?? '',
      answer: Array.isArray(question.answer)
        ? question.answer.map((item) => String(item))
        : [String(question.answer ?? '')],
      correct: question.correct === true,
    })),
  )
})

const shownResults = computed(() => (isReview.value ? synthesized.value : quizResults.value))

const score = computed(() => {
  if (isReview.value && attempt.value) {
    return { correct: attempt.value.score, total: attempt.value.total }
  }
  return {
    correct: quizResults.value.filter((item) => item.correct).length,
    total: questionsCount.value,
  }
})

const elapsed = computed(() => {
  if (isReview.value) return fmtDuration(attempt.value?.durationSec ?? 0)
  const ms = quizSubmitted.value ? finishedMs.value : now.value - startedLocal.value
  return fmtDuration(ms / 1000)
})

const attemptDate = computed(() => {
  const raw = attempt.value?.submittedAt
  if (!raw) return ''
  const ts = Date.parse(raw)
  return Number.isNaN(ts) ? '' : fmtShort(Math.floor(ts / 1000))
})

const analysisMap = computed<Record<number, ReviewItem>>(() => {
  const map: Record<number, ReviewItem> = {}
  for (const section of pack.value?.review?.sections ?? []) {
    for (const item of section.items ?? []) map[item.no] = item
  }
  return map
})

const gapMap = computed<Record<number, { row: ReviewRow; section: ReviewSection }>>(() => {
  const map: Record<number, { row: ReviewRow; section: ReviewSection }> = {}
  for (const section of pack.value?.review?.sections ?? []) {
    for (const row of section.rows ?? []) map[row.no] = { row, section }
  }
  return map
})

const correctNos = computed(
  () => new Set(synthesized.value.filter((item) => item.correct).map((item) => item.no)),
)

function citesForGap(no: number): Cite[] {
  const hit = gapMap.value[no]
  if (!hit) return []
  if (hit.row.cites?.length) return hit.row.cites
  if (correctNos.value.has(no)) return []
  return hit.section.cites ?? []
}

const activeCites = computed<Cite[]>(() => {
  if (openNo.value != null) return analysisMap.value[openNo.value]?.cites ?? []
  if (openGap.value != null) return citesForGap(openGap.value)
  return []
})

function addCites(set: Set<string>, cites?: Cite[]): void {
  for (const cite of cites ?? []) {
    for (const index of cite.b ?? []) set.add(`p${cite.p}s${index + 1}`)
  }
}

const citedIds = computed<Set<string>>(() => {
  const set = new Set<string>()
  if (!isReview.value || tab.value !== 'text') return set
  addCites(set, activeCites.value)
  return set
})

function isVisible(id: string): boolean {
  return showAll.value ? !hiddenIds.has(id) : openIds.has(id)
}

function isCited(sentence: Sentence): boolean {
  return citedIds.value.has(sentence.id)
}

function toggleSentence(id: string): void {
  if (isVisible(id)) {
    openIds.delete(id)
    if (showAll.value) hiddenIds.add(id)
  } else {
    openIds.add(id)
    hiddenIds.delete(id)
  }
}

function toggleAll(): void {
  showAll.value = !showAll.value
  openIds.clear()
  hiddenIds.clear()
}

function isSaved(word: string): boolean {
  if (!pack.value) return false
  return savedMap.value[resolveLemma(word, pack.value.lexicon)] !== undefined
}

function openWord(event: Event, word: string, sentence: Sentence, para: number): void {
  if (!pack.value) return
  const target = event.currentTarget as HTMLElement
  const rect = target.getBoundingClientRect()
  const hit = lookup(word, pack.value.lexicon)
  const lemma = hit?.lemma ?? word.toLowerCase()
  popover.value = {
    word,
    lemma,
    entry: hit?.entry ?? null,
    context: sentence.en,
    contextZh: sentence.zh,
    sentenceId: sentence.id,
    para,
    x: rect.left,
    y: rect.bottom,
    saved: savedMap.value[lemma] !== undefined,
  }
}

function setAnswer(no: number, value: string): void {
  answers.value = { ...answers.value, [no]: value }
  void ensureSession()
}

function closePopover(): void {
  popover.value = null
}

async function toggleWord(): Promise<void> {
  if (!pack.value || !popover.value || busyWord.value) return
  const item = popover.value
  busyWord.value = true
  try {
    if (item.saved) {
      const id = savedMap.value[item.lemma]
      if (id !== undefined) await api.vocabDelete(id)
      const next = { ...savedMap.value }
      delete next[item.lemma]
      savedMap.value = next
      item.saved = false
      toast(t('toast.removed'))
    } else {
      const response = await api.vocabAdd({
        lemma: item.lemma,
        word: item.word,
        gloss: item.entry?.gloss ?? '',
        pos: item.entry?.pos ?? '',
        source: source.value,
        context: {
          packId: props.id,
          sentenceId: item.sentenceId,
          en: item.context,
          zh: item.contextZh,
          para: item.para,
        },
      })
      savedMap.value = { ...savedMap.value, [item.lemma]: response.item.id }
      item.saved = true
      toast(t('toast.added'))
    }
    await refreshVocabCounts()
  } catch (error) {
    toast(error instanceof Error ? error.message : t('toast.loadFailed'))
  } finally {
    busyWord.value = false
  }
}

let creating: Promise<void> | null = null

/** 会话延迟到首次作答才建，避免只浏览也留下空记录。 */
async function ensureSession(): Promise<void> {
  if (sessionId.value || !pack.value || questionsCount.value === 0) return
  if (!creating) {
    creating = api
      .readingSession(pack.value.id)
      .then((session) => {
        sessionId.value = session.sessionId
      })
      .finally(() => {
        creating = null
      })
  }
  await creating
}

function resetQuiz(): void {
  quizSubmitted.value = false
  quizResults.value = []
  answers.value = {}
  sessionId.value = ''
  finishedMs.value = 0
  startedLocal.value = Date.now()
  now.value = Date.now()
  openNo.value = null
  openGap.value = null
}

async function load(): Promise<void> {
  loading.value = true
  failed.value = false
  popover.value = null
  tab.value = 'text'
  railMode.value = 'questions'
  openNo.value = null
  openGap.value = null
  showAll.value = false
  openIds.clear()
  hiddenIds.clear()
  try {
    const [detail, vocab] = await Promise.all([
      api.pack(props.id),
      api.vocabList({ packId: props.id, limit: 1000 }),
    ])
    const full =
      detail.attempt || detail.hasReview || detail.hasGuide
        ? await api.pack(props.id, true)
        : detail
    pack.value = full
    const map: Record<string, number> = {}
    for (const item of vocab.items) map[item.lemma] = item.id
    savedMap.value = map
    quizMode.value = !(full.attempt || full.hasReview)
    resetQuiz()
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}

async function submit(): Promise<void> {
  if (submitting.value) return
  submitting.value = true
  try {
    await ensureSession()
    if (!sessionId.value) return
    const duration = Date.now() - startedLocal.value
    const result = await api.readingSubmit(sessionId.value, answers.value, duration)
    quizResults.value = result.items
    finishedMs.value = duration
    quizSubmitted.value = true
    await refreshVocabCounts()
  } catch (error) {
    toast(error instanceof Error ? error.message : t('toast.loadFailed'))
  } finally {
    submitting.value = false
  }
}

function redo(): void {
  quizMode.value = true
  tab.value = 'text'
  railMode.value = 'questions'
  resetQuiz()
  document.querySelector('.pane-ans .scroll')?.scrollTo({ top: 0, behavior: 'smooth' })
}

function backToReview(): void {
  quizMode.value = false
  resetQuiz()
  railMode.value = 'questions'
}

function toggleOpen(no: number): void {
  openNo.value = openNo.value === no ? null : no
  openGap.value = null
}

function scrollToCites(cites: Cite[]): void {
  const first = cites[0]
  if (!first || !first.b?.length) return
  const el = document.querySelector(
    `.pane-read .sent[data-id="p${first.p}s${first.b[0] + 1}"]`,
  )
  el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

async function jumpToCite(no: number): Promise<void> {
  openNo.value = no
  openGap.value = null
  await nextTick()
  scrollToCites(analysisMap.value[no]?.cites ?? [])
}

async function jumpToGap(no: number): Promise<void> {
  if (openGap.value === no) {
    openGap.value = null
    return
  }
  openGap.value = no
  openNo.value = null
  await nextTick()
  scrollToCites(citesForGap(no))
  const row = document.querySelector('.scroll-ans .row.on')
  row?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

function back(): void {
  router.push('/read')
}

function onKey(event: KeyboardEvent): void {
  if (event.key === 'Escape') closePopover()
}

onMounted(() => {
  load()
  timer = window.setInterval(() => {
    if (!isReview.value && !quizSubmitted.value) now.value = Date.now()
  }, 1000)
  document.addEventListener('click', closePopover)
  document.addEventListener('keydown', onKey)
})

onBeforeUnmount(() => {
  window.clearInterval(timer)
  document.removeEventListener('click', closePopover)
  document.removeEventListener('keydown', onKey)
})

watch(() => props.id, load)

watch(railMode, (value) => {
  if (value === 'overview') {
    openNo.value = null
    openGap.value = null
  }
})
</script>

<template>
  <div class="reader">
    <div v-if="loading" class="state">{{ t('common.loading') }}</div>
    <div v-else-if="failed" class="state">
      {{ t('toast.loadFailed') }}
      <button class="retry" @click="load">{{ t('common.retry') }}</button>
    </div>

    <template v-else-if="pack">
      <header class="topbar">
        <div class="tb-left">
          <div class="title-row">
            <button
              class="back"
              type="button"
              :title="t('reader.back')"
              :aria-label="t('reader.back')"
              @click="back"
            >
              <Icon name="arrowLeft" :size="13" />
            </button>
            <h1>{{ pack.meta.title }}</h1>
          </div>
          <div class="meta">
            <span>{{ source }}</span>
            <template v-if="isReview && attempt">
              <span class="num strong">{{ attempt.score }} / {{ attempt.total }}</span>
              <span class="num">{{ elapsed }}</span>
              <span v-if="attemptDate">{{ attemptDate }}</span>
              <span v-if="attempt.wrong" class="num bad">
                {{ t('reader.review.wrongCount', { n: attempt.wrong }) }}
              </span>
            </template>
            <template v-else>
              <span class="timer num">{{ t('reader.duration') }} {{ elapsed }}</span>
              <span v-if="quizSubmitted" class="num strong">
                {{ score.correct }} / {{ score.total }}
              </span>
            </template>
          </div>
        </div>

        <div class="tb-right">
          <Segmented
            v-if="hasGuide"
            v-model="tab"
            class="tabs"
            :aria-label="t('reader.tab.text')"
            :options="[
              { value: 'text', label: t('reader.tab.text') },
              { value: 'guide', label: t('reader.tab.guide') },
            ]"
          />

          <template v-if="tab === 'text'">
            <span v-if="!isReview && !quizSubmitted" class="progress num">
              {{ answered }} / {{ questionsCount }}
            </span>
            <AppButton size="sm" @click="router.push('/vocab')">
              {{ t('reader.vocab') }}
              <span v-if="vocabCount" class="badge">{{ vocabCount }}</span>
            </AppButton>
            <AppButton size="sm" @click="toggleAll">
              {{ showAll ? t('reader.hideAll') : t('reader.showAll') }}
            </AppButton>

            <template v-if="isReview">
              <AppButton size="sm" @click="redo">{{ t('reader.redo') }}</AppButton>
            </template>
            <template v-else>
              <AppButton
                v-if="!quizSubmitted"
                size="sm"
                variant="outline"
                :disabled="answered === 0 || submitting"
                @click="submit"
              >
                {{ t('reader.submit') }}
              </AppButton>
              <template v-else>
                <AppButton v-if="canReview" size="sm" variant="outline" @click="backToReview">
                  {{ t('reader.rail.review') }}
                </AppButton>
                <AppButton v-else size="sm" @click="redo">{{ t('reader.redo') }}</AppButton>
              </template>
            </template>
          </template>
        </div>
      </header>

      <div v-if="tab === 'guide'" class="guide-wrap">
        <GuidePane :guide="pack.guide ?? null" />
      </div>

      <div v-else class="split">
        <section class="pane pane-read">
          <div class="scroll">
            <div v-for="paragraph in pack.paragraphs" :key="paragraph.no" class="para">
              <span class="pnum num">{{ paragraph.no }}</span>
              <div class="text">
                <template v-for="sentence in paragraph.sentences" :key="sentence.id">
                  <span
                    class="sent"
                    :class="{ open: isVisible(sentence.id), hl: isCited(sentence) }"
                    :data-id="sentence.id"
                    @click="toggleSentence(sentence.id)"
                  >
                    <template v-for="(token, index) in tokenize(sentence.en)" :key="index">
                      <span
                        v-if="token.word"
                        class="w"
                        :class="{ saved: isSaved(token.text) }"
                        role="button"
                        tabindex="0"
                        @click.stop="openWord($event, token.text, sentence, paragraph.no)"
                        @keydown.enter.prevent.stop="openWord($event, token.text, sentence, paragraph.no)"
                        @keydown.space.prevent.stop="openWord($event, token.text, sentence, paragraph.no)"
                      >{{ token.text }}</span>
                      <template v-else>{{ token.text }}</template>
                    </template>
                  </span>{{ ' ' }}<span v-if="isVisible(sentence.id)" class="tr">{{ sentence.zh }}</span>
                </template>
              </div>
            </div>
          </div>
        </section>

        <aside class="pane pane-ans">
          <div v-if="isReview && pack.review" class="rail-head">
            <span class="rh-title">{{ t('reader.rail.answer') }}</span>
            <Segmented
              v-model="railMode"
              :options="[
                { value: 'questions', label: t('reader.rail.questions') },
                { value: 'overview', label: t('reader.rail.review') },
              ]"
            />
          </div>

          <div class="scroll scroll-ans">
            <ReviewOverview
              v-if="isReview && railMode === 'overview'"
              :review="pack.review ?? null"
              :attempt="pack.attempt ?? null"
            />
            <ReviewRail
              v-else-if="isReview"
              :groups="pack.questionGroups"
              :review="pack.review ?? null"
              :results="shownResults"
              :paragraphs="pack.paragraphs"
              :open-no="openNo"
              :open-gap="openGap"
              @open="toggleOpen"
              @gap="jumpToGap"
              @cite="jumpToCite"
            />
            <QuestionRail
              v-else
              :answers="answers"
              :groups="pack.questionGroups"
              :submitted="quizSubmitted"
              :results="quizResults"
              @answer="setAnswer"
            />
          </div>
        </aside>
      </div>
    </template>
  </div>

  <WordPopover
    v-if="popover"
    :word="popover.word"
    :entry="popover.entry"
    :context="popover.context"
    :context-zh="popover.contextZh"
    :saved="popover.saved"
    :x="popover.x"
    :y="popover.y"
    @close="closePopover"
    @toggle="toggleWord"
  />
</template>

<style scoped>
.reader {
  display: flex;
  flex-direction: column;
  height: 100svh;
  max-width: 1720px;
  margin: 0 auto;
  padding: 0 clamp(16px, 2.2vw, 36px) 20px;
  font-family: var(--font-serif);
  color: var(--fg);
  /* 正文一律黑色：层级靠字号、字重与缩进，不靠灰度 */
  --fg-2: var(--fg);
  --fg-3: var(--fg);
}

.reader :deep(em) {
  font-style: normal;
  font-weight: 600;
  text-decoration: underline;
  text-decoration-thickness: 1px;
  text-underline-offset: 3px;
  text-decoration-color: color-mix(in srgb, var(--fg) 32%, transparent);
}

.state {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 48px 4px;
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
}

.retry {
  color: var(--fg);
  font-family: var(--font-sans);
  text-decoration: underline;
  text-underline-offset: 3px;
}

/* ── 顶栏 ── */
.topbar {
  flex-shrink: 0;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  padding: 14px 2px 10px;
}

.tb-left {
  min-width: 0;
}

.title-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}

.back {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  margin-top: 4px;
  margin-left: -6px;
  border-radius: 4px;
  color: var(--fg-3);
  flex-shrink: 0;
}

.back:hover {
  background: var(--bg-subtle);
  color: var(--fg);
}

h1 {
  margin: 0;
  max-width: var(--measure-headline);
  font-family: var(--font-serif);
  font-size: 26px;
  font-weight: 500;
  line-height: 1.2;
  letter-spacing: -0.012em;
}

.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 4px;
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: var(--text-xs);
}

.meta span {
  position: relative;
}

.meta span + span::before {
  content: '';
  position: absolute;
  left: -7px;
  top: 50%;
  width: 2px;
  height: 2px;
  border-radius: 50%;
  background: var(--line-strong);
}

.meta .strong {
  color: var(--fg-2);
  font-weight: 600;
}

.meta .bad {
  color: var(--fg);
}

.tb-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.tabs {
  margin-right: 4px;
}

.progress {
  margin-right: 2px;
  color: var(--fg-3);
  font-size: var(--text-xs);
}

.badge {
  display: inline-grid;
  place-items: center;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 999px;
  background: var(--bg-page);
  color: var(--fg-2);
  font-family: var(--font-sans);
  font-size: 10px;
  font-style: normal;
}

/* ── 双栏 ── */
.split {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1.08fr) minmax(420px, 0.92fr);
  gap: clamp(28px, 3vw, 52px);
  padding-top: 12px;
}

.pane {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 6px 0 64px;
}

.scroll-ans {
  padding: 10px 4px 56px 0;
}

.scroll::-webkit-scrollbar {
  width: 9px;
}

.scroll::-webkit-scrollbar-thumb {
  background: var(--line-soft);
  border: 3px solid var(--bg-raise);
  border-radius: 6px;
}

.rail-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
  padding: 0 2px 8px;
  border-bottom: 0.5px solid var(--line-hair);
}

.rh-title {
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.1em;
}

/* ── 原文 ── */
.para {
  position: relative;
  margin: 0;
  padding: 12px 0 12px 40px;
  border-radius: 8px;
  transition: background-color 0.2s var(--ease-out-cubic);
}

.para:hover {
  background: var(--bg-subtle);
}

.para + .para {
  border-top: 1px dashed var(--line-hair);
}

.pnum {
  position: absolute;
  left: 4px;
  top: 14px;
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 5px;
  background: var(--bg-sunken);
  color: var(--fg);
  font-family: var(--font-sans);
  font-size: 11px;
  font-weight: 600;
}

.text {
  font-size: 17.5px;
  line-height: 1.95;
  color: var(--fg);
  letter-spacing: 0.002em;
}

.sent {
  cursor: pointer;
  border-radius: 3px;
  box-decoration-break: clone;
  -webkit-box-decoration-break: clone;
  transition:
    background-color 0.14s var(--ease-out-cubic),
    font-weight 0.14s var(--ease-out-cubic);
}

.sent:hover {
  background: var(--bg-sunken);
}

.sent.open {
  background: var(--bg-subtle);
  box-shadow: 0 0 0 2px var(--bg-subtle);
}

/* 答案句：点开某道题时才出现，peach 色块 + clay 标记 */
.sent.hl {
  background: var(--hl-answer);
  box-shadow: 0 0 0 3px var(--hl-answer);
  font-weight: 600;
}

.para:has(.hl) .pnum {
  background: var(--bg-raise);
  color: var(--fg);
  box-shadow: inset 2px 0 0 var(--hl-line);
}

.w {
  border-radius: 2px;
  transition: background-color 0.1s, color 0.1s;
}

.w:hover {
  background: var(--bg-sunken);
  color: var(--fg);
  cursor: help;
}

.w.saved {
  text-decoration: underline;
  text-decoration-color: var(--fg);
  text-decoration-thickness: 1.5px;
  text-underline-offset: 3px;
}

.tr {
  display: block;
  margin: 10px 0;
  padding: 9px 14px;
  border-left: 2px solid var(--accent);
  border-radius: 0 5px 5px 0;
  background: var(--bg-subtle);
  color: var(--fg-2);
  font-family: var(--font-sans);
  font-size: 13.5px;
  line-height: 1.9;
  animation: tr-in 0.18s var(--ease-out-cubic);
}

@keyframes tr-in {
  from {
    opacity: 0;
    transform: translateY(-3px);
  }
}

/* ── 读懂这篇 ── */
.guide-wrap {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 12px 0 0;
}

.guide-wrap::-webkit-scrollbar {
  width: 9px;
}

.guide-wrap::-webkit-scrollbar-thumb {
  background: var(--line-soft);
  border: 3px solid var(--bg-page);
  border-radius: 6px;
}

@media (max-width: 1240px) {
  .split {
    grid-template-columns: minmax(0, 1fr) minmax(360px, 0.8fr);
  }
}

@media (max-width: 1100px) {
  .reader {
    height: auto;
    padding-bottom: 40px;
  }

  .split {
    grid-template-columns: minmax(0, 1fr);
    gap: 14px;
  }

  .topbar {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }

  .tb-right {
    flex-wrap: wrap;
  }

  .scroll {
    overflow: visible;
    padding: 12px 0 32px;
  }

  .scroll-ans {
    padding: 14px 0 24px;
  }

  .pane {
    max-height: none;
  }

  .rail-head {
    position: sticky;
    top: 0;
    z-index: 5;
    padding-top: 6px;
    background: var(--bg-page);
  }

  .guide-wrap {
    overflow: visible;
    padding: 8px 0 0;
  }
}

@media (max-width: 640px) {
  .reader {
    padding: 0 14px 32px;
  }

  .text {
    font-size: 16.5px;
    line-height: 1.85;
  }

  .para {
    padding-left: 30px;
  }

  .pnum {
    width: 20px;
    height: 20px;
    font-size: 10px;
  }

  .tabs {
    order: -1;
    width: 100%;
    margin-bottom: 2px;
  }
}
</style>
