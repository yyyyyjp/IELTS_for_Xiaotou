<script setup lang="ts">
import { computed } from 'vue'
import { t } from '../i18n'
import type { Attempt, ReviewDoc } from '../types'
import { fmtDuration } from '../utils/format'
import { rich } from '../utils/rich'

const props = defineProps<{
  review: ReviewDoc | null
  attempt?: Attempt | null
}>()

const stats = computed<[string, string, number][]>(() => {
  if (props.review?.stats?.length) return props.review.stats
  const a = props.attempt
  if (!a) return []
  return [
    [`${a.score} / ${a.total}`, t('reader.score'), 1],
    [fmtDuration(a.durationSec), t('reader.duration'), 0],
    [String(a.wrong), t('common.wrong'), 1],
  ]
})

const bars = computed<[string, number, string][]>(() => {
  if (props.review?.bars?.length) return props.review.bars
  const a = props.attempt
  if (!a?.byType?.length) return []
  return a.byType
    .filter((row) => row.total)
    .map((row) => [
      row.label,
      Math.round((row.accuracy ?? 0) * 100),
      `${row.correct ?? 0}/${row.total ?? 0}`,
    ])
})

const diagnoses = computed(() => props.review?.diagnoses ?? [])
const actions = computed(() => props.review?.actions ?? [])
</script>

<template>
  <div class="rev">
    <template v-if="review">
      <h2 v-if="review.title" class="rev-title" v-html="rich(review.title)"></h2>
      <p v-if="review.lede" class="rev-lede" v-html="rich(review.lede)"></p>

      <div v-if="stats.length" class="stats">
        <div v-for="([value, label, tone], index) in stats" :key="index" class="stat" :class="{ bad: tone }">
          <b>{{ value }}</b>
          <span>{{ label }}</span>
        </div>
      </div>

      <div v-if="bars.length" class="bars">
        <div v-for="([label, percent, value], index) in bars" :key="index" class="bar">
          <span class="bl">{{ label }}</span>
          <span class="track"><i :style="{ width: `${Math.max(2, Math.min(100, percent))}%` }"></i></span>
          <span class="v">{{ value }}</span>
        </div>
      </div>

      <template v-if="diagnoses.length">
        <div class="sec-h">
          <em>DIAGNOSIS</em>
          <h3>{{ t('reader.review.diagnosis') }}</h3>
          <span class="cnt">{{ diagnoses.length }}</span>
        </div>
        <div class="grid3">
          <div v-for="item in diagnoses" :key="item.n" class="dg">
            <div class="n">{{ item.n }}</div>
            <div class="t">{{ item.t }}</div>
            <p v-html="rich(item.p)"></p>
          </div>
        </div>
      </template>

      <template v-if="actions.length">
        <div class="sec-h">
          <em>NEXT</em>
          <h3>{{ t('reader.review.actions') }}</h3>
          <span class="cnt">{{ actions.length }}</span>
        </div>
        <ol class="acts">
          <li v-for="(item, index) in actions" :key="index" v-html="rich(item)"></li>
        </ol>
      </template>

      <div v-if="review.end" class="rev-end" v-html="rich(review.end)"></div>
    </template>

    <p v-else class="empty">{{ t('reader.review.empty') }}</p>
  </div>
</template>

<style scoped>
.rev {
  padding: 2px 2px 24px;
  font-family: var(--font-serif);
}

.rev-title {
  margin: 2px 0 10px;
  color: var(--fg);
  font-family: var(--font-serif);
  font-size: 24px;
  font-weight: 500;
  line-height: 1.25;
  letter-spacing: -0.01em;
}

.rev-lede {
  margin: 0 0 18px;
  color: var(--fg-2);
  font-family: var(--font-serif);
  font-size: 15.5px;
  line-height: 1.9;
}

.rev-lede :deep(b),
.rev-lede :deep(strong),
.rev-end :deep(b),
.rev-end :deep(strong) {
  color: var(--fg);
  font-weight: 600;
}

