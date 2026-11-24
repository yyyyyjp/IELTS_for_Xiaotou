<script setup lang="ts">
import { computed } from 'vue'
import { t } from '../i18n'
import type {
  Cite,
  Paragraph,
  QuestionGroup,
  ReadingResultItem,
  ReviewDoc,
  ReviewItem,
  ReviewRow,
  ReviewSection,
} from '../types'
import { citeParagraphs } from '../utils/cites'
import { rich } from '../utils/rich'

const props = defineProps<{
  groups: QuestionGroup[]
  review: ReviewDoc | null
  results: ReadingResultItem[]
  paragraphs: Paragraph[]
  openNo: number | null
  openGap: number | null
}>()

const emit = defineEmits<{
  (event: 'open', no: number): void
  (event: 'gap', no: number): void
  (event: 'cite', no: number): void
}>()

const resultMap = computed<Record<number, ReadingResultItem>>(() => {
  const map: Record<number, ReadingResultItem> = {}
  for (const item of props.results) map[item.no] = item
  return map
})

const analysisMap = computed<Record<number, ReviewItem>>(() => {
  const map: Record<number, ReviewItem> = {}
  for (const section of props.review?.sections ?? []) {
    for (const item of section.items ?? []) map[item.no] = item
  }
  return map
})

const typeLabel: Record<string, string> = {
  mcq: 'reader.sect.mcq',
  summary: 'reader.sect.summary',
  ynng: 'reader.sect.ynng',
  tfng: 'reader.sect.tfng',
  matching: 'reader.sect.matching',
  gap: 'reader.sect.gap',
}

function sectionFor(group: QuestionGroup): ReviewSection | undefined {
  const list = props.review?.sections ?? []
  const from = group.from ?? 0
  const to = group.to ?? 0
  return (
    list.find((s) => s.from != null && s.to != null && s.from <= from && s.to >= to) ??
    list.find((s) => s.kind === group.type)
  )
}

function title(group: QuestionGroup): string {
  const section = sectionFor(group)
  if (section?.title) return section.title
  const label = t(typeLabel[group.type] ?? 'reader.questions')
  const nos = group.items.map((item) => item.no)
  if (!nos.length) return label
  const a = Math.min(...nos)
  const b = Math.max(...nos)
  return a === b ? `${label} ${a}` : `${label} ${a}–${b}`
}

function isOk(no: number): boolean {
  const item = resultMap.value[no]
  return item ? item.correct : false
}

function correctText(no: number): string {
  const item = resultMap.value[no]
  if (item) return item.answer.join(' / ')
  const q = props.groups.flatMap((g) => g.items).find((x) => x.no === no)
  const a = q?.answer
  return Array.isArray(a) ? a.join(' / ') : String(a ?? '')
}

function mineText(no: number): string {
  const q = props.groups.flatMap((g) => g.items).find((x) => x.no === no)
  return (q?.mine ?? '').trim() || t('reader.unanswered')
}

function analysisFor(no: number): ReviewItem | undefined {
  return analysisMap.value[no]
}

function expandable(no: number): boolean {
  const a = analysisFor(no)
  return Boolean(a?.diag || a?.chain)
}

function isOpen(no: number): boolean {
  return props.openNo === no
}

function moreLabel(no: number): string {
  if (isOpen(no)) return t('reader.review.collapse')
  const label = analysisFor(no)?.label ?? ''
  if (label === 'why-right') return t('reader.review.whyRight')
  if (label === 'why-wrong') return t('reader.review.whyWrong')
  return label || t('reader.review.whyWrong')
}

function citeText(no: number): string {
  const paras = citeParagraphs(analysisFor(no)?.cites)
  if (!paras.length) return ''
  return `${t('reader.review.cite')} · ${paras.map((p) => `¶${p}`).join(' ')}`
}

function optionState(no: number, key: string): string {
  const answer = correctText(no)
  const mine = (props.groups.flatMap((g) => g.items).find((x) => x.no === no)?.mine ?? '').trim()
  if (answer.split(' / ').includes(key)) return 'correct'
  if (mine === key) return 'mine-wrong'
  return ''
}

