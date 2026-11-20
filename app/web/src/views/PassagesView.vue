<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '../api'
import { t } from '../i18n'
import type { PackSummary } from '../types'
import { fmtShort, pct } from '../utils/format'
import Card from '../components/Card.vue'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'

const loading = ref(true)
const failed = ref(false)
const packs = ref<PackSummary[]>([])

const ordered = computed(() =>
  [...packs.value]
    .filter((pack) => pack.kind === 'reading')
    .sort((a, b) => {
      const recent = (b.progress?.lastAt ?? 0) - (a.progress?.lastAt ?? 0)
      if (recent !== 0) return recent
      return a.meta.title.localeCompare(b.meta.title)
    }),
)

function accuracy(pack: PackSummary): string {
  const reading = pack.progress?.reading
  if (!reading || reading.answered === 0) return '—'
  return pct(reading.correct / reading.answered)
}

async function load(): Promise<void> {
  loading.value = true
  failed.value = false
  try {
    const data = await api.packs()
    packs.value = data.items
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
    <PageHeader :eyebrow="t('read.count', { n: ordered.length })" :title="t('nav.read')" />

    <div v-if="loading" class="state">{{ t('common.loading') }}</div>
    <div v-else-if="failed" class="state">
      {{ t('toast.loadFailed') }}
      <button class="retry" @click="load">{{ t('common.retry') }}</button>
    </div>

    <Card v-else padding="none">
      <RouterLink
        v-for="(pack, index) in ordered"
        :key="pack.id"
        :to="`/read/${pack.id}`"
        class="row"
      >
        <span class="index serif num">{{ String(index + 1).padStart(2, '0') }}</span>
        <div class="main">
          <div class="title">{{ pack.meta.title }}</div>
          <div class="meta">
            {{ pack.meta.book }} · {{ pack.meta.test }} · {{ pack.meta.passage }}
            <span class="sep">·</span>
            {{ pack.counts.sentences }} {{ t('common.sentences') }}
            <span class="sep">·</span>
            {{ pack.counts.questions }} {{ t('common.questions') }}
          </div>
        </div>
        <div class="stat">
          <span class="value num">{{ accuracy(pack) }}</span>
          <span class="label">{{ t('stats.readingAccuracy') }}</span>
        </div>
        <div class="last">
          {{ pack.progress?.lastAt ? fmtShort(pack.progress.lastAt) : t('stats.never') }}
        </div>
        <Icon name="chevronRight" :size="16" class="arrow" />
      </RouterLink>

      <div v-if="ordered.length === 0" class="empty">{{ t('read.empty') }}</div>
    </Card>
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

.row {
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr) 112px 96px 18px;
  align-items: center;
  gap: 16px;
  padding: 18px 20px;
  transition: background-color 0.15s var(--ease-out-cubic);
}

.row + .row {
  border-top: 0.5px solid var(--line-hair);
}

.row:hover {
  background: var(--bg-subtle);
}

.index {
  color: var(--fg-3);
  font-family: var(--font-serif);
  font-size: 15px;
  font-variant-numeric: tabular-nums;
}

.title {
  font-family: var(--font-serif);
  font-size: 19px;
  font-weight: 500;
  line-height: 1.25;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.meta {
  margin-top: 4px;
  color: var(--fg-3);
  font-size: var(--text-xs);
}

.sep {
  margin: 0 2px;
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  text-align: right;
}

.value {
  font-family: var(--font-serif);
  font-size: 17px;
  font-weight: 500;
}

.label {
  color: var(--fg-3);
  font-size: 11px;
}

.last {
  color: var(--fg-3);
  font-size: var(--text-xs);
  text-align: right;
}

.arrow {
  color: var(--fg-3);
}

.empty {
  padding: 48px 20px;
  color: var(--fg-3);
  font-size: var(--text-sm);
  text-align: center;
}

@media (max-width: 760px) {
  .row {
    grid-template-columns: 30px minmax(0, 1fr) 18px;
    gap: 10px;
    padding: 14px 16px;
  }

  .stat,
  .last {
    display: none;
  }

  .title {
    font-size: 17px;
  }
}
</style>
