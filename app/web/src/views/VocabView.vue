<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { api, ttsUrl } from '../api'
import { t } from '../i18n'
import { refreshVocabCounts } from '../state'
import { toast } from '../toast'
import type { ReviewGrade, VocabItem, VocabStats } from '../types'
import { fmtShort } from '../utils/format'
import { playUrl, stopAudio } from '../utils/audio'
import { splitHighlight } from '../utils/words'
import AppButton from '../components/AppButton.vue'
import AudioButton from '../components/AudioButton.vue'
import Card from '../components/Card.vue'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'
import Segmented from '../components/Segmented.vue'

const items = ref<VocabItem[]>([])
const stats = ref<VocabStats | null>(null)
const route = useRoute()
const query = ref(typeof route.query.q === 'string' ? route.query.q : '')
const filter = ref<string>('all')
const selectedId = ref(0)
const loading = ref(true)
const failed = ref(false)

const reviewing = ref(false)
const queue = ref<VocabItem[]>([])
const queueIndex = ref(0)
const revealed = ref(false)
const reviewDone = ref(false)
const reviewedCount = ref(0)
const cardStart = ref(Date.now())
const grading = ref(false)

let searchTimer = 0

const selected = computed(() => items.value.find((item) => item.id === selectedId.value) ?? null)
const current = computed(() => queue.value[queueIndex.value] ?? null)

const filterOptions = computed(() => [
  { value: 'due', label: t('vocab.filter.due'), count: stats.value?.dueNow ?? 0 },
  { value: 'new', label: t('vocab.filter.new'), count: stats.value?.byState.new ?? 0 },
  {
    value: 'learning',
    label: t('vocab.filter.learning'),
    count: stats.value?.byState.learning ?? 0,
  },
  { value: 'all', label: t('vocab.filter.all'), count: stats.value?.total ?? 0 },
])

const grades: { value: ReviewGrade; key: string; label: string }[] = [
  { value: 'again', key: '1', label: 'vocab.grade.again' },
  { value: 'hard', key: '2', label: 'vocab.grade.hard' },
  { value: 'good', key: '3', label: 'vocab.grade.good' },
  { value: 'easy', key: '4', label: 'vocab.grade.easy' },
]

function stateLabel(item: VocabItem): string {
  if (item.state === 'new') return t('vocab.filter.new')
  if (item.state === 'learning') return t('vocab.filter.learning')
  return t('vocab.state.review')
}