function summaryParts(group: QuestionGroup): { text: string; no: number }[] {
  if (!group.text) return []
  return group.text
    .split(/(\{\{\d+\}\})/)
    .filter(Boolean)
    .map((text) => {
      const match = /^\{\{(\d+)\}\}$/.exec(text)
      return match ? { text, no: Number(match[1]) } : { text, no: 0 }
    })
}

function summaryHint(no: number): string {
  const ok = isOk(no)
  return `${t('reader.mine')} ${mineText(no)}${ok ? '' : ` → ${correctText(no)}`}`
}

function optionHit(group: QuestionGroup, key: string): boolean {
  return group.items.some((item) => correctText(item.no).split(' / ').includes(key))
}

function optionMiss(group: QuestionGroup, key: string): boolean {
  return group.items.some(
    (item) => (item.mine ?? '').trim() === key && !correctText(item.no).split(' / ').includes(key),
  )
}

function rowOk(no: number): boolean {
  return isOk(no)
}

function sectionNote(group: QuestionGroup): string {
  return sectionFor(group)?.note ?? ''
}

function sectionDiag(group: QuestionGroup): string {
  return sectionFor(group)?.diag ?? ''
}

function sectionRows(group: QuestionGroup) {
  return sectionFor(group)?.rows ?? []
}

function selectGap(no: number): void {
  emit('gap', no)
}

function gapCites(row: ReviewRow, section?: ReviewSection): Cite[] {
  if (row.cites?.length) return row.cites
  if (rowOk(row.no)) return []
  return section?.cites ?? []
}

function quoteFor(row: ReviewRow, section?: ReviewSection) {
  const out: { id: string; en: string; zh: string }[] = []
  for (const cite of gapCites(row, section)) {
    const para = props.paragraphs.find((item) => item.no === cite.p)
    if (!para) continue
    for (const index of cite.b ?? []) {
      const sentence = para.sentences[index]
      if (sentence) out.push({ id: sentence.id, en: sentence.en, zh: sentence.zh })
    }
  }
  return out
}

function toggle(no: number): void {
  emit('open', no)
}
</script>

