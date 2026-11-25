<script setup lang="ts">
import { computed } from 'vue'
import { t } from '../i18n'
import type { GuideDoc } from '../types'
import { rich } from '../utils/rich'

const props = defineProps<{
  guide: GuideDoc | null
  activePara?: number | null
}>()

const emit = defineEmits<{
  (event: 'jump-para', no: number): void
}>()

const band = computed(() => props.guide?.band ?? [])
const legend = computed(() => props.guide?.legend ?? [])
const rows = computed(() => props.guide?.rows ?? [])
const terms = computed(() => props.guide?.terms ?? [])
const why = computed(() => props.guide?.why ?? [])
const echo = computed(() => props.guide?.echo ?? {})
const argument = computed(() => props.guide?.argument ?? {})

const structureTitle = computed(
  () => props.guide?.structureTitle || t('reader.guide.structure'),
)
const negative = computed(() => argument.value.negative ?? [])
const positive = computed(() => argument.value.positive ?? [])
</script>

<template>
  <div class="guide">
    <template v-if="guide">
      <div v-if="guide.kicker" class="kicker">{{ guide.kicker }}</div>
      <h2 v-if="guide.title">{{ guide.title }}</h2>
      <p v-if="guide.lede" class="lede" v-html="rich(guide.lede)"></p>

      <div v-if="guide.thesis" class="thesis">
        <em>{{ t('reader.guide.thesis') }}</em>
        <p v-html="rich(guide.thesis)"></p>
      </div>

      <template v-if="band.length">
        <div class="sec-h">
          <em>STRUCTURE</em>
          <h3>{{ structureTitle }}</h3>
          <span class="cnt">{{ band.length }}</span>
        </div>
        <div class="band">
          <button
            v-for="cell in band"
            :key="cell.n"
            type="button"
            class="cell"
            :class="[cell.s, { active: activePara === cell.n }]"
            :aria-pressed="activePara === cell.n"
            @click="emit('jump-para', cell.n)"
          >
            <b>{{ cell.n }}</b>
            <span>{{ cell.f }}</span>
          </button>
        </div>
        <div v-if="legend.length" class="legend">
          <span v-for="item in legend" :key="item.text">
            <i :class="item.s"></i>{{ item.text }}
          </span>
        </div>
      </template>

      <template v-if="negative.length || positive.length">
        <div class="sec-h">
          <em>ARGUMENT</em>
          <h3>{{ t('reader.guide.argument') }}</h3>
        </div>
        <div class="duel">
          <div v-if="negative.length" class="col neg">
            <h4>{{ argument.negativeTitle || t('reader.guide.argument') }}</h4>
            <ol>
              <li v-for="(item, index) in negative" :key="index">
                <b>{{ item.t }}</b>
                <span v-html="rich(item.p)"></span>
              </li>
            </ol>
          </div>
          <div v-if="positive.length" class="col pos">
            <h4>{{ argument.positiveTitle || t('reader.guide.argument') }}</h4>
            <ol>
              <li v-for="(item, index) in positive" :key="index">
                <b>{{ item.t }}</b>
                <span v-html="rich(item.p)"></span>
              </li>
            </ol>
          </div>
        </div>
        <div v-if="argument.punch" class="punch" v-html="rich(argument.punch)"></div>
      </template>

      <template v-if="rows.length">
        <div class="sec-h">
          <em>PARAGRAPH BY PARAGRAPH</em>
          <h3>{{ t('reader.guide.paragraphs') }}</h3>
          <span class="cnt">{{ rows.length }}</span>
        </div>
        <div class="table">
          <button
            v-for="row in rows"
            :key="row.n"
            type="button"
            class="row"
            :class="{ active: activePara === row.n }"
            :aria-pressed="activePara === row.n"
            @click="emit('jump-para', row.n)"
          >
            <div class="n">{{ row.n }}</div>
            <div class="d" v-html="rich(row.d)"></div>
            <div class="w" :class="row.s">{{ row.w }}</div>
          </button>
        </div>
      </template>

      <template v-if="terms.length">
        <div class="sec-h">
          <em>TERMS</em>
          <h3>{{ t('reader.guide.terms') }}</h3>
          <span class="cnt">{{ terms.length }}</span>
        </div>
        <div class="terms">
          <div v-for="term in terms" :key="term.k" class="term">
            <div class="k">{{ term.k }}</div>
            <div v-if="term.en" class="en">{{ term.en }}</div>
            <p v-html="rich(term.d)"></p>
          </div>
        </div>
      </template>

      <template v-if="echo.neg || echo.pos">
        <div class="sec-h">
          <em>ECHO</em>
          <h3>{{ t('reader.guide.echo') }}</h3>
        </div>
        <div class="echo">
          <blockquote v-if="echo.neg" class="neg">
            <span>{{ t('reader.guide.negative') }}</span>
            <p v-html="rich(echo.neg)"></p>
          </blockquote>
          <blockquote v-if="echo.pos" class="pos">
            <span>{{ t('reader.guide.positive') }}</span>
            <p v-html="rich(echo.pos)"></p>
          </blockquote>
        </div>
        <p v-if="echo.note" class="echo-note" v-html="rich(echo.note)"></p>
      </template>

      <template v-if="why.length">
        <div class="sec-h">
          <em>WHY</em>
          <h3>{{ t('reader.guide.why') }}</h3>
          <span class="cnt">{{ why.length }}</span>
        </div>
        <div class="why">
          <div v-for="(item, index) in why" :key="index" class="why-item">
            <h4>{{ item.t }}</h4>
            <p v-html="rich(item.p)"></p>
          </div>
        </div>
      </template>

      <div v-if="guide.side" class="side" v-html="rich(guide.side)"></div>
      <div v-if="guide.end" class="end" v-html="rich(guide.end)"></div>
    </template>

    <p v-else class="empty">{{ t('reader.guide.empty') }}</p>
  </div>
