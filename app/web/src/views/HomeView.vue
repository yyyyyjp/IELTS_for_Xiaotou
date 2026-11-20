<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '../api'
import { t } from '../i18n'
import type { DailyItem, Overview, PackSummary, VocabStats } from '../types'
import { fmtDayLong, fmtMonthDay, fmtShort, pct } from '../utils/format'
import AppButton from '../components/AppButton.vue'
import Card from '../components/Card.vue'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'

const loading = ref(true)
const failed = ref(false)
const overview = ref<Overview | null>(null)
const packs = ref<PackSummary[]>([])
const daily = ref<DailyItem[]>([])
const vocab = ref<VocabStats | null>(null)

const due = computed(() => overview.value?.totals.dueNow ?? 0)
const newWords = computed(() => vocab.value?.byState.new ?? 0)
const readings = computed(() =>
  [...packs.value]
    .filter((pack) => pack.kind === 'reading')
    .sort((a, b) => (b.progress?.lastAt ?? 0) - (a.progress?.lastAt ?? 0))
    .slice(0, 4),
)
const maxActivity = computed(() =>
  Math.max(1, ...daily.value.map((day) => day.attempts)),
)
const hasActivity = computed(() => daily.value.some((day) => day.attempts > 0))

const metrics = computed(() => [
  {
    key: 'streak',
    icon: 'flame' as const,
    label: t('home.streak'),
    value: overview.value?.streak.current ?? 0,
    unit: t('home.streakUnit'),
  },
  {
    key: 'answered',
    icon: 'list' as const,
    label: t('home.todayAnswered'),
    value: overview.value?.today.attempts ?? 0,
    unit: '',
  },
  {
    key: 'accuracy',
    icon: 'target' as const,
    label: t('home.todayAccuracy'),
    value: pct(overview.value?.today.accuracy ?? 0),
    unit: '',
  },
  {
    key: 'focus',
    icon: 'clock' as const,
    label: t('home.focus'),
    value: overview.value?.today.minutes ?? 0,
    unit: t('common.minutes'),
  },
])

function packAccuracy(pack: PackSummary): string {
  const reading = pack.progress?.reading
  if (!reading || reading.answered === 0) return '—'
  return pct(reading.correct / reading.answered)
}

async function load(): Promise<void> {
  loading.value = true
  failed.value = false
  try {
    const [o, p, d, v] = await Promise.all([
      api.statsOverview(),
      api.packs(),
      api.statsDaily(30),
      api.vocabStats(),
    ])
    overview.value = o
    packs.value = p.items
    daily.value = d.items
    vocab.value = v
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <PageHeader :eyebrow="fmtDayLong()" :title="t('home.title')" />

    <div v-if="loading" class="state">{{ t('common.loading') }}</div>
    <div v-else-if="failed" class="state">
      {{ t('toast.loadFailed') }}
      <button class="retry" @click="load">{{ t('common.retry') }}</button>
    </div>

    <template v-else>
      <div class="hero">
        <Card variant="subtle" padding="lg" class="due-card">
          <div class="due-top">
            <span class="eyebrow">{{ t('home.due') }}</span>
            <Icon name="bookmark" :size="16" class="due-icon" />
          </div>
          <div class="due-number serif num">{{ due }}</div>
          <div class="due-sub">{{ t('home.new', { n: newWords }) }}</div>
          <div class="due-action">
            <AppButton v-if="due > 0" variant="primary" @click="$router.push('/vocab')">
              {{ t('home.startReview') }}
            </AppButton>
            <span v-else class="due-empty">{{ t('home.noDue') }}</span>
          </div>
        </Card>

        <div class="metrics">
          <Card v-for="metric in metrics" :key="metric.key" padding="sm" class="metric">
            <div class="metric-label">
              <Icon :name="metric.icon" :size="13" />
              {{ metric.label }}
            </div>
            <div class="metric-value">
              <span class="serif num">{{ metric.value }}</span>
              <span v-if="metric.unit" class="unit">{{ metric.unit }}</span>
            </div>
          </Card>
        </div>
      </div>

      <section class="section">
        <div class="section-head">
          <h2>{{ t('home.continue') }}</h2>
          <RouterLink to="/read" class="more">
            {{ t('home.allPacks') }}
            <Icon name="arrowUpRight" :size="13" />
          </RouterLink>
        </div>

        <Card padding="none">
          <RouterLink
            v-for="pack in readings"
            :key="pack.id"
            :to="`/read/${pack.id}`"
            class="pack-row"
          >
            <div class="pack-main">
              <div class="pack-title">{{ pack.meta.title }}</div>
              <div class="pack-meta">
                {{ pack.meta.book }} · {{ pack.meta.test }} · {{ pack.meta.passage }}
              </div>
            </div>
            <div class="pack-stat">
              <span class="pack-value num">{{ packAccuracy(pack) }}</span>
              <span class="pack-label">{{ t('stats.readingAccuracy') }}</span>
            </div>
            <div class="pack-last">
              {{ pack.progress?.lastAt ? fmtShort(pack.progress.lastAt) : t('stats.never') }}
            </div>
            <Icon name="chevronRight" :size="16" class="pack-arrow" />
          </RouterLink>
          <div v-if="readings.length === 0" class="empty">{{ t('common.empty') }}</div>
        </Card>
      </section>

      <section class="section">
        <div class="section-head">
          <h2>{{ t('home.activity') }}</h2>
          <RouterLink to="/stats" class="more">
            {{ t('nav.stats') }}
            <Icon name="arrowUpRight" :size="13" />
          </RouterLink>
        </div>
        <Card padding="md">
          <div v-if="!hasActivity" class="chart-empty">{{ t('home.noAttempts') }}</div>
          <template v-else>
            <div class="activity">
              <div
                v-for="day in daily"
                :key="day.date"
                class="bar"
                :style="{
                  height: `${day.attempts ? Math.max(4, (day.attempts / maxActivity) * 64) : 2}px`,
                }"
                :class="{ zero: day.attempts === 0 }"
                :title="`${fmtMonthDay(day.date)} · ${day.attempts}`"
              />
            </div>
            <div class="axis">
              <span>{{ daily.length ? fmtMonthDay(daily[0].date) : '' }}</span>
              <span>{{ daily.length ? fmtMonthDay(daily[daily.length - 1].date) : '' }}</span>
            </div>
          </template>
        </Card>
      </section>
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

.hero {
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr);
  gap: var(--space-5);
}