<template>
  <div class="rail">
    <section v-for="group in groups" :key="group.id" class="sect">
      <div class="sect-t">
        <span>{{ title(group) }}</span>
      </div>

      <p v-if="group.instruction" class="sect-desc">{{ group.instruction }}</p>

      <template v-if="group.type === 'summary'">
        <div class="sum-box">
          <p v-if="group.title" class="sum-t">{{ group.title }}</p>
          <p class="sum-text">
            <template v-for="(part, index) in summaryParts(group)" :key="index">
              <span
                v-if="part.no"
                class="blank"
                :class="[isOk(part.no) ? 'ok' : 'no', { on: openGap === part.no }]"
                :title="summaryHint(part.no)"
                role="button"
                tabindex="0"
                :aria-pressed="openGap === part.no"
                @click.stop="selectGap(part.no)"
                @keydown.enter.prevent.stop="selectGap(part.no)"
                @keydown.space.prevent.stop="selectGap(part.no)"
              >
                <b>{{ part.no }}</b>
                <span>{{ mineText(part.no) }}</span>
                <template v-if="!isOk(part.no)">
                  <i class="arrow">→</i>
                  <span>{{ correctText(part.no) }}</span>
                </template>
              </span>
              <template v-else>{{ part.text }}</template>
            </template>
          </p>

          <div class="optbox">
            <div
              v-for="option in group.options || []"
              :key="option.key"
              :class="{ hit: optionHit(group, option.key), mis: optionMiss(group, option.key) }"
            >
              <em>{{ option.key }}</em>
              <span>{{ option.text }}</span>
            </div>
          </div>
        </div>

        <div v-if="sectionRows(group).length" class="rows">
          <div class="rows-title">{{ t('reader.review.summaryRows') }}</div>
          <div
            v-for="row in sectionRows(group)"
            :key="row.no"
            class="row"
            :class="[rowOk(row.no) ? 'ok' : 'no', { on: openGap === row.no }]"
          >
            <div class="row-top">
              <span class="row-no">{{ row.no }}</span>
              <span class="row-mine">{{ row.minePhrase || mineText(row.no) }}</span>
              <template v-if="!rowOk(row.no) && row.corPhrase">
                <i class="arrow">→</i>
                <span class="row-cor">{{ row.corPhrase }}</span>
              </template>
            </div>
            <p v-if="row.diag" class="row-diag" v-html="rich(row.diag)"></p>
            <div v-if="openGap === row.no" class="gap-quote">
              <span class="gq-label">{{ t('reader.review.answerSentence') }}</span>
              <template v-if="quoteFor(row, sectionFor(group)).length">
                <p
                  v-for="line in quoteFor(row, sectionFor(group))"
                  :key="line.id"
                  class="gq-en"
                >{{ line.en }}</p>
                <p
                  v-for="line in quoteFor(row, sectionFor(group))"
                  :key="'zh-' + line.id"
                  class="gq-zh"
                >{{ line.zh }}</p>
              </template>
              <p v-else class="gq-empty">{{ t('reader.review.noCite') }}</p>
            </div>
            <p v-if="row.src" class="row-src">{{ row.src }}</p>
          </div>
        </div>

        <div v-if="sectionDiag(group)" class="group-note" v-html="rich(sectionDiag(group))"></div>
        <div v-if="sectionNote(group)" class="group-note soft" v-html="rich(sectionNote(group))"></div>
      </template>

      <template v-else>
        <div v-if="group.type === 'matching' && group.options && group.options.length" class="optbox static">
          <div v-for="option in group.options" :key="option.key">
            <em>{{ option.key }}</em>
            <span>{{ option.text }}</span>
          </div>
        </div>

        <article
          v-for="item in group.items"
          :key="item.no"
          class="qcard"
          :class="{ ok: isOk(item.no), no: !isOk(item.no), open: isOpen(item.no), 'has-rev': expandable(item.no) }"
          @click="expandable(item.no) && toggle(item.no)"
        >
          <button
            type="button"
            class="qhead"
            :disabled="!expandable(item.no)"
            @click.stop="expandable(item.no) && toggle(item.no)"
          >
            <span class="qno">{{ item.no }}</span>
            <span class="tag" :class="isOk(item.no) ? 'ok' : 'no'">
              {{ isOk(item.no) ? t('common.correct') : t('common.wrong') }}
            </span>
            <span v-if="expandable(item.no)" class="qmore">
              {{ moreLabel(item.no) }}
              <i :class="{ flip: isOpen(item.no) }">▾</i>
            </span>
          </button>

          <p v-if="item.stem" class="stem">{{ item.stem }}</p>

          <ul v-if="item.options && item.options.length" class="opts">
            <li
              v-for="option in item.options"
              :key="option.key"
              class="opt"
              :class="optionState(item.no, option.key)"
            >
              <i>{{ option.key }}</i>
              <span>{{ option.text }}</span>
              <span v-if="optionState(item.no, option.key) === 'correct'" class="mk">✓</span>
              <span v-else-if="optionState(item.no, option.key) === 'mine-wrong'" class="mk">×</span>
            </li>
          </ul>

          <div v-else-if="group.type === 'ynng' || group.type === 'tfng'" class="ynrow">
            <span class="chip-lbl">{{ t('reader.mine') }}</span>
            <span class="chip" :class="isOk(item.no) ? 'ok' : 'no'">{{ mineText(item.no) }}</span>
            <span class="chip-lbl">{{ t('reader.right') }}</span>
            <span class="chip ok">{{ correctText(item.no) }}</span>
          </div>

          <div v-if="group.type !== 'ynng' && group.type !== 'tfng'" class="ansline">
            <span>{{ t('reader.mine') }} <b :class="isOk(item.no) ? 'good' : 'bad'">{{ mineText(item.no) }}</b></span>
            <span>{{ t('reader.right') }} <b class="good">{{ correctText(item.no) }}</b></span>
          </div>

          <div v-if="isOpen(item.no)" class="qrev" @click.stop>
            <p v-if="analysisFor(item.no)?.diag" class="qrev-d" v-html="rich(analysisFor(item.no)?.diag)"></p>
            <button
              v-if="analysisFor(item.no)?.cites && analysisFor(item.no)?.cites?.length"
              type="button"
              class="cite"
              @click.stop="emit('cite', item.no)"
            >
              {{ citeText(item.no) }}
              <em>· {{ t('reader.review.citeHint') }}</em>
            </button>
            <p v-if="analysisFor(item.no)?.chain" class="qrev-c">
              <b>{{ t('reader.review.chain') }}</b>
              <span v-html="rich(analysisFor(item.no)?.chain)"></span>
            </p>
          </div>
        </article>

        <div v-if="sectionDiag(group)" class="group-note" v-html="rich(sectionDiag(group))"></div>
        <div v-if="sectionNote(group)" class="group-note soft" v-html="rich(sectionNote(group))"></div>
      </template>
    </section>

    <p v-if="groups.length === 0" class="empty">{{ t('reader.noQuestions') }}</p>
  </div>