</template>

<style scoped>
.guide {
  padding: 2px 2px 40px;
  font-family: var(--font-serif);
  color: var(--fg);
}

.kicker {
  margin-bottom: 8px;
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: 11px;
  letter-spacing: 0.04em;
}

h2 {
  margin: 0 0 10px;
  font-family: var(--font-serif);
  font-size: 24px;
  font-weight: 500;
  line-height: 1.25;
  letter-spacing: -0.01em;
}

.lede {
  margin: 0 0 20px;
  color: var(--fg-2);
  font-size: 15px;
  line-height: 1.9;
}

.lede :deep(b),
.lede :deep(strong) {
  color: var(--fg);
  font-weight: 600;
}

.lede :deep(em) {
  color: var(--fg);
  font-style: normal;
  font-weight: 600;
}

.thesis {
  margin-bottom: 34px;
  padding: 14px 18px;
  border-left: 2px solid var(--accent);
  border-radius: 0 8px 8px 0;
  background: var(--bg-subtle);
}

.thesis em {
  display: block;
  margin-bottom: 4px;
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: 10px;
  font-style: normal;
  font-weight: 600;
  letter-spacing: 0.1em;
}

.thesis p {
  margin: 0;
  color: var(--fg);
  font-size: 15.5px;
  line-height: 1.85;
}

.sec-h {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin: 38px 0 14px;
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
  font-family: var(--font-serif);
  font-size: 18px;
  font-weight: 500;
  line-height: 1.35;
}

.sec-h .cnt {
  margin-left: auto;
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: 10px;
  font-variant-numeric: tabular-nums;
}

.band {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(76px, 1fr));
  gap: 5px;
}

.cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 8px 6px;
  border: 0.5px solid transparent;
  border-radius: 6px;
  text-align: center;
  cursor: pointer;
  transition:
    transform 0.14s var(--ease-out-cubic),
    border-color 0.14s var(--ease-out-cubic),
    box-shadow 0.14s var(--ease-out-cubic);
}

.cell:hover {
  transform: translateY(-1px);
  border-color: var(--line-strong);
}

.cell.active {
  border-color: var(--accent);
  box-shadow: 0 0 0 1.5px color-mix(in srgb, var(--accent) 45%, transparent);
}

.cell b {
  font-family: var(--font-sans);
  font-size: 9.5px;
  font-weight: 600;
  opacity: 0.65;
}

.cell span {
  font-family: var(--font-serif);
  font-size: 12.5px;
  line-height: 1.25;
}

.cell.t {
  background: var(--ok-bg);
  border-color: var(--ok-line);
  color: var(--fg);
}

.cell.a {
  background: var(--band-a-bg);
  border-color: var(--band-a-line);
  color: var(--fg);
}

.cell.g {
  background: var(--bg-sunken);
  border-color: var(--line-hair);
  color: var(--fg-3);
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 18px;
  margin-top: 10px;
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: 10.5px;
}

.legend span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.legend i {
  width: 9px;
  height: 9px;
  border-radius: 2px;
}

.legend i.t {
  background: var(--ok-bg);
  border: 1px solid var(--ok-line);
}

.legend i.a {
  background: var(--band-a-bg);
  border: 1px solid var(--band-a-line);
}

.legend i.g {
  background: var(--bg-sunken);
  border: 1px solid var(--line-hair);
}

.duel {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 20px 24px;
}

.col h4 {
  margin: 0 0 10px;
  padding-bottom: 6px;
  border-bottom: 0.5px solid var(--line-hair);
  color: var(--fg-2);
  font-family: var(--font-sans);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.col ol {
  margin: 0;
  padding: 0;
  list-style: none;
}

.col li {
  position: relative;
  padding: 0 0 12px 14px;
  color: var(--fg-2);
  font-size: 13.5px;
  line-height: 1.8;
}

.col li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--line-strong);
}

