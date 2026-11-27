<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { t } from '../i18n'
import { toast } from '../toast'
import type { PackImportResult, PackSummary } from '../types'
import { fmtDuration } from '../utils/format'
import {
  exportDataset,
  ingestExportFiles,
  type ExportPassageEntry,
} from '../utils/exportDataset'
import AppButton from './AppButton.vue'
import Icon from './Icon.vue'
import Segmented from './Segmented.vue'

const props = defineProps<{
  open: boolean
  initialMode?: 'export' | 'existing'
  initialPackId?: string
  packs?: PackSummary[]
}>()

const emit = defineEmits<{
  (event: 'close'): void
  (event: 'imported', packId: string): void
}>()

const mode = ref<'export' | 'existing'>(props.initialMode ?? 'export')
const localPacks = ref<PackSummary[]>([])
const targetPackId = ref(props.initialPackId ?? '')

const folderInput = ref<HTMLInputElement | null>(null)
const filesInput = ref<HTMLInputElement | null>(null)
const jsonFileInput = ref<HTMLInputElement | null>(null)

const dragging = ref(false)
const readingFiles = ref(false)
const passageQuery = ref('')
const selectedPassageKey = ref('')
const selectedAttemptId = ref('')
const analysisText = ref('')
const recordHistory = ref(true)

const preview = ref<PackImportResult | null>(null)
const previewError = ref('')
const previewLoading = ref(false)
const saving = ref(false)
const copyingPrompt = ref(false)

let previewTimer = 0
let previewSeq = 0

const readingPacks = computed(() => {
  const src = props.packs?.length ? props.packs : localPacks.value
  return src.filter((p) => p.kind === 'reading')
})

const packMap = computed(() => {
  const m = new Map<string, PackSummary>()
  for (const p of readingPacks.value) m.set(p.id, p)
  return m
})

const filteredEntries = computed<ExportPassageEntry[]>(() => {
  const entries = exportDataset.value?.entries ?? []
  const q = passageQuery.value.trim().toLowerCase()
  if (!q) return entries
  const tokens = q.split(/\s+/).filter(Boolean)
  return entries.filter((e) => {
    const hay = `${e.derivedId} ${e.book} ${e.test} ${e.part} ${e.title}`.toLowerCase()
    return tokens.every((tok) => hay.includes(tok))
  })
})

const selectedEntry = computed<ExportPassageEntry | null>(() => {
  const entries = exportDataset.value?.entries ?? []
  return entries.find((e) => e.key === selectedPassageKey.value) ?? null
})

const selectedAttempt = computed<Record<string, unknown> | null>(() => {
  const entry = selectedEntry.value
  if (!entry) return null
  return (
    entry.attempts.find((a) => String(a.attempt_id ?? '') === selectedAttemptId.value) ??
    entry.attempts[0] ??
    null
  )
})

const datasetComplete = computed(() => {
  const ds = exportDataset.value
  return Boolean(ds && ds.hasPassages && ds.hasAttempts && ds.hasQuestions && ds.hasGroups)
})

const canSubmit = computed(() => {
  if (saving.value) return false
  if (mode.value === 'export') {
    if (!selectedEntry.value || !selectedAttempt.value) return false
    if (analysisText.value.trim() && previewError.value) return false
    return true
  }
  return Boolean(targetPackId.value && analysisText.value.trim() && !previewError.value)
})

async function ensurePacks(): Promise<void> {
  if (props.packs?.length || localPacks.value.length) return
  try {
    const res = await api.packs()
    localPacks.value = res.items
  } catch {
    /* ignore */
  }
}

function selectEntry(entry: ExportPassageEntry): void {
  selectedPassageKey.value = entry.key
  selectedAttemptId.value = String(entry.attempts[0]?.attempt_id ?? '')
}

watch(
  () => props.open,
  async (isOpen) => {
    if (!isOpen) return
    mode.value = props.initialMode ?? 'export'
    previewError.value = ''
    preview.value = null
    await ensurePacks()
    if (props.initialPackId) {
      targetPackId.value = props.initialPackId
    } else if (!targetPackId.value && readingPacks.value.length) {
      targetPackId.value = readingPacks.value[0].id
    }
    if (!selectedPassageKey.value && exportDataset.value?.entries.length) {
      selectEntry(exportDataset.value.entries[0])
    }
    schedulePreview()
  },
  { immediate: true },
)

