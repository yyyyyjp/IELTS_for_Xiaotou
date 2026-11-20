<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '../api'
import { lang, t } from '../i18n'
import type { DailyItem, Overview, PackStats, WeakWord } from '../types'
import { dateOf, fmtMonthDay, fmtShort, pct } from '../utils/format'
import Card from '../components/Card.vue'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'
import Segmented from '../components/Segmented.vue'

const loading = ref(true)
const failed = ref(false)
const range = ref('30')
const overview = ref<Overview | null>(null)
const daily = ref<DailyItem[]>([])
const rangeFrom = ref('')
const rangeTo = ref('')
const packs = ref<PackStats[]>([])
const weak = ref<WeakWord[]>([])
const heatmap = ref<DailyItem[]>([])

const rangeOptions = computed(() => [
  { value: '7', label: t('stats.range7') },
  { value: '30', label: t('stats.range30') },
  { value: '90', label: t('stats.range90') },
])

const metrics = computed(() => [
  { key: 'days', label: t('stats.studyDays'), value: overview.value?.streak.studyDays ?? 0, unit: '' },
  { key: 'streak', label: t('stats.streak'), value: overview.value?.streak.current ?? 0, unit: t('stats.dayUnit') },
  {
    key: 'accuracy',
    label: t('stats.accuracy'),
    value: pct(
      (overview.value?.totals.attempts ?? 0) > 0
        ? (overview.value?.totals.correct ?? 0) / (overview.value?.totals.attempts ?? 1)
        : 0,
    ),
    unit: '',
  },
  { key: 'answers', label: t('stats.answers'), value: overview.value?.totals.attempts ?? 0, unit: '' },
])

const maxTotal = computed(() => Math.max(1, ...daily.value.map((day) => day.attempts)))
const hasAttempts = computed(() => daily.value.some((day) => day.attempts > 0))

const heatCells = computed<(DailyItem | null)[]>(() => {
  const days = heatmap.value
  if (!days.length) return []
  const first = dateOf(days[0].date)
  const offset = (first.getDay() + 6) % 7
  return [...Array<DailyItem | null>(offset).fill(null), ...days]
})

const weekdayLabels = computed(() =>
  lang.value === 'zh' ? ['一', '', '三', '', '五', '', ''] : ['M', '', 'W', '', 'F', '', ''],
)

function segHeight(count: number): string {
  if (count <= 0) return '0px'
  return `${Math.max(1, (count / maxTotal.value) * 132)}px`
}

function level(count: number): number {
  if (count <= 0) return 0
  if (count <= 3) return 1
  if (count <= 8) return 2
  if (count <= 15) return 3
  return 4
}

function accuracy(part: { correct: number; answered?: number; attempts?: number }): string {
  const total = part.answered ?? part.attempts ?? 0
  return total ? pct(part.correct / total) : '—'
}

async function loadDaily(): Promise<void> {
  const data = await api.statsDaily(Number(range.value))
  daily.value = data.items
  rangeFrom.value = data.from
  rangeTo.value = data.to
}