</template>

<style scoped>
.rail {
  padding: 2px 2px 40px;
  font-family: var(--font-serif);
}

.sect + .sect {
  margin-top: 28px;
}

.sect-t {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 10px;
  font-family: var(--font-sans);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.14em;
  color: var(--fg-3);
}

.sect-t::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--line-hair);
}

.sect-desc {
  margin: -2px 0 14px;
  color: var(--fg-3);
  font-family: var(--font-serif);
  font-size: 14.5px;
  line-height: 1.7;
  white-space: pre-line;
}

.qcard {
  padding: 15px 17px;
  margin-bottom: 12px;
  border: 0.5px solid var(--line-strong);
  border-radius: 10px;
  background: transparent;
  transition: border-color 0.16s var(--ease-out-cubic);
}

.qcard.ok {
  border-color: var(--ok-line);
}

.qcard.no {
  border-color: var(--bad-line);
}

.qcard.has-rev {
  cursor: pointer;
}

.qhead {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 0;
  text-align: left;
}

.qhead:disabled {
  cursor: default;
}

.qno {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 28px;
  height: 23px;
  padding: 0 7px;
  border-radius: var(--radius-xs);
  background: var(--bg-sunken);
  color: var(--fg-2);
  font-family: var(--font-serif);
  font-size: 14px;
  font-weight: 600;
}

.qcard.ok .qno {
  background: var(--ok-bg);
  color: var(--fg);
}

.qcard.no .qno {
  background: var(--bad-bg);
  color: var(--fg);
}

.tag {
  padding: 2px 7px;
  border-radius: 3px;
  font-family: var(--font-sans);
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.tag.ok {
  background: var(--ok-bg);
  color: var(--fg);
}

.tag.no {
  background: var(--bad-bg);
  color: var(--fg);
}

.qmore {
  margin-left: auto;
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: 12px;
  letter-spacing: 0.02em;
}

.qmore:hover {
  color: var(--fg);
}

.qmore i {
  display: inline-block;
  margin-left: 4px;
  font-style: normal;
  transition: transform 0.2s var(--ease-out-cubic);
}

.qmore i.flip {
  transform: rotate(180deg);
}

.stem {
  margin: 9px 0 11px;
  color: var(--fg);
  font-family: var(--font-serif);
  font-size: 18px;
  line-height: 1.6;
}

.opts {
  margin: 0;
  padding: 0;
  list-style: none;
}

.opt {
  position: relative;
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 6px 24px 6px 8px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  color: var(--fg-muted);
  font-family: var(--font-serif);
  font-size: 17.5px;
  line-height: 1.5;
}

.opt i {
  width: 15px;
  flex-shrink: 0;
  padding-top: 2px;
  color: var(--fg-muted);
  font-size: 16px;
  font-style: normal;
  font-weight: 600;
}

.opt span {
  flex: 1;
}

.opt.correct {
  background: var(--ok-bg);
  border-color: var(--ok-line);
  color: var(--fg);
  font-weight: 600;
}

.opt.correct i {
  color: var(--fg);
}

.opt.mine-wrong {
  background: var(--bad-bg);
  border-color: var(--bad-line);
  color: var(--fg);
  font-weight: 600;
}

.opt.mine-wrong i {
  color: var(--fg);
}

.mk {
  position: absolute;
  top: 4px;
  right: 7px;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.8;
}

.opt.correct .mk {
  color: var(--fg);
}

.opt.mine-wrong .mk {
  color: var(--fg);
}

.ynrow {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin: 6px 0 2px;
}

.chip-lbl {
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: 10.5px;
}

.chip {
  padding: 4px 10px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-sm);
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 600;
}