watch(
  () => exportDataset.value?.entries,
  (entries) => {
    if (!entries?.length) {
      selectedPassageKey.value = ''
      selectedAttemptId.value = ''
      return
    }
    if (!entries.some((e) => e.key === selectedPassageKey.value)) {
      selectEntry(entries[0])
    }
  },
)

watch([mode, selectedPassageKey, selectedAttemptId, targetPackId, analysisText], () => {
  schedulePreview()
})

function buildExportPayload(dryRun: boolean) {
  const ds = exportDataset.value
  const entry = selectedEntry.value
  const attempt = selectedAttempt.value
  if (!ds || !entry || !attempt) return null
  const aid = String(attempt.attempt_id ?? '')
  return {
    passage: entry.passage,
    attempt,
    questions: ds.questionsByAttempt.get(aid) ?? [],
    groups: ds.groupsByAttempt.get(aid) ?? [],
    analysisText: analysisText.value,
    keepLexicon: true,
    recordHistory: recordHistory.value,
    dryRun,
  }
}

function schedulePreview(): void {
  window.clearTimeout(previewTimer)
  previewError.value = ''

  if (mode.value === 'existing' && !analysisText.value.trim()) {
    preview.value = null
    previewLoading.value = false
    return
  }
  if (mode.value === 'export' && !selectedEntry.value) {
    preview.value = null
    previewLoading.value = false
    return
  }

  previewTimer = window.setTimeout(runPreview, 280)
}

async function runPreview(): Promise<void> {
  const seq = ++previewSeq
  previewLoading.value = true
  previewError.value = ''
  try {
    if (mode.value === 'export') {
      const payload = buildExportPayload(true)
      if (!payload) {
        preview.value = null
        return
      }
      const res = await api.packImportFromExport(payload)
      if (seq !== previewSeq) return
      preview.value = res
    } else {
      if (!targetPackId.value || !analysisText.value.trim()) {
        preview.value = null
        return
      }
      const res = await api.packUpdateAnalysis(targetPackId.value, {
        analysisText: analysisText.value,
        keepLexicon: true,
        dryRun: true,
      })
      if (seq !== previewSeq) return
      preview.value = res
    }
  } catch (err) {
    if (seq !== previewSeq) return
    preview.value = null
    previewError.value = err instanceof Error ? err.message : t('toast.loadFailed')
  } finally {
    if (seq === previewSeq) previewLoading.value = false
  }
}

async function handleFiles(files: FileList | null): Promise<void> {
  if (!files || files.length === 0) return
  readingFiles.value = true
  try {
    // 若拖入的是单个 .json 文件，直接作为 AI 复盘 JSON 填入文本框
    if (files.length === 1 && files[0].name.toLowerCase().endsWith('.json')) {
      analysisText.value = await files[0].text()
      return
    }
    const count = await ingestExportFiles(files)
    if (count === 0) {
      toast(t('import.noJsonlFound'))
    }
  } catch (err) {
    toast(err instanceof Error ? err.message : t('toast.loadFailed'))
  } finally {
    readingFiles.value = false
  }
}

function onDrop(event: DragEvent): void {
  dragging.value = false
  void handleFiles(event.dataTransfer?.files ?? null)
}

async function onJsonFilePick(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  try {
    analysisText.value = await file.text()
  } finally {
    input.value = ''
  }
}

async function copyPrompt(): Promise<void> {
  if (copyingPrompt.value) return
  copyingPrompt.value = true
  try {
    let promptText = ''
    if (mode.value === 'export') {
      const payload = buildExportPayload(true)
      if (!payload) return
      const res = await api.packExportPrompt({
        passage: payload.passage,
        attempt: payload.attempt,
        questions: payload.questions,
        groups: payload.groups,
      })
      promptText = res.prompt
    } else {
      if (!targetPackId.value) return
      const res = await api.packPrompt(targetPackId.value)
      promptText = res.prompt
    }
    await navigator.clipboard.writeText(promptText)
    toast(t('import.promptCopied'))
  } catch (err) {
    toast(err instanceof Error ? err.message : t('toast.loadFailed'))
  } finally {
    copyingPrompt.value = false
  }
}