async function load(): Promise<void> {
  loading.value = true
  failed.value = false
  try {
    const [o, d, p, w, h] = await Promise.all([
      api.statsOverview(),
      api.statsDaily(Number(range.value)),
      api.statsPacks(),
      api.statsWeak(10),
      api.statsDaily(182),
    ])
    overview.value = o
    daily.value = d.items
    rangeFrom.value = d.from
    rangeTo.value = d.to
    packs.value = p.items
    weak.value = w.items
    heatmap.value = h.items
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}

watch(range, () => {
  loadDaily().catch(() => {
    failed.value = true
  })
})

onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader
      :eyebrow="rangeFrom ? `${fmtMonthDay(rangeFrom)} – ${fmtMonthDay(rangeTo)}` : ''"
      :title="t('nav.stats')"
    >
      <template #actions>
        <Segmented v-model="range" :options="rangeOptions" />
      </template>
    </PageHeader>

    <div v-if="loading" class="state">{{ t('common.loading') }}</div>
    <div v-else-if="failed" class="state">
      {{ t('toast.loadFailed') }}
      <button class="retry" @click="load">{{ t('common.retry') }}</button>
    </div>

    <template v-else>
      <div class="metrics">
        <Card v-for="metric in metrics" :key="metric.key" padding="sm" class="metric">
          <div class="metric-label">{{ metric.label }}</div>
          <div class="metric-value">
            <span class="serif num">{{ metric.value }}</span>
            <span v-if="metric.unit" class="unit">{{ metric.unit }}</span>
          </div>
        </Card>
      </div>

      <Card padding="md" class="activity-card">
        <div class="card-head">
          <h2>{{ t('stats.activity') }}</h2>
          <div class="legend">
            <span class="legend-item"><i class="dot dict" />{{ t('stats.dictation') }}</span>
            <span class="legend-item"><i class="dot read" />{{ t('stats.reading') }}</span>
            <span class="legend-item"><i class="dot review" />{{ t('stats.review') }}</span>
          </div>
        </div>

        <div v-if="!hasAttempts" class="chart-empty">{{ t('stats.emptyRange') }}</div>
        <div v-else class="chart">
          <div
            v-for="day in daily"
            :key="day.date"
            class="col"
            :title="`${fmtMonthDay(day.date)} · ${day.attempts}`"
          >
            <div class="stack">
              <div
                v-if="day.review"
                class="seg review"
                :style="{ height: segHeight(day.review) }"
              />
              <div
                v-if="day.reading.answered"
                class="seg read"
                :style="{ height: segHeight(day.reading.answered) }"
              />
              <div
                v-if="day.dictation.attempts"
                class="seg dict"
                :style="{ height: segHeight(day.dictation.attempts) }"
              />
              <i v-if="day.attempts === 0" class="zero" />
            </div>
          </div>
        </div>

        <div class="axis">
          <span>{{ rangeFrom ? fmtMonthDay(rangeFrom) : '' }}</span>
          <span>{{ rangeTo ? fmtMonthDay(rangeTo) : '' }}</span>
        </div>
      </Card>

      <div class="split">
        <Card padding="md">
          <div class="card-head">
            <h2>{{ t('stats.calendar') }}</h2>
          </div>
          <div class="heat-wrap">
            <div class="weekdays" aria-hidden="true">
              <span v-for="(label, index) in weekdayLabels" :key="index">{{ label }}</span>
            </div>
            <div class="heat">
              <span
                v-for="(day, index) in heatCells"
                :key="day ? day.date : `gap-${index}`"
                class="heat-cell"
                :class="day ? `l${level(day.attempts)}` : 'blank'"
                :title="day ? `${fmtMonthDay(day.date)} · ${day.attempts}` : ''"
              />
            </div>
          </div>
          <div class="heat-foot">
            <span>{{ heatmap.length ? fmtMonthDay(heatmap[0].date) : '' }}</span>
            <span>{{ heatmap.length ? fmtMonthDay(heatmap[heatmap.length - 1].date) : '' }}</span>
          </div>
        </Card>

        <Card padding="md">
          <div class="card-head">
            <h2>{{ t('stats.weak') }}</h2>
          </div>
          <div v-if="weak.length" class="weak">
            <RouterLink
              v-for="item in weak"
              :key="item.word"
              :to="{ path: '/vocab', query: { q: item.word } }"
              class="weak-row"
            >
              <span class="weak-main">
                <span class="weak-word">{{ item.word }}</span>
                <span class="weak-gloss">{{ item.gloss || '—' }}</span>
              </span>
              <span class="weak-count num">×{{ item.wrong }}</span>
            </RouterLink>
          </div>
          <div v-else class="empty">{{ t('stats.weakEmpty') }}</div>
        </Card>
      </div>

      <Card padding="none" class="packs">
        <div class="packs-head">
          <h2>{{ t('stats.packs') }}</h2>
          <RouterLink to="/read" class="more">
            {{ t('home.allPacks') }}
            <Icon name="arrowUpRight" :size="13" />
          </RouterLink>
        </div>

        <div class="table-head">
          <span />
          <span>{{ t('stats.readingAccuracy') }}</span>
          <span>{{ t('stats.dictation') }}</span>
          <span>{{ t('stats.last') }}</span>
        </div>

        <RouterLink
          v-for="pack in packs"
          :key="pack.id"
          :to="`/read/${pack.id}`"
          class="pack-row"
        >
          <span class="pack-main">
            <span class="pack-title">{{ pack.meta.title }}</span>
            <span class="pack-meta">{{ pack.meta.book }} · {{ pack.meta.test }} · {{ pack.meta.passage }}</span>
          </span>
          <span class="cell num">{{ accuracy(pack.stats.reading) }}</span>
          <span class="cell num">{{ accuracy(pack.stats.dictation) }}</span>
          <span class="cell num muted">
            {{ pack.stats.lastAt ? fmtShort(pack.stats.lastAt) : t('stats.never') }}
          </span>
        </RouterLink>
        <div v-if="packs.length === 0" class="empty">{{ t('stats.empty') }}</div>
      </Card>
    </template>
  </div>
</template>

<style scoped>
.state {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 48px 0;
  color: var(--fg-3);
  font-size: var(--text-sm);
}

.retry {
  color: var(--fg);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.metric {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 96px;
}

.metric-label {
  color: var(--fg-3);
  font-size: var(--text-xs);
}

.metric-value {
  display: flex;
  align-items: baseline;
  gap: 5px;
}

.metric-value .serif {
  font-family: var(--font-serif);
  font-size: 30px;
  font-weight: 500;
  line-height: 1;
}

.unit {
  color: var(--fg-3);
  font-size: var(--text-micro);
}

.activity-card {
  margin-top: var(--space-5);
}

.card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.card-head h2,
.packs-head h2 {
  font-family: var(--font-serif);
  font-size: 18px;
  font-weight: 500;
}

.legend {
  display: flex;
  gap: 12px;
  color: var(--fg-3);
  font-size: var(--text-micro);
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.dot.dict {
  background: var(--accent);
}

.dot.read {
  background: var(--fg-3);
}

.dot.review {
  background: var(--line-strong);
}

.chart-empty {
  display: grid;
  place-items: center;
  height: 132px;
  color: var(--fg-3);
  font-size: var(--text-sm);
}

.chart {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 132px;
}

.col {
  display: flex;
  flex: 1;
  align-items: flex-end;
  min-width: 1px;
  height: 100%;
}

.stack {
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  width: 100%;
  height: 100%;
}

.seg {
  width: 100%;
}

.seg.dict {
  background: var(--accent);
  border-radius: 1px 1px 0 0;
}

.seg.read {
  background: var(--fg-3);
}

.seg.review {
  background: var(--line-strong);
}

.zero {
  display: block;
  width: 100%;
  height: 2px;
  background: var(--line-hair);
}

.axis {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
  color: var(--fg-3);
  font-size: 11px;
}

.split {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--space-5);
  margin-top: var(--space-5);
}

.heat-wrap {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}

.weekdays {
  display: grid;
  grid-template-rows: repeat(7, 11px);
  gap: 2px;
  padding-top: 0;
  color: var(--fg-3);
  font-size: 10px;
  line-height: 11px;
}

.heat {
  display: grid;
  grid-template-rows: repeat(7, 11px);
  grid-auto-flow: column;
  grid-auto-columns: 11px;
  gap: 2px;
  overflow-x: auto;
  padding-bottom: 2px;
}

.heat-cell {
  width: 11px;
  height: 11px;
  border-radius: 2px;
  background: var(--bg-sunken);
}

.heat-cell.blank {
  background: transparent;
}

.heat-cell.l1 {
  background: rgba(217, 119, 87, 0.2);
}

.heat-cell.l2 {
  background: rgba(217, 119, 87, 0.42);
}

.heat-cell.l3 {
  background: rgba(217, 119, 87, 0.68);
}

.heat-cell.l4 {
  background: rgba(217, 119, 87, 0.95);
}

.heat-foot {
  display: flex;
  justify-content: space-between;
  margin-top: 10px;
  padding-left: 17px;
  color: var(--fg-3);
  font-size: 11px;
}

.weak-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  padding: 8px 0;
  border-top: 0.5px solid var(--line-hair);
}

.weak-row:hover .weak-word {
  text-decoration: underline;
  text-decoration-color: var(--accent);
  text-underline-offset: 3px;
}

.weak-main {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.weak-word {
  font-size: 14px;
  font-weight: 500;
}

.weak-gloss {
  color: var(--fg-3);
  font-size: var(--text-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.weak-count {
  color: var(--fg-2);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
}

.empty {
  padding: 24px 0;
  color: var(--fg-3);
  font-size: var(--text-sm);
}

.packs {
  margin-top: var(--space-5);
}

.packs-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 20px 20px 14px;
}

.more {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--fg-3);
  font-size: var(--text-xs);
}

.more:hover {
  color: var(--fg);
}

.table-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 110px 110px 92px;
  gap: 16px;
  padding: 0 20px 8px;
  color: var(--fg-3);
  font-size: 11px;
}

.table-head span:not(:first-child) {
  text-align: right;
}

.pack-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 110px 110px 92px;
  align-items: center;
  gap: 16px;
  padding: 14px 20px;
  border-top: 0.5px solid var(--line-hair);
  transition: background-color 0.15s var(--ease-out-cubic);
}

.pack-row:hover {
  background: var(--bg-subtle);
}

.pack-main {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.pack-title {
  font-size: 14px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pack-meta {
  color: var(--fg-3);
  font-size: var(--text-xs);
}

.cell {
  font-size: var(--text-xs);
  text-align: right;
}

@media (max-width: 900px) {
  .metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .split {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 720px) {
  .table-head {
    display: none;
  }

  .pack-row {
    grid-template-columns: minmax(0, 1fr) 72px;
  }

  .pack-row .cell:nth-child(3),
  .pack-row .cell:nth-child(4) {
    display: none;
  }
}
</style>