.chip.ok {
  background: var(--ok-bg);
  border-color: var(--ok-line);
  color: var(--fg);
  font-weight: 700;
}

.chip.no {
  background: var(--bad-bg);
  border-color: var(--bad-line);
  color: var(--fg);
  font-weight: 700;
}

.ansline {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
  margin-top: 8px;
  padding-top: 7px;
  border-top: 1px dashed var(--line-hair);
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: 12.5px;
}

.ansline b {
  font-family: var(--font-serif);
  font-size: 15.5px;
  font-weight: 600;
}

.ansline b.good {
  color: var(--fg);
}

.ansline b.bad {
  color: var(--fg);
}

.qrev {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 0.5px solid var(--line-hair);
  animation: qrev-in 0.18s var(--ease-out-cubic);
}

@keyframes qrev-in {
  from {
    opacity: 0;
    transform: translateY(-2px);
  }
}

.qrev-d {
  margin: 0;
  color: var(--fg-2);
  font-family: var(--font-serif);
  font-size: 16px;
  line-height: 1.85;
}

.qrev-d :deep(em),
.qrev-c :deep(em),
.row-diag :deep(em),
.group-note :deep(em) {
  color: var(--fg);
  font-style: normal;
  font-weight: 600;
}

.cite {
  margin-top: 9px;
  color: var(--fg-2);
  font-family: var(--font-sans);
  font-size: 12.5px;
  text-decoration: underline;
  text-decoration-color: var(--line-soft);
  text-underline-offset: 3px;
}

.cite:hover {
  color: var(--fg);
  text-decoration-color: var(--fg);
}

.cite em {
  color: var(--fg-3);
  font-style: normal;
}

.qrev-c {
  margin: 10px 0 0;
  color: var(--fg-2);
  font-family: var(--font-serif);
  font-size: 16px;
  line-height: 1.85;
}

.qrev-c b {
  display: block;
  margin-bottom: 2px;
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.sum-box {
  padding: 15px 17px;
  border: 0.5px solid var(--line-strong);
  border-radius: 10px;
  background: transparent;
}

.sum-t {
  margin: 0 0 10px;
  color: var(--fg);
  font-family: var(--font-serif);
  font-size: 18px;
  font-weight: 600;
}

.sum-text {
  margin: 0;
  color: var(--fg);
  font-family: var(--font-serif);
  font-size: 17.5px;
  line-height: 1.95;
}

.blank {
  cursor: pointer;
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  margin: 0 2px;
  padding: 1px 6px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-xs);
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  vertical-align: baseline;
}

.blank b {
  font-size: 9.5px;
  font-weight: 600;
  opacity: 0.65;
}

.blank:hover,
.blank:focus-visible {
  border-color: var(--fg);
}

.blank.on {
  box-shadow: 0 0 0 2px var(--fg);
}

.blank.ok {
  border-color: var(--ok-line);
  background: var(--ok-bg);
  color: var(--fg);
  font-weight: 700;
}