async function submit(): Promise<void> {
  if (!canSubmit.value) return
  saving.value = true
  try {
    if (mode.value === 'export') {
      const payload = buildExportPayload(false)
      if (!payload) return
      const res = await api.packImportFromExport(payload)
      toast(t('import.success'))
      emit('imported', res.id)
    } else {
      const res = await api.packUpdateAnalysis(targetPackId.value, {
        analysisText: analysisText.value,
        keepLexicon: true,
        dryRun: false,
      })
      toast(t('import.success'))
      emit('imported', res.id)
    }
  } catch (err) {
    previewError.value = err instanceof Error ? err.message : t('toast.loadFailed')
  } finally {
    saving.value = false
  }
}

function attemptSummary(attempt: Record<string, unknown>): string {
  const c = attempt.correct ?? 0
  const tot = attempt.total ?? 0
  const dur = fmtDuration(Number(attempt.duration_sec ?? 0))
  const sub = String(attempt.submitted_at ?? '').slice(0, 10)
  return [sub, `${c}/${tot}`, dur].filter(Boolean).join(' · ')
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && props.open) {
    emit('close')
  }
}

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  window.clearTimeout(previewTimer)
  document.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="backdrop" data-no-lookup @click.self="emit('close')">
      <div class="modal" role="dialog" aria-modal="true" :aria-label="t('import.title')">
        <header class="m-head">
          <div class="m-title-row">
            <h2 class="serif">{{ t('import.title') }}</h2>
            <button
              type="button"
              class="close-btn"
              :aria-label="t('common.close')"
              @click="emit('close')"
            >
              <Icon name="x" :size="16" />
            </button>
          </div>

          <Segmented
            v-model="mode"
            :options="[
              { value: 'export', label: t('import.mode.export') },
              { value: 'existing', label: t('import.mode.existing') },
            ]"
          />
        </header>

        <div class="m-body">
          <!-- 模式一：从 idictation 导出的 4 个 JSONL 新建/合并整篇 -->
          <template v-if="mode === 'export'">
            <section class="step">
              <div class="step-head">
                <span class="step-label">{{ t('import.stepFiles') }}</span>
                <div class="file-btns">
                  <AppButton size="sm" variant="outline" @click="folderInput?.click()">
                    <Icon name="upload" :size="14" />
                    {{ t('import.pickFolder') }}
                  </AppButton>
                  <AppButton size="sm" @click="filesInput?.click()">
                    {{ t('import.pickFiles') }}
                  </AppButton>
                </div>
              </div>

              <input
                ref="folderInput"
                type="file"
                webkitdirectory
                multiple
                hidden
                @change="handleFiles(($event.target as HTMLInputElement).files)"
              />
              <input
                ref="filesInput"
                type="file"
                accept=".jsonl,.json"
                multiple
                hidden
                @change="handleFiles(($event.target as HTMLInputElement).files)"
              />

              <div
                class="dropzone"
                :class="{ dragging, ready: datasetComplete }"
                @dragover.prevent="dragging = true"
                @dragleave.prevent="dragging = false"
                @drop.prevent="onDrop"
              >
                <p class="drop-hint">{{ t('import.dropHint') }}</p>
                <div class="file-pills">
                  <span class="fpill" :class="{ ok: exportDataset?.hasPassages }">
                    passages {{ exportDataset?.hasPassages ? `✓ ${exportDataset.passagesCount}` : '—' }}
                  </span>
                  <span class="fpill" :class="{ ok: exportDataset?.hasAttempts }">
                    attempts {{ exportDataset?.hasAttempts ? `✓ ${exportDataset.attemptsCount}` : '—' }}
                  </span>
                  <span class="fpill" :class="{ ok: exportDataset?.hasQuestions }">
                    questions {{ exportDataset?.hasQuestions ? `✓ ${exportDataset.questionsCount}` : '—' }}
                  </span>
                  <span class="fpill" :class="{ ok: exportDataset?.hasGroups }">
                    groups {{ exportDataset?.hasGroups ? `✓ ${exportDataset.groupsCount}` : '—' }}
                  </span>
                </div>
              </div>
            </section>

            <section v-if="exportDataset" class="step">
              <div class="step-head">
                <span class="step-label">{{ t('import.stepPassage') }}</span>
                <AppButton
                  v-if="selectedEntry"
                  size="sm"
                  variant="outline"
                  :disabled="copyingPrompt"
                  @click="copyPrompt"
                >
                  <Icon name="copy" :size="14" />
                  {{ t('import.copyPrompt') }}
                </AppButton>
              </div>

              <input
                v-model="passageQuery"
                type="search"
                class="input"
                :placeholder="t('import.searchPassage')"
              />

              <div v-if="filteredEntries.length" class="entry-list">
                <button
                  v-for="entry in filteredEntries"
                  :key="entry.key"
                  type="button"
                  class="entry-row"
                  :class="{ on: entry.key === selectedPassageKey }"
                  @click="selectEntry(entry)"
                >
                  <div class="entry-main">
                    <span class="entry-meta">
                      {{ entry.book }} · {{ entry.test }} · {{ entry.part }}
                    </span>
                    <span class="entry-title serif">{{ entry.title }}</span>
                  </div>
                  <div class="entry-right">
                    <span
                      v-if="packMap.has(entry.derivedId)"
                      class="mini-pill"
                      :class="{ rev: packMap.get(entry.derivedId)?.hasReview }"
                    >
                      {{
                        packMap.get(entry.derivedId)?.hasReview
                          ? t('read.reviewReady')
                          : t('import.inLibrary')
                      }}
                    </span>
                    <span class="entry-score num">
                      {{ entry.attempts[0]?.correct }} / {{ entry.attempts[0]?.total }}
                    </span>
                  </div>
                </button>
              </div>
              <p v-else class="muted-note">{{ t('import.noPassages') }}</p>

              <div v-if="selectedEntry && selectedEntry.attempts.length > 1" class="sub-select">
                <select v-model="selectedAttemptId" class="select">
                  <option
                    v-for="att in selectedEntry.attempts"
                    :key="String(att.attempt_id)"
                    :value="String(att.attempt_id)"
                  >
                    {{ attemptSummary(att) }}
                  </option>
                </select>
              </div>
            </section>
          </template>

          <!-- 模式二：为站内已有篇目补录或更新 AI 复盘 -->
          <template v-else>
            <section class="step">
              <div class="step-head">
                <span class="step-label">{{ t('import.stepExistingTarget') }}</span>
                <AppButton
                  v-if="targetPackId"
                  size="sm"
                  variant="outline"
                  :disabled="copyingPrompt"
                  @click="copyPrompt"
                >
                  <Icon name="copy" :size="14" />
                  {{ t('import.copyPrompt') }}
                </AppButton>
              </div>

              <select v-model="targetPackId" class="select">
                <option v-for="p in readingPacks" :key="p.id" :value="p.id">
                  {{ p.meta.book }} · {{ p.meta.test }} · {{ p.meta.passage }} — {{ p.meta.title }}
                </option>
              </select>
            </section>
          </template>

          <!-- 通用：粘贴或上传 AI 复盘 JSON -->
          <section v-if="mode === 'existing' || exportDataset" class="step">
            <div class="step-head">
              <span class="step-label">
                {{ mode === 'export' ? t('import.stepAnalysis') : t('import.stepExistingAnalysis') }}
              </span>
              <button type="button" class="link-btn" @click="jsonFileInput?.click()">
                {{ t('import.loadJsonFile') }}
              </button>
              <input
                ref="jsonFileInput"
                type="file"
                accept=".json,.txt,.md"
                hidden
                @change="onJsonFilePick"
              />
            </div>

            <textarea
              v-model="analysisText"
              class="textarea mono"
              rows="7"
              spellcheck="false"
              :placeholder="t('import.analysisPlaceholder')"
            />

            <!-- 实时解析预览与校验结果 -->
            <div v-if="previewError" class="callout bad">
              {{ previewError }}
            </div>

            <div v-else-if="preview" class="callout ok">
              <div class="pv-top">
                <span class="pv-id mono">{{ preview.id }}</span>
                <span class="pv-tag">
                  {{ preview.exists ? t('import.previewUpdate') : t('import.previewNew') }}
                </span>
                <span v-if="preview.counts" class="pv-counts num">
                  {{
                    t('import.previewCounts', {
                      p: preview.counts.paragraphs,
                      s: preview.counts.sentences,
                      q: preview.counts.questions,
                    })
                  }}
                </span>
                <span v-if="preview.attempt" class="pv-score num">
                  {{ preview.attempt.score }} / {{ preview.attempt.total }}
                </span>
              </div>

              <template v-if="preview.analysis.hasReview || preview.analysis.hasGuide || preview.analysis.lexiconCount">
                <div v-if="preview.analysis.hasReview" class="pv-line">
                  <b>{{ t('reader.rail.review') }}: </b>{{ preview.analysis.reviewTitle || t('import.untitled') }}
                  <span class="pv-sub num">
                    {{
                      t('import.reviewCoverage', {
                        q: preview.analysis.coveredQuestions,
                        d: preview.analysis.diagnosisCount,
                      })
                    }}
                  </span>
                </div>
                <div v-if="preview.analysis.hasGuide" class="pv-line">
                  <b>{{ t('reader.tab.guide') }}: </b>{{ preview.analysis.guideTitle || t('import.detected') }}
                  <span class="pv-sub num">
                    {{ t('import.guideBandCount', { n: preview.analysis.bandCount }) }}
                  </span>
                </div>
                <div v-if="preview.analysis.lexiconCount" class="pv-line">
                  <b>{{ t('import.lexiconAdded') }}</b>{{ t('import.lexiconAddedCount', { n: preview.analysis.lexiconCount }) }}
                </div>
              </template>
              <p v-else-if="mode === 'export'" class="pv-empty">
                {{ t('import.previewNoReview') }}
              </p>

              <div v-if="preview.warnings.length" class="warnings">
                <div class="warn-head">
                  {{ t('import.warningsTitle', { n: preview.warnings.length }) }}
                </div>
                <ul>
                  <li v-for="(w, i) in preview.warnings" :key="i">{{ w }}</li>
                </ul>
              </div>
            </div>
          </section>
        </div>

        <footer class="m-foot">
          <label v-if="mode === 'export'" class="chk">
            <input v-model="recordHistory" type="checkbox" />
            <span>{{ t('import.recordHistory') }}</span>
          </label>
          <span v-else />

          <div class="foot-btns">
            <AppButton @click="emit('close')">{{ t('common.cancel') }}</AppButton>
            <AppButton variant="primary" :disabled="!canSubmit" @click="submit">
              {{
                saving
                  ? t('import.importing')
                  : mode === 'export'
                    ? t('import.submitExport')
                    : t('import.submitExisting')
              }}
            </AppButton>
          </div>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: grid;
  place-items: center;
  padding: 16px;
  background: color-mix(in srgb, #000 36%, transparent);
  backdrop-filter: blur(2px);
}

