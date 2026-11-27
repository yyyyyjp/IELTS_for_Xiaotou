<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'
import { t } from '../i18n'
import { refreshVocabCounts } from '../state'
import { toast } from '../toast'
import type {
  DictAnswerResult,
  DictItem,
  DictSession,
  DictSummary,
  PackSummary,
} from '../types'
import { ALL_PACKS_ID } from '../localDictation'
import { fmtDuration, formatPackCode, formatPackOption, pct } from '../utils/format'
import { playUrl, prefetch, stopAudio } from '../utils/audio'
import AppButton from '../components/AppButton.vue'
import Card from '../components/Card.vue'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'
import ProgressBar from '../components/ProgressBar.vue'
import Segmented from '../components/Segmented.vue'

type Phase = 'setup' | 'run' | 'done'
type Mode = 'word' | 'word_in_context' | 'sentence'

const phase = ref<Phase>('setup')
const packs = ref<PackSummary[]>([])
const packId = ref(ALL_PACKS_ID)
const mode = ref<Mode>('word')
const limit = ref('20')
const starting = ref(false)
const error = ref('')

const session = ref<DictSession | null>(null)
const index = ref(0)
const inputs = ref<string[]>([])
const checked = ref(false)
const result = ref<DictAnswerResult | null>(null)
const correctCount = ref(0)
const summary = ref<DictSummary | null>(null)
const replays = ref(0)
const itemStart = ref(Date.now())

const inputEls = new Map<number, HTMLInputElement>()

const item = computed<DictItem | null>(() => session.value?.items[index.value] ?? null)
const selectedPack = computed(() => packs.value.find((pack) => pack.id === packId.value))
const selectedSource = computed(() => {
  if (packId.value === ALL_PACKS_ID) return t('dictate.allPacks')
  const meta = selectedPack.value?.meta
  if (!meta) return ''
  return formatPackCode(meta) || [meta.book, meta.test, meta.passage].filter(Boolean).join(' · ')
})
const total = computed(() => session.value?.items.length ?? 0)
const progress = computed(() => (total.value ? index.value / total.value : 0))
const canCheck = computed(() => inputs.value.some((value) => value.trim() !== ''))

const modeOptions: { value: Mode; icon: 'bookmark' | 'book' | 'layers'; label: string; desc: string }[] = [
  { value: 'word', icon: 'bookmark', label: 'dictate.mode.word', desc: 'dictate.mode.wordDesc' },
  { value: 'word_in_context', icon: 'book', label: 'dictate.mode.context', desc: 'dictate.mode.contextDesc' },
  { value: 'sentence', icon: 'layers', label: 'dictate.mode.sentence', desc: 'dictate.mode.sentenceDesc' },
]

const countOptions = [
  { value: '10', label: '10' },
  { value: '20', label: '20' },
  { value: '30', label: '30' },
]

const parts = computed(() => {
  const text = item.value?.text || ''
  let blank = 0
  return text
    .split(/(\{\{\}\})/)
    .filter(Boolean)
    .map((part) => (part === '{{}}' ? { text: part, blank: blank++ } : { text: part, blank: -1 }))
})

function bindInput(element: unknown, blank: number): void {
  if (element instanceof HTMLInputElement) inputEls.set(blank, element)
  else inputEls.delete(blank)
}

function inputWidth(blank: number): string {
  const length = item.value?.blankLengths[blank] ?? 6
  return `${Math.max(3, length + 1)}ch`
}

async function loadPacks(): Promise<void> {
  try {
    const data = await api.packs()
    packs.value = data.items
    if (!packId.value) {
      packId.value = ALL_PACKS_ID
    }
  } catch {
    error.value = t('toast.loadFailed')
  }
}

function resetItem(): void {
  const blanks = item.value?.blankCount ?? 1
  inputs.value = Array.from({ length: blanks }, () => '')
  checked.value = false
  result.value = null
  replays.value = 0
  itemStart.value = Date.now()
  nextTick(() => {
    inputEls.get(0)?.focus()
  })
}