.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(88px, 1fr));
  gap: 1px;
  margin-bottom: 18px;
  border: 0.5px solid var(--line-hair);
  border-radius: 8px;
  overflow: hidden;
  background: var(--line-hair);
}

.stat {
  padding: 10px 10px 9px;
  background: var(--bg-page);
}

.stat b {
  display: block;
  color: var(--fg);
  font-family: var(--font-serif);
  font-size: 20px;
  font-weight: 500;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}

.stat.bad b {
  color: var(--fg);
}

.stat span {
  display: block;
  margin-top: 2px;
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: 10.5px;
  letter-spacing: 0.04em;
}

.bars {
  margin-bottom: 22px;
}

.bar {
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr) 42px;
  align-items: center;
  gap: 10px;
  padding: 4px 0;
}

.bl {
  color: var(--fg-2);
  font-family: var(--font-sans);
  font-size: 12px;
  white-space: nowrap;
}

.track {
  height: 3px;
  border-radius: 2px;
  background: var(--bg-sunken);
  overflow: hidden;
}

.track i {
  display: block;
  height: 100%;
  border-radius: 2px;
  background: var(--accent);
}

.v {
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: 11.5px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.sec-h {
  display: flex;
  align-items: baseline;
  gap: 9px;
  margin: 24px 0 12px;
  padding-bottom: 8px;
  border-bottom: 0.5px solid var(--line-hair);
}

.sec-h em {
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: 9.5px;
  font-style: normal;
  font-weight: 600;
  letter-spacing: 0.14em;
}

.sec-h h3 {
  margin: 0;
  color: var(--fg);
  font-family: var(--font-serif);
  font-size: 17px;
  font-weight: 500;
}

.sec-h .cnt {
  margin-left: auto;
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: 10px;
}

.grid3 {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 12px;
}

.dg {
  padding: 12px 13px;
  border: 0.5px solid var(--line-hair);
  border-radius: 8px;
}

.dg .n {
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.12em;
}

.dg .t {
  margin: 3px 0 6px;
  color: var(--fg);
  font-family: var(--font-serif);
  font-size: 17px;
  font-weight: 600;
}

.dg p {
  margin: 0;
  color: var(--fg-2);
  font-family: var(--font-serif);
  font-size: 14px;
  line-height: 1.75;
}

.dg p :deep(em) {
  color: var(--fg);
  font-style: normal;
  font-weight: 600;
}

.acts {
  margin: 0;
  padding: 0 0 0 18px;
  counter-reset: act;
  list-style: none;
}

.acts li {
  position: relative;
  padding: 0 0 11px 12px;
  color: var(--fg-2);
  font-family: var(--font-serif);
  font-size: 14.5px;
  line-height: 1.8;
}

.acts li::before {
  counter-increment: act;
  content: counter(act, decimal-leading-zero);
  position: absolute;
  left: -18px;
  top: 2px;
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.acts li :deep(b),
.acts li :deep(strong) {
  color: var(--fg);
  font-weight: 600;
}

.acts li :deep(em) {
  color: var(--fg);
  font-style: normal;
  font-weight: 600;
}

.rev-end {
  margin-top: 22px;
  padding: 14px 16px;
  border-left: 2px solid var(--accent);
  border-radius: 0 8px 8px 0;
  background: var(--bg-subtle);
  color: var(--fg-2);
  font-family: var(--font-serif);
  font-size: 14.5px;
  line-height: 1.9;
}

.rev-end :deep(em) {
  color: var(--fg);
  font-style: normal;
  font-weight: 600;
}

.empty {
  padding: 40px 0;
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  text-align: center;
}

@media (max-width: 640px) {
  .stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .rev-title {
    font-size: 21px;
  }

  .bar {
    grid-template-columns: 78px minmax(0, 1fr) 38px;
  }
}
</style>