.due-card {
  display: flex;
  flex-direction: column;
  min-height: 248px;
}

.due-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.due-icon {
  color: var(--accent);
}

.due-number {
  margin-top: 18px;
  font-family: var(--font-serif);
  font-size: clamp(56px, 6vw, 80px);
  font-weight: 500;
  line-height: 0.95;
}

.due-sub {
  margin-top: 8px;
  color: var(--fg-2);
  font-size: var(--text-sm);
}

.due-action {
  margin-top: auto;
  padding-top: 24px;
}

.due-empty {
  color: var(--fg-3);
  font-size: var(--text-sm);
}

.metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.metric {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-height: 118px;
}

.metric-label {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--fg-3);
  font-size: var(--text-xs);
}

.metric-value {
  display: flex;
  align-items: baseline;
  gap: 5px;
  margin-top: 16px;
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

.section {
  margin-top: var(--space-7);
}

.section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.section-head h2 {
  font-family: var(--font-serif);
  font-size: 20px;
  font-weight: 500;
}

.more {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--fg-3);
  font-size: var(--text-xs);
  transition: color 0.2s var(--ease-out-cubic);
}

.more:hover {
  color: var(--fg);
}

.pack-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 104px 88px 18px;
  align-items: center;
  gap: 16px;
  padding: 16px 20px;
  transition: background-color 0.15s var(--ease-out-cubic);
}

.pack-row + .pack-row {
  border-top: 0.5px solid var(--line-hair);
}

.pack-row:hover {
  background: var(--bg-subtle);
}

.pack-title {
  font-size: 15px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pack-meta {
  margin-top: 3px;
  color: var(--fg-3);
  font-size: var(--text-xs);
}

.pack-stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  text-align: right;
}

.pack-value {
  font-family: var(--font-serif);
  font-size: 17px;
  font-weight: 500;
}

.pack-label {
  color: var(--fg-3);
  font-size: 11px;
}

.pack-last {
  color: var(--fg-3);
  font-size: var(--text-xs);
  text-align: right;
}

.pack-arrow {
  color: var(--fg-3);
}

.empty {
  padding: 32px 20px;
  color: var(--fg-3);
  font-size: var(--text-sm);
  text-align: center;
}

.chart-empty {
  display: grid;
  place-items: center;
  height: 96px;
  color: var(--fg-3);
  font-size: var(--text-sm);
}

.activity {
  display: flex;
  align-items: flex-end;
  gap: 3px;
  height: 64px;
}

.bar {
  flex: 1;
  min-width: 2px;
  border-radius: 2px;
  background: var(--accent);
  opacity: 0.9;
}

.bar.zero {
  background: var(--line-hair);
  opacity: 1;
}

.axis {
  display: flex;
  justify-content: space-between;
  margin-top: 10px;
  color: var(--fg-3);
  font-size: 11px;
}

@media (max-width: 1080px) {
  .hero {
    grid-template-columns: minmax(0, 1fr);
  }

  .due-card {
    min-height: 0;
  }
}

@media (max-width: 720px) {
  .pack-row {
    grid-template-columns: minmax(0, 1fr) 18px;
  }

  .pack-stat,
  .pack-last {
    display: none;
  }
}
</style>