async function load(): Promise<void> {
  loading.value = true
  failed.value = false
  try {
    const state = filter.value === 'new' || filter.value === 'learning' ? filter.value : undefined
    const [list, counts] = await Promise.all([
      api.vocabList({
        q: query.value.trim(),
        due: filter.value === 'due',
        state,
        limit: 500,
      }),
      api.vocabStats(),
    ])
    items.value = list.items
    stats.value = counts
    if (!items.value.some((item) => item.id === selectedId.value)) {
      selectedId.value = items.value[0]?.id ?? 0
    }
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}

function select(item: VocabItem): void {
  selectedId.value = item.id
  if (window.innerWidth <= 900) {
    nextTick(() => {
      document.querySelector('.detail')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }
}

function scheduleLoad(): void {
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(load, 220)
}

async function saveNote(): Promise<void> {
  if (!selected.value) return
  try {
    await api.vocabPatch(selected.value.id, { note: selected.value.note })
    toast(t('toast.saved'))
  } catch (error) {
    toast(error instanceof Error ? error.message : t('toast.loadFailed'))
  }
}

async function remove(item: VocabItem): Promise<void> {
  try {
    await api.vocabDelete(item.id)
    toast(t('toast.removed'))
    selectedId.value = 0
    await load()
    await refreshVocabCounts()
  } catch (error) {
    toast(error instanceof Error ? error.message : t('toast.loadFailed'))
  }
}

function playCurrent(): void {
  const word = current.value
  if (!word) return
  void playUrl(word.audioUrl || ttsUrl(word.word), word.word)
}

async function openReview(): Promise<void> {
  try {
    const data = await api.vocabReviewQueue(30)
    if (data.items.length === 0) {
      toast(t('vocab.noDue'))
      return
    }
    queue.value = data.items
    queueIndex.value = 0
    revealed.value = false
    reviewDone.value = false
    reviewedCount.value = 0
    cardStart.value = Date.now()
    reviewing.value = true
    playCurrent()
  } catch (error) {
    toast(error instanceof Error ? error.message : t('toast.loadFailed'))
  }
}

function reveal(): void {
  revealed.value = true
}

async function grade(value: ReviewGrade): Promise<void> {
  const word = current.value
  if (!word || !revealed.value || grading.value) return
  grading.value = true
  try {
    await api.vocabReview(word.id, value, Date.now() - cardStart.value)
    reviewedCount.value += 1
    if (queueIndex.value + 1 < queue.value.length) {
      queueIndex.value += 1
      revealed.value = false
      cardStart.value = Date.now()
      playCurrent()
    } else {
      reviewDone.value = true
      await load()
      await refreshVocabCounts()
    }
  } catch (error) {
    toast(error instanceof Error ? error.message : t('toast.loadFailed'))
  } finally {
    grading.value = false
  }
}

async function closeReview(): Promise<void> {
  reviewing.value = false
  stopAudio()
  await load()
  await refreshVocabCounts()
}

function onKey(event: KeyboardEvent): void {
  if (!reviewing.value) return
  if (event.key === 'Escape') {
    void closeReview()
    return
  }
  if (event.code === 'Space') {
    const tag = (event.target as HTMLElement | null)?.tagName ?? ''
    if (!['INPUT', 'TEXTAREA', 'BUTTON'].includes(tag)) {
      event.preventDefault()
      playCurrent()
    }
  }
  if (!revealed.value || reviewDone.value) return
  const found = grades.find((item) => item.key === event.key)
  if (found) {
    event.preventDefault()
    void grade(found.value)
  }
}

watch([query, filter], scheduleLoad)
watch(
  () => route.query.q,
  (value) => {
    if (typeof value === 'string' && value !== query.value) query.value = value
  },
)

onMounted(() => {
  load()
  document.addEventListener('keydown', onKey)
})

onBeforeUnmount(() => {
  window.clearTimeout(searchTimer)
  document.removeEventListener('keydown', onKey)
  stopAudio()
})
</script>

<template>
  <div class="page">
    <PageHeader
      :eyebrow="t('vocab.count', { n: stats?.total ?? 0 })"
      :title="t('nav.vocab')"
    >
      <template #actions>
        <AppButton
          variant="primary"
          :disabled="!stats?.dueNow"
          @click="openReview"
        >
          {{ t('vocab.startReview') }}
          <span v-if="stats?.dueNow" class="badge num">{{ stats?.dueNow }}</span>
        </AppButton>
      </template>
    </PageHeader>

    <Card v-if="!loading && stats && stats.total === 0" padding="lg" class="first-empty">
      <p class="first-empty-title serif">{{ t('vocab.empty') }}</p>
      <RouterLink to="/read" class="first-empty-link">
        {{ t('vocab.emptyHint') }}
        <Icon name="arrowUpRight" :size="14" />
      </RouterLink>
    </Card>

    <div v-else class="layout">
      <Card padding="none" class="list-card">
        <div class="list-head">
          <div class="search">
            <Icon name="search" :size="15" class="search-icon" />
            <input v-model="query" type="search" :placeholder="t('vocab.search')" />
          </div>
          <div class="filters">
            <Segmented v-model="filter" :options="filterOptions" :aria-label="t('nav.vocab')" />
          </div>
        </div>

        <div v-if="loading" class="list-state">{{ t('common.loading') }}</div>
        <div v-else-if="failed" class="list-state">
          {{ t('toast.loadFailed') }}
          <button class="link" @click="load">{{ t('common.retry') }}</button>
        </div>

        <div v-else class="list">
          <button
            v-for="item in items"
            :key="item.id"
            type="button"
            class="row"
            :class="{ on: item.id === selectedId }"
            @click="select(item)"
          >
            <span class="row-main">
              <span class="word">{{ item.word }}</span>
              <span class="gloss">{{ item.gloss || '—' }}</span>
            </span>
            <i v-if="item.due" class="due" aria-hidden="true" />
          </button>

          <div v-if="items.length === 0" class="empty">
            <p>{{ query ? t('common.empty') : t('vocab.empty') }}</p>
            <RouterLink v-if="!query" to="/read" class="empty-link">
              {{ t('vocab.emptyHint') }}
              <Icon name="arrowUpRight" :size="13" />
            </RouterLink>
          </div>
        </div>
      </Card>

      <div class="detail">
        <Card v-if="selected" padding="lg" class="detail-card">
          <div class="detail-head">
            <h2 class="serif">{{ selected.word }}</h2>
            <AudioButton :text="selected.word" :size="34" />
          </div>
          <div v-if="selected.pos || selected.phonetic" class="sub">
            <span v-if="selected.pos">{{ selected.pos }}</span>
            <span v-if="selected.phonetic" class="mono">{{ selected.phonetic }}</span>
          </div>
          <p class="gloss">{{ selected.gloss || '—' }}</p>

          <section v-if="selected.contexts.length" class="contexts">
            <div v-for="(context, index) in selected.contexts" :key="index" class="context">
              <p class="en">
                <template v-for="(part, partIndex) in splitHighlight(context.en || '', selected.word)" :key="partIndex">
                  <span :class="{ hit: part.hit }">{{ part.text }}</span>
                </template>
              </p>
              <p v-if="context.zh" class="zh">{{ context.zh }}</p>
            </div>
          </section>

          <label class="note">
            <span class="label">{{ t('vocab.note') }}</span>
            <textarea
              v-model="selected.note"
              rows="2"
              :placeholder="t('vocab.notePlaceholder')"
              @blur="saveNote"
            />
          </label>

          <div class="facts">
            <div class="fact">
              <span class="fact-label">{{ t('vocab.state') }}</span>
              <span class="fact-value">{{ stateLabel(selected) }}</span>
            </div>
            <div class="fact">
              <span class="fact-label">{{ t('vocab.next') }}</span>
              <span class="fact-value num">{{ selected.dueAt ? fmtShort(selected.dueAt) : '—' }}</span>
            </div>
            <div class="fact">
              <span class="fact-label">{{ t('vocab.repsLabel') }}</span>
              <span class="fact-value num">{{ selected.reps }}</span>
            </div>
            <div class="fact">
              <span class="fact-label">{{ t('vocab.lapsesLabel') }}</span>
              <span class="fact-value num">{{ selected.lapses }}</span>
            </div>
          </div>

          <button type="button" class="delete" @click="remove(selected)">
            <Icon name="trash" :size="15" />
            {{ t('common.delete') }}
          </button>
        </Card>

        <Card v-else padding="lg" class="detail-card empty-detail">
          <p>{{ t('vocab.detailEmpty') }}</p>
        </Card>
      </div>
    </div>
  </div>

  <Teleport to="body">
    <Transition name="modal">
      <div v-if="reviewing" class="mask" @click.self="closeReview">
        <div class="panel" role="dialog" aria-modal="true" :aria-label="t('vocab.reviewing')">
          <div class="panel-head">
            <span class="progress num">{{ queueIndex + 1 }} / {{ queue.length }}</span>
            <button type="button" class="close" :aria-label="t('common.close')" @click="closeReview">
              <Icon name="x" :size="16" />
            </button>
          </div>

          <template v-if="!reviewDone && current">
            <div class="card-front">
              <div class="front-word serif">{{ current.word }}</div>
              <AudioButton :text="current.word" :size="40" />
            </div>

            <div v-if="!revealed" class="reveal">
              <AppButton variant="secondary" @click="reveal">{{ t('vocab.show') }}</AppButton>
            </div>

            <div v-else class="reveal-body">
              <p class="front-gloss">{{ current.gloss || '—' }}</p>
              <p v-if="current.contexts[0]?.en" class="front-context">
                {{ current.contexts[0].en }}
              </p>
              <p v-if="current.contexts[0]?.zh" class="front-context zh">
                {{ current.contexts[0].zh }}
              </p>
            </div>

            <div v-if="revealed" class="grades">
              <button
                v-for="item in grades"
                :key="item.value"
                type="button"
                class="grade"
                :class="item.value"
                :disabled="grading"
                @click="grade(item.value)"
              >
                <span class="key num">{{ item.key }}</span>
                <span class="grade-label">{{ t(item.label) }}</span>
              </button>
            </div>
          </template>

          <div v-else class="review-done">
            <Icon name="check" :size="24" class="done-icon" />
            <h3 class="serif">{{ t('vocab.reviewDone') }}</h3>
            <p class="muted">{{ t('vocab.reviewed', { n: reviewedCount }) }}</p>
            <AppButton variant="primary" @click="closeReview">{{ t('common.done') }}</AppButton>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.first-empty {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 12px;
  max-width: 520px;
  padding: 48px 40px;
}

.first-empty-title {
  font-size: 24px;
  font-weight: 500;
}

.first-empty-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--fg);
  font-size: var(--text-sm);
  text-decoration: underline;
  text-decoration-color: var(--line-strong);
  text-underline-offset: 3px;
}

.first-empty-link:hover {
  text-decoration-color: var(--accent);
}

.layout {
  display: grid;
  grid-template-columns: 376px minmax(0, 1fr);
  align-items: start;
  gap: var(--space-5);
}

.list-card {
  position: sticky;
  top: 24px;
  overflow: hidden;
}

.list-head {
  padding: 14px 16px;
  border-bottom: 0.5px solid var(--line-hair);
}

.search {
  position: relative;
}

.search input {
  width: 100%;
  height: 34px;
  padding: 0 10px 0 32px;
  border: 1px solid var(--line-hair);
  border-radius: var(--radius-md);
  background: var(--input-bg);
  font-size: var(--text-sm);
  outline: none;
}

.search input:focus {
  border-color: var(--focus);
}

.search input::-webkit-search-cancel-button {
  display: none;
}

.search-icon {
  position: absolute;
  top: 50%;
  left: 10px;
  transform: translateY(-50%);
  color: var(--fg-3);
  pointer-events: none;
}

.filters {
  margin-top: 10px;
  overflow-x: auto;
}

.list {
  max-height: calc(100svh - 320px);
  overflow: auto;
}

.row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 10px 16px;
  border-left: 2px solid transparent;
  text-align: left;
  transition: background-color 0.15s var(--ease-out-cubic);
}