.blank.no {
  border-color: var(--bad-line);
  background: var(--bad-bg);
  color: var(--fg);
  font-weight: 700;
}

.arrow {
  font-style: normal;
  opacity: 0.55;
}

.optbox {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 2px 12px;
  margin-top: 11px;
  padding-top: 10px;
  border-top: 1px dashed var(--line-hair);
}

.optbox.static {
  margin: 0 0 12px;
  padding: 10px 12px;
  border: 0.5px solid var(--line-hair);
  border-radius: 8px;
}

.optbox div {
  display: flex;
  gap: 6px;
  padding: 2px 3px;
  border-radius: var(--radius-xs);
  color: var(--fg-muted);
  font-family: var(--font-serif);
  font-size: 16px;
  line-height: 1.65;
}

.optbox em {
  width: 13px;
  flex-shrink: 0;
  color: var(--fg-muted);
  font-size: 14px;
  font-style: normal;
  font-weight: 700;
}

.optbox .hit {
  color: var(--fg);
  font-weight: 600;
}

.optbox .hit em {
  color: var(--fg);
}

.optbox .mis {
  color: var(--fg);
  text-decoration: line-through;
  text-decoration-color: var(--bad-line);
}

.optbox .mis em {
  color: var(--fg);
}

.rows {
  margin-top: 14px;
}

.rows-title {
  margin-bottom: 6px;
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.1em;
}

.row {
  padding: 9px 0 9px 10px;
  border-left: 2px solid var(--line-hair);
}

.row + .row {
  margin-top: 2px;
}

.row.no {
  border-left-color: var(--bad-line);
}

.row.on {
  border-left-color: var(--fg);
  background: var(--bg-subtle);
}

.row.ok {
  border-left-color: var(--ok-line);
}

.row-top {
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex-wrap: wrap;
  font-family: var(--font-sans);
  font-size: 13px;
}

.row-no {
  color: var(--fg-3);
  font-variant-numeric: tabular-nums;
}

.row-mine {
  color: var(--fg);
  font-family: var(--font-serif);
  font-size: 15.5px;
}

.row-cor {
  color: var(--fg);
  font-family: var(--font-serif);
  font-size: 15.5px;
  font-weight: 600;
}

.gap-quote {
  margin-top: 8px;
  padding: 9px 12px;
  border-left: 2px solid var(--fg);
  background: var(--bg-subtle);
}

.gq-label {
  display: block;
  font-family: var(--font-sans);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.gq-en {
  margin: 4px 0 0;
  font-family: var(--font-serif);
  font-size: 16px;
  line-height: 1.7;
}

.gq-zh {
  margin: 2px 0 0;
  font-family: var(--font-sans);
  font-size: 13.5px;
  line-height: 1.6;
}

.gq-empty {
  margin: 4px 0 0;
  font-family: var(--font-sans);
  font-size: 12.5px;
}

.row-diag {
  margin: 4px 0 0;
  color: var(--fg-2);
  font-family: var(--font-serif);
  font-size: 15px;
  line-height: 1.8;
}

.row-src {
  margin: 4px 0 0;
  color: var(--fg-3);
  font-family: var(--font-serif);
  font-size: 13.5px;
  font-style: italic;
  line-height: 1.6;
}

.group-note {
  margin-top: 12px;
  padding: 10px 13px;
  border-left: 2px solid var(--accent);
  border-radius: 0 6px 6px 0;
  background: var(--bg-subtle);
  color: var(--fg-2);
  font-family: var(--font-serif);
  font-size: 15px;
  line-height: 1.8;
}

.group-note.soft {
  border-left-color: var(--line-strong);
  background: transparent;
  color: var(--fg-3);
}

.empty {
  padding: 40px 0;
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  text-align: center;
}

@media (max-width: 640px) {
  .qcard,
  .sum-box {
    padding: 13px 15px;
  }

  .stem,
  .sum-text {
    font-size: 17px;
  }

  .opt {
    font-size: 17px;
  }

  .optbox {
    grid-template-columns: 1fr;
  }
}
</style>