async function start(): Promise<void> {
  if (!packId.value || starting.value) return
  starting.value = true
  error.value = ''
  try {
    const data = await api.dictationSession({
      packId: packId.value,
      mode: mode.value,
      source: 'auto',
      limit: Number(limit.value),
    })
    session.value = data
    index.value = 0
    correctCount.value = 0
    summary.value = null
    phase.value = 'run'
    resetItem()
    afterItemChange(true)
  } catch (err) {
    error.value = err instanceof Error ? err.message : t('toast.loadFailed')
  } finally {
    starting.value = false
  }
}

function afterItemChange(auto: boolean): void {
  const current = item.value
  if (!current) return
  if (auto) void playUrl(current.audioUrl, current.audioText)
  const next = session.value?.items[index.value + 1]
  if (next) prefetch(next.audioUrl)
}

function playManual(): void {
  if (!item.value) return
  replays.value += 1
  void playUrl(item.value.audioUrl, item.value.audioText)
}

async function check(): Promise<void> {
  if (!session.value || !item.value || checked.value || !canCheck.value) return
  try {
    const data = await api.dictationAnswer(session.value.sessionId, {
      itemId: item.value.id,
      input: inputs.value,
      replays: replays.value,
      durationMs: Date.now() - itemStart.value,
    })
    result.value = data
    checked.value = true
    if (data.correct) correctCount.value += 1
  } catch (err) {
    toast(err instanceof Error ? err.message : t('toast.loadFailed'))
  }
}

async function next(): Promise<void> {
  if (!session.value) return
  if (index.value + 1 < session.value.items.length) {
    index.value += 1
    resetItem()
    afterItemChange(true)
    return
  }
  await finish()
}

async function finish(): Promise<void> {
  if (!session.value) return
  try {
    summary.value = await api.dictationFinish(session.value.sessionId)
    phase.value = 'done'
    stopAudio()
    await refreshVocabCounts()
  } catch (err) {
    toast(err instanceof Error ? err.message : t('toast.loadFailed'))
  }
}

function exit(): void {
  stopAudio()
  phase.value = 'setup'
  session.value = null
  summary.value = null
}

async function again(): Promise<void> {
  phase.value = 'setup'
  await start()
}

function onKey(event: KeyboardEvent): void {
  if (phase.value !== 'run') return
  const tag = (event.target as HTMLElement | null)?.tagName ?? ''
  if (event.code === 'Space' && !['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(tag)) {
    event.preventDefault()
    playManual()
  }
  if (event.key === 'Enter' && !['INPUT', 'TEXTAREA', 'BUTTON'].includes(tag)) {
    event.preventDefault()
    if (checked.value) void next()
    else void check()
  }
}

onMounted(() => {
  loadPacks()
  document.addEventListener('keydown', onKey)
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKey)
  stopAudio()
})
</script>