.modal {
  display: flex;
  flex-direction: column;
  width: min(720px, 100%);
  max-height: min(88svh, 820px);
  border: 0.5px solid var(--line-soft);
  border-radius: var(--radius-xl);
  background: var(--bg-raise);
  color: var(--fg);
  box-shadow: var(--shadow-md);
  animation: panel-in 0.18s var(--ease-out-quart);
}

.m-head {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 18px 22px 14px;
  border-bottom: 0.5px solid var(--line-hair);
}

.m-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.m-title-row h2 {
  margin: 0;
  font-size: 21px;
  font-weight: 500;
}

.close-btn {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  color: var(--fg-3);
}

.close-btn:hover {
  background: var(--bg-sunken);
  color: var(--fg);
}

.m-body {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 18px;
  overflow-y: auto;
  padding: 18px 22px;
}

.step {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.step-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.step-label {
  color: var(--fg);
  font-size: var(--text-sm);
  font-weight: 500;
}

.file-btns {
  display: flex;
  gap: 6px;
}

.dropzone {
  padding: 14px 16px;
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius-md);
  background: var(--bg-subtle);
  transition: border-color 0.15s, background-color 0.15s;
}

.dropzone.dragging {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, var(--bg-subtle));
}

.dropzone.ready {
  border-style: solid;
  border-color: var(--line-soft);
}

