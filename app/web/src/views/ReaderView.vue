<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { t } from '../i18n'
import { refreshVocabCounts } from '../state'
import { toast } from '../toast'
import type { LexEntry, PackDetail, ReadingResultItem, Sentence } from '../types'
import { resolveLemma, lookup, tokenize } from '../utils/words'
import { fmtDuration } from '../utils/format'
import AppButton from '../components/AppButton.vue'
import Icon from '../components/Icon.vue'
import QuestionRail from '../components/QuestionRail.vue'
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

const answers = ref<Record<number, string>>({})
const submitted = ref(false)
const submitting = ref(false)
const results = ref<ReadingResultItem[]>([])
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

const correctCount = computed(() => results.value.filter((item) => item.correct).length)

const elapsed = computed(() => {
  const ms = submitted.value ? finishedMs.value : now.value - startedLocal.value
  return fmtDuration(ms / 1000)
})

function isVisible(id: string): boolean {
  return showAll.value ? !hiddenIds.has(id) : openIds.has(id)
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

async function load(): Promise<void> {
  loading.value = true
  failed.value = false
  popover.value = null
  submitted.value = false
  results.value = []
  answers.value = {}
  showAll.value = false
  openIds.clear()
  hiddenIds.clear()
  try {
    const [detail, vocab] = await Promise.all([
      api.pack(props.id),
      api.vocabList({ packId: props.id, limit: 1000 }),
    ])
    pack.value = detail
    const map: Record<string, number> = {}
    for (const item of vocab.items) map[item.lemma] = item.id
    savedMap.value = map
    sessionId.value = ''
    startedLocal.value = Date.now()
    finishedMs.value = 0
    now.value = Date.now()
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
    results.value = result.items
    finishedMs.value = duration
    submitted.value = true
    await refreshVocabCounts()
  } catch (error) {
    toast(error instanceof Error ? error.message : t('toast.loadFailed'))
  } finally {
    submitting.value = false
  }
}

function redo(): void {
  submitted.value = false
  results.value = []
  answers.value = {}
  sessionId.value = ''
  finishedMs.value = 0
  startedLocal.value = Date.now()
  now.value = Date.now()
  document.querySelector('.pane-ans .scroll')?.scrollTo({ top: 0, behavior: 'smooth' })
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
    if (!submitted.value) now.value = Date.now()
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
            <span class="timer num">{{ t('reader.duration') }} {{ elapsed }}</span>
          </div>
        </div>

        <div class="tb-right">
          <span v-if="!submitted" class="progress num">{{ answered }} / {{ questionsCount }}</span>
          <AppButton size="sm" @click="router.push('/vocab')">
            {{ t('reader.vocab') }}
            <span v-if="vocabCount" class="badge">{{ vocabCount }}</span>
          </AppButton>
          <AppButton size="sm" @click="toggleAll">
            {{ showAll ? t('reader.hideAll') : t('reader.showAll') }}
          </AppButton>
          <AppButton
            v-if="!submitted"
            size="sm"
            variant="primary"
            :disabled="answered === 0 || submitting"
            @click="submit"
          >
            {{ t('reader.submit') }}
          </AppButton>
          <AppButton v-else size="sm" @click="redo">
            {{ t('reader.redo') }}
          </AppButton>
        </div>
      </header>

      <div class="split">
        <section class="pane pane-read">
          <div class="scroll">
            <div v-for="paragraph in pack.paragraphs" :key="paragraph.no" class="para">
              <span class="pnum num">{{ paragraph.no }}</span>
              <div class="text">
                <template v-for="sentence in paragraph.sentences" :key="sentence.id">
                  <span
                    class="sent"
                    :class="{ open: isVisible(sentence.id) }"
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
          <div class="scroll scroll-ans">
            <QuestionRail
              :answers="answers"
              :groups="pack.questionGroups"
              :submitted="submitted"
              :results="results"
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
  align-items: center;
  gap: 6px;
}

.back {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
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

.tb-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
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
  padding-top: 16px;
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
  padding: 12px 4px 56px 0;
}

.scroll::-webkit-scrollbar {
  width: 9px;
}

.scroll::-webkit-scrollbar-thumb {
  background: var(--line-soft);
  border: 3px solid var(--bg-raise);
  border-radius: 6px;
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
  color: var(--accent-strong);
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
  transition: background-color 0.14s var(--ease-out-cubic);
}

.sent:hover {
  background: var(--bg-sunken);
}

.sent.open {
  background: var(--bg-subtle);
  box-shadow: 0 0 0 2px var(--bg-subtle);
}

.w {
  border-radius: 2px;
  transition: background-color 0.1s, color 0.1s;
}

.w:hover {
  background: var(--accent);
  color: var(--bg-raise);
  cursor: help;
}

.w.saved {
  text-decoration: underline;
  text-decoration-color: var(--accent);
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

@media (max-width: 1240px) {
  .split {
    grid-template-columns: minmax(0, 1fr) minmax(360px, 0.8fr);
  }

  .pane-read .hint {
    display: none;
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

  .stat {
    min-width: 70px;
    padding: 5px 10px;
  }
}
</style>