<template>
  <div class="page">
    <div class="wrap">
      <PageHeader
      :eyebrow="selectedSource"
      :title="t('nav.dictate')"
    />

    <template v-if="phase === 'setup'">
      <Card padding="lg" class="setup">
        <div class="field">
          <label for="pack" class="label">{{ t('dictate.pack') }}</label>
          <div class="select">
            <select id="pack" v-model="packId" @change="error = ''">
              <option :value="ALL_PACKS_ID">{{ t('dictate.allPacks') }}</option>
              <option v-for="pack in packs" :key="pack.id" :value="pack.id">
                {{ formatPackOption(pack) }}
              </option>
            </select>
            <Icon name="chevronDown" :size="15" class="select-icon" />
          </div>
        </div>

        <div class="field">
          <span class="label">{{ t('dictate.mode') }}</span>
          <div class="modes">
            <button
              v-for="option in modeOptions"
              :key="option.value"
              type="button"
              class="mode"
              :class="{ on: mode === option.value }"
              @click="mode = option.value; error = ''"
            >
              <Icon :name="option.icon" :size="18" />
              <span class="mode-label">{{ t(option.label) }}</span>
              <span class="mode-desc">{{ t(option.desc) }}</span>
            </button>
          </div>
        </div>

        <div class="foot">
          <div class="field count">
            <span class="label">{{ t('dictate.count') }}</span>
            <Segmented v-model="limit" :options="countOptions" />
          </div>
          <AppButton variant="primary" :disabled="starting || !packId" @click="start">
            {{ t('dictate.start') }}
          </AppButton>
        </div>

        <div v-if="error" class="alert" role="alert">
          <div class="alert-inner">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="alert-ico">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <span class="alert-text">{{ error }}</span>
          </div>
          <button type="button" class="alert-close" :aria-label="t('common.close')" @click="error = ''">
            <Icon name="x" :size="14" />
          </button>
        </div>
      </Card>
    </template>

    <template v-else-if="phase === 'run' && session">
      <div class="run">
        <div class="run-head">
          <button type="button" class="icon-btn" :aria-label="t('dictate.exit')" @click="exit">
            <Icon name="arrowLeft" :size="17" />
          </button>
          <span class="run-count num">{{ index + 1 }} / {{ total }}</span>
          <span class="run-mode">{{ t(mode === 'word_in_context' ? 'dictate.mode.context' : `dictate.mode.${mode}`) }}</span>
        </div>
        <ProgressBar :value="index" :total="total" :height="2" />

        <Card padding="lg" class="stage">
          <p class="hint-label">{{ checked ? '' : t('dictate.typeAnswer') }}</p>

          <div class="audio">
            <button type="button" class="speaker" :aria-label="t('common.replay')" @click="playManual">
              <Icon name="play" :size="24" />
            </button>
            <span v-if="item?.hint.gloss" class="gloss">{{ item.hint.gloss }}</span>
          </div>

          <div v-if="mode === 'word'" class="word-input">
            <input
              :ref="(element) => bindInput(element, 0)"
              v-model="inputs[0]"
              class="line-input"
              :class="{
                ok: checked && result?.correct,
                bad: checked && result && !result.correct,
              }"
              :disabled="checked"
              autocomplete="off"
              autocapitalize="off"
              spellcheck="false"
              @keydown.enter.prevent="checked ? next() : check()"
            />
          </div>

          <p v-else class="masked">
            <template v-for="(part, partIndex) in parts" :key="partIndex">
              <input
                v-if="part.blank >= 0"
                :ref="(element) => bindInput(element, part.blank)"
                v-model="inputs[part.blank]"
                class="blank"
                :class="{
                  ok: checked && result?.parts[part.blank],
                  bad: checked && result?.parts[part.blank] === false,
                }"
                :style="{ width: inputWidth(part.blank) }"
                :disabled="checked"
                autocomplete="off"
                autocapitalize="off"
                spellcheck="false"
                @keydown.enter.prevent="checked ? next() : check()"
              />
              <template v-else>{{ part.text }}</template>
            </template>
          </p>

          <div class="feedback" :class="result ? (result.correct ? 'ok' : 'bad') : ''">
            <template v-if="checked && result">
              <Icon :name="result.correct ? 'check' : 'x'" :size="16" />
              <span v-if="result.correct" class="fb-text">{{ t('common.correct') }}</span>
              <template v-else>
                <span class="fb-label">{{ t('dictate.correctAnswer') }}</span>
                <span class="fb-expected">{{ result.expected.join(' / ') }}</span>
              </template>
            </template>
          </div>

          <div class="actions">
            <AppButton
              v-if="!checked"
              variant="primary"
              :disabled="!canCheck"
              @click="check"
            >
              {{ t('dictate.check') }}
            </AppButton>
            <AppButton v-else variant="primary" @click="next">
              {{ t('dictate.next') }}
            </AppButton>
          </div>
        </Card>
      </div>
    </template>

    <template v-else-if="phase === 'done' && summary">
      <Card padding="lg" class="done">
        <div class="score-row">
          <span class="score serif num">{{ pct(summary.accuracy) }}</span>
          <div class="score-meta">
            <span class="num">{{ summary.correct }} / {{ summary.total }}</span>
            <span class="muted">{{ fmtDuration(summary.durationSec) }}</span>
          </div>
        </div>

        <div v-if="summary.wrong.length" class="missed">
          <div class="missed-head">{{ t('dictate.missed') }}</div>
          <div v-for="wrong in summary.wrong" :key="wrong.itemId" class="missed-row">
            <span class="missed-answer">{{ wrong.answers.join(' / ') }}</span>
            <span class="missed-input">{{ Array.isArray(wrong.input) ? wrong.input.join(' / ') : wrong.input }}</span>
          </div>
        </div>

        <div class="done-actions">
          <AppButton variant="primary" @click="again">{{ t('dictate.again') }}</AppButton>
          <AppButton variant="secondary" @click="exit">{{ t('common.back') }}</AppButton>
        </div>
      </Card>
    </template>
    </div>
  </div>