.drop-hint {
  margin: 0 0 10px;
  color: var(--fg-2);
  font-size: var(--text-xs);
}

.file-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.fpill {
  padding: 2px 8px;
  border: 0.5px solid var(--line-soft);
  border-radius: var(--radius-pill);
  background: var(--bg-raise);
  color: var(--fg-3);
  font-family: var(--font-mono);
  font-size: 11px;
}

.fpill.ok {
  border-color: var(--ok-line);
  background: var(--ok-bg);
  color: var(--ok);
}

.input,
.select,
.textarea {
  width: 100%;
  padding: 8px 11px;
  border: 0.5px solid var(--line-soft);
  border-radius: var(--radius-sm);
  background: var(--input-bg);
  color: var(--fg);
  font-size: var(--text-sm);
  transition: border-color 0.15s;
}

.input:focus,
.select:focus,
.textarea:focus {
  outline: none;
  border-color: var(--focus);
}

.textarea {
  resize: vertical;
  min-height: 120px;
  font-size: 12.5px;
  line-height: 1.55;
}

.mono {
  font-family: var(--font-mono);
}

.entry-list {
  display: flex;
  flex-direction: column;
  max-height: 196px;
  overflow-y: auto;
  border: 0.5px solid var(--line-hair);
  border-radius: var(--radius-md);
  background: var(--bg-page);
}