.row + .row {
  border-top: 0.5px solid var(--line-hair);
}

.row:hover {
  background: var(--bg-subtle);
}

.row.on {
  background: var(--bg-sunken);
  border-left-color: var(--accent);
}

.row-main {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.word {
  font-size: 14px;
  font-weight: 500;
}

.gloss {
  color: var(--fg-3);
  font-size: var(--text-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.due {
  width: 6px;
  height: 6px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--accent);
}

.list-state {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 40px 16px;
  color: var(--fg-3);
  font-size: var(--text-sm);
}

.link {
  color: var(--fg);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.empty {
  padding: 48px 24px;
  text-align: center;
  color: var(--fg-3);
  font-size: var(--text-sm);
}

.empty-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 10px;
  color: var(--fg);
}

.detail-card {
  min-height: 420px;
}

.detail {
  scroll-margin-top: calc(var(--topbar-h) + 12px);
}

.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.detail-head h2 {
  font-size: clamp(30px, 3.4vw, 40px);
  font-weight: 500;
  line-height: 1.1;
  word-break: break-word;
}

.sub {
  display: flex;
  gap: 10px;
  margin-top: 6px;
  color: var(--fg-3);
  font-size: var(--text-xs);
}

.mono {
  font-family: var(--font-mono);
}

.detail-card .gloss {
  margin-top: 18px;
  color: var(--fg);
  font-size: 17px;
  line-height: 1.6;
  white-space: normal;
}

.contexts {
  margin-top: var(--space-5);
}

.context + .context {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 0.5px solid var(--line-hair);
}

.en {
  color: var(--fg-2);
  font-size: 14px;
  line-height: 1.6;
}

.hit {
  color: var(--fg);
  font-weight: 500;
  box-shadow: inset 0 -1px 0 var(--accent);
}

.zh {
  margin-top: 4px;
  color: var(--fg-3);
  font-size: var(--text-xs);
  line-height: 1.55;
}

.note {
  display: block;
  margin-top: var(--space-5);
}

.label {
  display: block;
  margin-bottom: 6px;
  color: var(--fg-3);
  font-size: var(--text-xs);
}

.note textarea {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--line-hair);
  border-radius: var(--radius-md);
  background: var(--input-bg);
  font-size: var(--text-sm);
  line-height: 1.5;
  resize: vertical;
  outline: none;
}

.note textarea:focus {
  border-color: var(--focus);
}

.facts {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-top: var(--space-5);
  padding-top: var(--space-4);
  border-top: 0.5px solid var(--line-hair);
}

.fact {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.fact-label {
  color: var(--fg-3);
  font-size: var(--text-micro);
}

.fact-value {
  font-size: var(--text-sm);
}

.delete {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: var(--space-5);
  color: var(--fg-3);
  font-size: var(--text-xs);
  transition: color 0.2s var(--ease-out-cubic);
}

.delete:hover {
  color: var(--bad);
}

.empty-detail {
  display: grid;
  place-items: center;
  color: var(--fg-3);
  font-size: var(--text-sm);
}

.badge {
  display: inline-grid;
  place-items: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: var(--radius-pill);
  background: var(--bg-page);
  color: var(--fg);
  font-size: 11px;
}

.mask {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(20, 20, 19, 0.36);
}

.panel {
  width: min(560px, 100%);
  padding: 20px 24px 28px;
  border: 0.5px solid var(--line-hair);
  border-radius: var(--radius-xl);
  background: var(--bg-raise);
  box-shadow: var(--shadow-md);
  animation: panel-in 0.22s var(--ease-out-quart);
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.progress {
  color: var(--fg-3);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
}

.close {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  color: var(--fg-3);
}

.close:hover {
  background: var(--bg-sunken);
  color: var(--fg);
}

.card-front {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  padding: 36px 0 24px;
}

.front-word {
  font-size: clamp(36px, 6vw, 48px);
  font-weight: 500;
  line-height: 1.1;
  text-align: center;
  word-break: break-word;
}

.reveal {
  display: flex;
  justify-content: center;
  padding-bottom: 12px;
}

.reveal-body {
  min-height: 96px;
  padding: 8px 0 20px;
  text-align: center;
}

.front-gloss {
  font-size: 18px;
  line-height: 1.6;
}

.front-context {
  max-width: 46ch;
  margin: 12px auto 0;
  color: var(--fg-3);
  font-size: var(--text-sm);
  line-height: 1.6;
}

.front-context.zh {
  margin-top: 6px;
  color: var(--fg-3);
  font-size: var(--text-xs);
}

.grades {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
  margin-top: 12px;
}

.grade {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 10px 6px;
  border: 1px solid var(--line-hair);
  border-radius: var(--radius-md);
  transition:
    background-color 0.15s var(--ease-out-cubic),
    border-color 0.15s var(--ease-out-cubic);
}

.grade:hover {
  background: var(--bg-subtle);
  border-color: var(--line-strong);
}

.grade:disabled {
  opacity: 0.5;
}

.key {
  color: var(--fg-3);
  font-family: var(--font-mono);
  font-size: 11px;
}

.grade-label {
  font-size: var(--text-xs);
  font-weight: 500;
}

.grade.again .key {
  color: var(--bad);
}

.grade.hard .key {
  color: var(--warn);
}

.grade.good .key {
  color: var(--ok);
}

.grade.easy .key {
  color: var(--fg-2);
}

.review-done {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 48px 0 16px;
  text-align: center;
}

.done-icon {
  color: var(--ok);
}

.review-done h3 {
  font-size: 22px;
  font-weight: 500;
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s var(--ease-out-cubic);
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

@media (max-width: 1100px) {
  .layout {
    grid-template-columns: 320px minmax(0, 1fr);
  }
}

@media (max-width: 900px) {
  .layout {
    grid-template-columns: minmax(0, 1fr);
  }

  .list-card {
    position: static;
  }

  .list {
    max-height: 360px;
  }
}
</style>