.col.neg li::before {
  background: var(--bad-line);
}

.col.pos li::before {
  background: var(--ok-line);
}

.col li b {
  display: block;
  margin-bottom: 1px;
  color: var(--fg);
  font-family: var(--font-serif);
  font-size: 14px;
  font-weight: 600;
}

.col li :deep(em) {
  color: var(--fg);
  font-style: normal;
  font-weight: 600;
}

.punch {
  margin: 18px 0 0;
  padding: 14px 18px;
  border: 0.5px solid var(--line-strong);
  border-radius: 8px;
  background: var(--bg-raise);
  font-size: 15.5px;
  line-height: 1.85;
}

.punch :deep(b),
.punch :deep(strong) {
  color: var(--fg);
  font-weight: 600;
}

.table {
  border-top: 0.5px solid var(--line-hair);
}

.row {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr) 54px;
  gap: 12px;
  width: 100%;
  padding: 12px 6px;
  border-bottom: 0.5px solid var(--line-hair);
  border-radius: 6px;
  text-align: left;
  cursor: pointer;
  transition: background-color 0.14s var(--ease-out-cubic);
}

.row:hover {
  background: var(--bg-subtle);
}

.row.active {
  background: color-mix(in srgb, var(--hl-answer) 45%, var(--bg-page));
  box-shadow: inset 2px 0 0 var(--hl-line);
}

.row .n {
  padding-top: 2px;
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
}

.row .d {
  color: var(--fg-2);
  font-size: 13.5px;
  line-height: 1.85;
}

.row .d :deep(em) {
  color: var(--fg);
  font-style: normal;
  font-weight: 600;
}

.row .w {
  padding-top: 1px;
  font-family: var(--font-sans);
  font-size: 10px;
  text-align: right;
  white-space: nowrap;
}

.row .w.t {
  color: var(--fg);
}

.row .w.a {
  color: var(--fg);
}

.row .w.g {
  color: var(--fg-3);
}

.terms {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(175px, 1fr));
  gap: 12px;
}

.term {
  padding: 12px 14px;
  border: 0.5px solid var(--line-hair);
  border-radius: 8px;
}

.term .k {
  font-family: var(--font-serif);
  font-size: 16px;
  font-weight: 600;
}

.term .en {
  margin: 2px 0 6px;
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: 10px;
  letter-spacing: 0.02em;
}

.term p {
  margin: 0;
  color: var(--fg-2);
  font-size: 12.5px;
  line-height: 1.75;
}

.term p :deep(em) {
  color: var(--fg);
  font-style: normal;
  font-weight: 600;
}

.echo {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 18px 20px;
}

.echo blockquote {
  margin: 0;
  padding: 2px 0 2px 14px;
  border-left: 2px solid var(--line-strong);
}

.echo blockquote.pos {
  border-left-color: var(--accent);
}

.echo blockquote span {
  display: block;
  margin-bottom: 4px;
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: 9.5px;
  letter-spacing: 0.1em;
}

.echo blockquote p {
  margin: 0;
  color: var(--fg-2);
  font-size: 13.5px;
  line-height: 1.85;
}

.echo blockquote p :deep(b) {
  color: var(--fg);
}

.echo-note {
  margin: 14px 0 0;
  color: var(--fg-3);
  font-size: 13px;
  line-height: 1.85;
}

.echo-note :deep(b) {
  color: var(--fg);
}

.why-item {
  padding: 11px 0;
  border-bottom: 0.5px dashed var(--line-hair);
}

.why-item h4 {
  margin: 0 0 3px;
  color: var(--fg);
  font-family: var(--font-serif);
  font-size: 14.5px;
  font-weight: 600;
}

.why-item p {
  margin: 0;
  color: var(--fg-2);
  font-size: 13.5px;
  line-height: 1.85;
}

.why-item p :deep(em) {
  color: var(--fg);
  font-style: normal;
  font-weight: 600;
}

.side {
  margin-top: 34px;
  padding: 16px 18px;
  border: 0.5px solid var(--line-strong);
  border-radius: 8px;
  background: var(--bg-subtle);
  color: var(--fg-2);
  font-size: 13.5px;
  line-height: 1.9;
}

.side :deep(b) {
  color: var(--fg);
}

.end {
  margin-top: 22px;
  color: var(--fg-2);
  font-size: 14px;
  line-height: 1.9;
}

.end :deep(em) {
  color: var(--fg);
  font-style: normal;
  font-weight: 600;
}

.empty {
  padding: 48px 0;
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  text-align: center;
}

@media (max-width: 900px) {
  .duel,
  .echo {
    grid-template-columns: 1fr;
    gap: 18px;
  }

  .terms {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .guide {
    padding-bottom: 56px;
  }

  .band {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }

  .row {
    grid-template-columns: 20px minmax(0, 1fr) 42px;
    gap: 8px;
  }
}

</style>