</template>

<style scoped>
.wrap {
  width: 100%;
  max-width: 760px;
  margin-inline: auto;
}

.setup {
  max-width: none;
}

.field + .field {
  margin-top: var(--space-5);
}

.label {
  display: block;
  margin-bottom: 8px;
  color: var(--fg-3);
  font-size: var(--text-xs);
}

.select {
  position: relative;
}

.select select {
  width: 100%;
  height: 38px;
  padding: 0 34px 0 12px;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-md);
  background: var(--input-bg);
  font-size: 14px;
  appearance: none;
}

.select-icon {
  position: absolute;
  top: 50%;
  right: 12px;
  transform: translateY(-50%);
  color: var(--fg-3);
  pointer-events: none;
}

.modes {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.mode {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 14px;
  border: 1px solid var(--line-hair);
  border-radius: var(--radius-md);
  color: var(--fg-2);
  text-align: left;
  transition:
    background-color 0.15s var(--ease-out-cubic),
    border-color 0.15s var(--ease-out-cubic);
}

.mode:hover {
  background: var(--bg-subtle);
}

.mode.on {
  border-color: var(--line-strong);
  background: var(--bg-subtle);
  color: var(--fg);
  box-shadow: inset 2px 0 0 var(--accent);
}

.mode-label {
  margin-top: 6px;
  font-size: 14px;
  font-weight: 500;
}

.mode-desc {
  color: var(--fg-3);
  font-size: var(--text-xs);
}

.foot {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin-top: var(--space-6);
  padding-top: var(--space-5);
  border-top: 0.5px solid var(--line-hair);
}

.count {
  margin: 0;
}

.alert {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 18px;
  padding: 14px 38px;
  border: 1px solid var(--bad-line);
  border-radius: var(--radius-md);
  background: var(--bad-bg);
  color: var(--bad);
  text-align: center;
  animation: panel-in 0.16s var(--ease-out-quart);
}

.alert-inner {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-size: var(--text-sm);
  font-weight: 500;
  line-height: 1.5;
}

.alert-ico {
  flex-shrink: 0;
}

.alert-close {
  position: absolute;
  top: 50%;
  right: 10px;
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  transform: translateY(-50%);
  color: var(--bad);
  opacity: 0.72;
}

.alert-close:hover {
  opacity: 1;
  background: color-mix(in srgb, var(--bad) 12%, transparent);
}

.run {
  max-width: none;
}

.run-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.icon-btn {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  color: var(--fg-2);
}

.icon-btn:hover {
  background: var(--bg-sunken);
  color: var(--fg);
}

.run-count {
  color: var(--fg-2);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
}

.run-mode {
  margin-left: auto;
  color: var(--fg-3);
  font-size: var(--text-xs);
}

.stage {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-height: 380px;
  margin-top: 12px;
  padding: 40px 40px 32px;
  text-align: center;
}

.hint-label {
  min-height: 18px;
  color: var(--fg-3);
  font-size: var(--text-xs);
}

.audio {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  margin: 24px 0 8px;
}

.speaker {
  display: grid;
  place-items: center;
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: var(--bg-inverse);
  color: var(--fg-on-dark);
  transition: box-shadow 0.2s var(--ease-out-cubic);
}

.speaker:hover {
  box-shadow: 0 0 0 2px var(--bg-inverse);
}

.gloss {
  color: var(--fg-2);
  font-size: 17px;
}

.word-input {
  width: 100%;
  max-width: 340px;
  margin: 28px 0 0;
}

.line-input {
  width: 100%;
  height: 46px;
  border: 0;
  border-bottom: 1.5px solid var(--line-strong);
  background: transparent;
  color: var(--fg);
  font-size: 26px;
  text-align: center;
  outline: none;
}

.line-input:focus {
  border-bottom-color: var(--focus);
}

.line-input.ok {
  border-bottom-color: var(--ok);
  color: var(--ok);
}

.line-input.bad {
  border-bottom-color: var(--bad);
  color: var(--bad);
}

.masked {
  max-width: 620px;
  margin: 28px 0 0;
  font-size: 19px;
  line-height: 2.3;
  text-align: left;
}

.blank {
  height: 26px;
  margin: 0 0 0 1px;
  padding: 0 4px;
  border: 0;
  border-bottom: 1.5px solid var(--line-strong);
  background: transparent;
  color: var(--fg);
  font-size: inherit;
  text-align: center;
  outline: none;
}

.blank:focus {
  border-bottom-color: var(--focus);
}

.blank.ok {
  border-bottom-color: var(--ok);
  color: var(--ok);
}

.blank.bad {
  border-bottom-color: var(--bad);
  color: var(--bad);
}

.feedback {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 40px;
  margin-top: 24px;
  font-size: var(--text-sm);
}

.feedback.ok {
  color: var(--ok);
}

.feedback.bad {
  color: var(--bad);
}

.fb-expected {
  font-size: 15px;
  font-weight: 500;
  letter-spacing: 0.01em;
}

.fb-label {
  color: var(--fg-3);
  font-size: var(--text-micro);
}

.actions {
  margin-top: auto;
  padding-top: 24px;
}

.done {
  max-width: none;
}

.score-row {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  padding-bottom: var(--space-5);
  border-bottom: 0.5px solid var(--line-hair);
}

.score {
  font-family: var(--font-serif);
  font-size: clamp(56px, 8vw, 80px);
  font-weight: 500;
  line-height: 0.9;
}

.score-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  color: var(--fg-2);
  font-size: var(--text-sm);
}

.missed {
  margin-top: var(--space-5);
}

.missed-head {
  margin-bottom: 8px;
  color: var(--fg-3);
  font-size: var(--text-xs);
}

.missed-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  padding: 7px 0;
  border-top: 0.5px solid var(--line-hair);
  font-size: var(--text-sm);
}

.missed-answer {
  font-weight: 500;
}

.missed-input {
  color: var(--fg-3);
  text-decoration: line-through;
  text-decoration-color: var(--bad-line);
}

.done-actions {
  display: flex;
  gap: 8px;
  margin-top: var(--space-6);
}

@media (max-width: 640px) {
  .modes {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 6px;
  }

  .mode {
    padding: 12px 10px;
  }

  .mode-desc {
    font-size: var(--text-micro);
    line-height: 1.4;
  }

  .stage {
    padding: 28px 20px 24px;
  }

  .masked {
    font-size: 17px;
  }
}
</style>