.entry-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  padding: 9px 12px;
  text-align: left;
  transition: background-color 0.12s;
}

.entry-row + .entry-row {
  border-top: 0.5px solid var(--line-hair);
}

.entry-row:hover {
  background: var(--bg-subtle);
}

.entry-row.on {
  background: color-mix(in srgb, var(--accent) 12%, var(--bg-page));
  box-shadow: inset 2px 0 0 var(--accent);
}

.entry-main {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.entry-meta {
  color: var(--fg-3);
  font-size: 11px;
}

.entry-title {
  font-size: 14.5px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.entry-right {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 8px;
}

.mini-pill {
  padding: 1px 6px;
  border: 0.5px solid var(--line-soft);
  border-radius: var(--radius-xs);
  color: var(--fg-3);
  font-size: 10px;
}

.mini-pill.rev {
  border-color: color-mix(in srgb, var(--accent) 40%, transparent);
  color: var(--accent-strong);
}

.entry-score {
  color: var(--fg-2);
  font-family: var(--font-serif);
  font-size: 13.5px;
  font-weight: 500;
}

.muted-note {
  margin: 4px 0 0;
  color: var(--fg-3);
  font-size: var(--text-xs);
}

.link-btn {
  padding: 0;
  color: var(--fg-2);
  font-size: var(--text-xs);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.link-btn:hover {
  color: var(--fg);
}

.callout {
  padding: 11px 14px;
  border: 0.5px solid var(--line-soft);
  border-radius: var(--radius-md);
  font-size: var(--text-xs);
  line-height: 1.6;
}

.callout.ok {
  background: var(--bg-subtle);
}

.callout.bad {
  border-color: var(--bad-line);
  background: var(--bad-bg);
  color: var(--bad);
}

.pv-top {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.pv-id {
  padding: 1px 6px;
  border-radius: var(--radius-xs);
  background: var(--bg-sunken);
  font-size: 11.5px;
  font-weight: 600;
}

.pv-tag {
  color: var(--accent-strong);
  font-weight: 500;
}

.pv-counts,
.pv-score {
  color: var(--fg-2);
}

.pv-score {
  margin-left: auto;
  font-weight: 600;
}

.pv-line {
  color: var(--fg);
}

.pv-sub {
  color: var(--fg-3);
}

.pv-empty {
  margin: 0;
  color: var(--fg-3);
}

.warnings {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 0.5px dashed var(--line-soft);
  color: var(--warn);
}

.warn-head {
  font-weight: 600;
  margin-bottom: 2px;
}

.warnings ul {
  margin: 0;
  padding-left: 18px;
}

.m-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 22px;
  border-top: 0.5px solid var(--line-hair);
}

.chk {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--fg-2);
  font-size: var(--text-xs);
  cursor: pointer;
}

.chk input {
  accent-color: var(--accent);
}

.foot-btns {
  display: flex;
  gap: 8px;
  margin-left: auto;
}

@media (max-width: 640px) {
  .m-head,
  .m-body,
  .m-foot {
    padding-left: 16px;
    padding-right: 16px;
  }
}
</style>
