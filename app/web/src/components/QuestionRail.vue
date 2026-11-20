<script setup lang="ts">
import { computed, ref } from 'vue'
import { t } from '../i18n'
import type { QuestionGroup, ReadingResultItem } from '../types'

const props = defineProps<{
  groups: QuestionGroup[]
  answers: Record<number, string>
  submitted: boolean
  results: ReadingResultItem[]
}>()

const emit = defineEmits<{
  (event: 'answer', no: number, value: string): void
}>()

const focusGap = ref<number | null>(null)

const resultMap = computed<Record<number, ReadingResultItem>>(() => {
  const map: Record<number, ReadingResultItem> = {}
  for (const item of props.results) map[item.no] = item
  return map
})

const answered = computed(
  () => Object.values(props.answers).filter((value) => value !== '').length,
)
const total = computed(() => props.groups.reduce((sum, group) => sum + group.items.length, 0))
const correctCount = computed(() => props.results.filter((item) => item.correct).length)

const labels: Record<string, string> = {
  mcq: 'reader.sect.mcq',
  summary: 'reader.sect.summary',
  ynng: 'reader.sect.ynng',
  tfng: 'reader.sect.tfng',
}

const ynChoices = [
  { value: 'Y', label: 'YES' },
  { value: 'N', label: 'NO' },
  { value: 'NG', label: 'NG' },
]

const tfChoices = [
  { value: 'T', label: 'TRUE' },
  { value: 'F', label: 'FALSE' },
  { value: 'NG', label: 'NG' },
]

function sectionLabel(group: QuestionGroup): string {
  return t(labels[group.type] ?? group.type)
}

function range(group: QuestionGroup): string {
  const nos = group.items.map((item) => item.no)
  if (!nos.length) return ''
  const first = Math.min(...nos)
  const last = Math.max(...nos)
  return first === last ? String(first) : `${first}–${last}`
}

function setAnswer(no: number, value: string): void {
  emit('answer', no, value)
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

function gapNumbers(group: QuestionGroup): number[] {
  return [...(group.text || '').matchAll(/\{\{(\d+)\}\}/g)].map((m) => Number(m[1]))
}

function chooseGap(no: number): void {
  if (props.submitted) return
  focusGap.value = no
}

function chooseOption(group: QuestionGroup, key: string): void {
  if (props.submitted) return
  const nos = gapNumbers(group)
  const target = focusGap.value ?? nos.find((no) => !props.answers[no]) ?? nos[nos.length - 1]
  if (target === undefined) return
  setAnswer(target, key)
  focusGap.value = null
}

function optionState(no: number, key: string): 'correct' | 'mine-wrong' | '' {
  if (!props.submitted) return ''
  const item = resultMap.value[no]
  if (!item) return ''
  const answer = item.answer[0]
  if (answer === key) return 'correct'
  if (item.mine === key) return 'mine-wrong'
  return ''
}

function gapState(no: number): string {
  if (!props.submitted) return props.answers[no] ? 'filled' : ''
  if (!props.answers[no]) return 'skip'
  return resultMap.value[no]?.correct ? 'ok' : 'no'
}

function gapMine(no: number): string {
  return props.answers[no] || ''
}

function gapCorrect(no: number): string {
  return resultMap.value[no]?.answer[0] ?? ''
}

function cardState(no: number): string {
  if (!props.submitted) return ''
  return resultMap.value[no]?.correct ? 'ok' : 'no'
}

function mineText(no: number): string {
  const value = props.answers[no]
  return value ? value : t('reader.unanswered')
}

function correctText(no: number): string {
  const item = resultMap.value[no]
  return item ? item.answer.join(' / ') : ''
}

function answeredAll(): boolean {
  return answered.value >= total.value
}

</script>

<template>
  <div class="ans-wrap">
    <div v-if="submitted" class="scorebar">
      <div class="score-main">
        <span class="score-num">{{ correctCount }}</span>
        <span class="score-total">/ {{ total }}</span>
      </div>
      <span class="score-pct">{{ Math.round((correctCount / Math.max(1, total)) * 100) }}%</span>
    </div>

    <section v-for="group in groups" :key="group.id" class="sect">
      <div class="sect-t">
        <span>{{ sectionLabel(group) }} · {{ range(group) }}</span>
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
                :class="[gapState(part.no), { focus: focusGap === part.no && !submitted }]"
                @click="chooseGap(part.no)"
              >
                <b>{{ part.no }}</b>
                <template v-if="submitted">
                  <template v-if="!gapMine(part.no)">
                    <span>{{ gapCorrect(part.no) }}</span>
                  </template>
                  <template v-else>
                    <span>{{ gapMine(part.no) }}</span>
                    <template v-if="gapMine(part.no) !== gapCorrect(part.no)">
                      <i class="gap-arrow">→</i>
                      <span>{{ gapCorrect(part.no) }}</span>
                    </template>
                  </template>
                </template>
                <span v-else-if="gapMine(part.no)">{{ gapMine(part.no) }}</span>
              </span>
              <template v-else>{{ part.text }}</template>
            </template>
          </p>

          <div class="optbox">
            <div
              v-for="option in group.options || []"
              :key="option.key"
              :class="{
                hit: submitted && group.items.some((item) => resultMap[item.no]?.answer[0] === option.key),
                mis:
                  submitted &&
                  group.items.some(
                    (item) => answers[item.no] === option.key && resultMap[item.no]?.answer[0] !== option.key,
                  ),
                pick: !submitted && group.items.some((item) => answers[item.no] === option.key),
              }"
              @click="chooseOption(group, option.key)"
            >
              <em>{{ option.key }}</em>
              <span>{{ option.text }}</span>
            </div>
          </div>
        </div>
      </template>

      <template v-else>
        <div v-for="item in group.items" :key="item.no" class="qcard" :class="cardState(item.no)">
          <div class="qtop">
            <span class="qno">{{ item.no }}</span>
            <template v-if="submitted">
              <span class="tag" :class="cardState(item.no)">
                {{ cardState(item.no) === 'ok' ? t('common.correct') : t('common.wrong') }}
              </span>
            </template>
          </div>

          <p class="stem">{{ item.stem }}</p>

          <div v-if="group.type === 'ynng' || group.type === 'tfng'" class="ynrow">
            <button
              v-for="choice in group.type === 'ynng' ? ynChoices : tfChoices"
              :key="choice.value"
              type="button"
              class="chip"
              :class="{
                on: answers[item.no] === choice.value && !submitted,
                ok: submitted && resultMap[item.no]?.answer[0] === choice.value,
                no:
                  submitted &&
                  answers[item.no] === choice.value &&
                  resultMap[item.no]?.answer[0] !== choice.value,
              }"
              @click="!submitted && setAnswer(item.no, choice.value)"
            >
              {{ choice.label }}
            </button>
          </div>

          <ul v-else-if="item.options && item.options.length" class="opts">
            <li
              v-for="option in item.options"
              :key="option.key"
              class="opt"
              :class="[
                optionState(item.no, option.key),
                { pick: !submitted && answers[item.no] === option.key },
              ]"
              @click="!submitted && setAnswer(item.no, option.key)"
            >
              <i>{{ option.key }}</i>
              <span>{{ option.text }}</span>
              <span v-if="submitted && optionState(item.no, option.key) === 'correct'" class="mk">✓</span>
              <span v-if="submitted && optionState(item.no, option.key) === 'mine-wrong'" class="mk">×</span>
            </li>
          </ul>

          <input
            v-else
            class="fallback"
            :disabled="submitted"
            :value="answers[item.no] || ''"
            @input="setAnswer(item.no, ($event.target as HTMLInputElement).value)"
          />

          <div v-if="submitted" class="ansline">
            <span v-if="answers[item.no]">
              {{ t('reader.mine') }}
              <b :class="cardState(item.no)">{{ mineText(item.no) }}</b>
            </span>
            <span v-else>{{ t('reader.unanswered') }}</span>
            <span>{{ t('reader.right') }} <b class="good">{{ correctText(item.no) }}</b></span>
          </div>
        </div>
      </template>
    </section>

    <p v-if="total === 0" class="empty">{{ t('reader.noQuestions') }}</p>
  </div>
</template>

<style scoped>
.ans-wrap {
  padding: 2px 2px 40px;
  font-family: var(--font-serif);
}

.scorebar {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 22px;
  padding: 12px 16px;
  border: 0.5px solid var(--line-strong);
  border-radius: 10px;
  background: var(--bg-subtle);
}

.score-num {
  font-size: 28px;
  font-weight: 600;
  line-height: 1;
}

.score-total {
  color: var(--fg-3);
  font-size: 13px;
}

.score-pct {
  color: var(--fg-2);
  font-size: 12px;
}

.sect + .sect {
  margin-top: 26px;
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
  font-size: 14px;
  line-height: 1.75;
  white-space: pre-line;
}

.qcard {
  padding: 16px 18px;
  margin-bottom: 12px;
  border: 0.5px solid var(--line-strong);
  border-radius: 10px;
  background: var(--bg-raise);
  transition: border-color 0.16s var(--ease-out-cubic);
}

.qcard.ok {
  border-color: var(--ok-line);
}

.qcard.no {
  border-color: var(--bad-line);
}

.qtop {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 7px;
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
  font-size: 13px;
  font-weight: 600;
}

.qcard.ok .qno {
  background: var(--ok-bg);
  color: var(--ok);
}

.qcard.no .qno {
  background: var(--bad-bg);
  color: var(--bad);
}

.tag {
  padding: 2px 7px;
  border-radius: 3px;
  font-family: var(--font-sans);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.tag.ok {
  background: var(--ok-bg);
  color: var(--ok);
}

.tag.no {
  background: var(--bad-bg);
  color: var(--bad);
}

.stem {
  margin: 0 0 12px;
  color: var(--fg);
  font-family: var(--font-serif);
  font-size: 17.5px;
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
  padding: 7px 26px 7px 10px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  color: var(--fg-2);
  font-family: var(--font-serif);
  font-size: 17.5px;
  line-height: 1.5;
  cursor: pointer;
}

.opt:hover {
  background: var(--bg-subtle);
}

.opt i {
  width: 16px;
  flex-shrink: 0;
  padding-top: 2px;
  color: var(--fg-3);
  font-size: 16px;
  font-style: normal;
  font-weight: 600;
}

.opt span {
  flex: 1;
}

.opt.pick {
  background: var(--bg-sunken);
  border-color: var(--line-soft);
  color: var(--fg);
}

.opt.correct {
  background: var(--ok-bg);
  border-color: var(--ok-line);
  color: var(--ok);
}

.opt.correct i {
  color: var(--ok);
}

.opt.mine-wrong {
  background: var(--bad-bg);
  border-color: var(--bad-line);
  color: var(--bad);
}

.opt.mine-wrong i {
  color: var(--bad);
}

.mk {
  position: absolute;
  top: 4px;
  right: 8px;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.8;
}

.opt.correct .mk {
  color: var(--ok);
}

.opt.mine-wrong .mk {
  color: var(--bad);
}

.ynrow {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 8px;
}

.chip {
  padding: 5px 12px;
  border: 1px solid var(--line-hair);
  border-radius: var(--radius-sm);
  background: var(--bg-raise);
  color: var(--fg-2);
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.03em;
}

.chip:hover {
  border-color: var(--line-strong);
  color: var(--fg);
}

.chip.on {
  background: var(--bg-sunken);
  border-color: var(--line-strong);
  color: var(--fg);
}

.chip.ok {
  background: var(--ok-bg);
  border-color: var(--ok-line);
  color: var(--ok);
}

.chip.no {
  background: var(--bad-bg);
  border-color: var(--bad-line);
  color: var(--bad);
}

.ansline {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
  margin-top: 9px;
  padding-top: 8px;
  border-top: 1px dashed var(--line-hair);
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: 11.5px;
}

.ansline b {
  font-family: var(--font-serif);
  font-size: 14.5px;
  font-weight: 600;
}

.ansline b.good {
  color: var(--ok);
}

.ansline b.no {
  color: var(--bad);
}

.ansline b.ok {
  color: var(--ok);
}

.sum-box {
  padding: 16px 18px;
  border: 0.5px solid var(--line-strong);
  border-radius: 10px;
  background: var(--bg-raise);
}

.sum-t {
  margin: 0 0 12px;
  color: var(--fg);
  font-family: var(--font-serif);
  font-size: 18px;
  font-weight: 600;
}

.sum-text {
  color: var(--fg);
  font-family: var(--font-serif);
  font-size: 17.5px;
  line-height: 2;
}

.blank {
  display: inline-flex;
  align-items: baseline;
  gap: 5px;
  margin: 0 2px;
  padding: 2px 7px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-xs);
  background: var(--bg-subtle);
  color: var(--fg-2);
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  vertical-align: baseline;
}

.blank:hover {
  border-color: var(--accent);
  color: var(--fg);
}

.blank.focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 30%, transparent);
  color: var(--fg);
}

.blank.filled {
  border-color: var(--line-strong);
  background: var(--bg-sunken);
  color: var(--fg);
}

.blank b {
  font-size: 9.5px;
  font-weight: 600;
  opacity: 0.7;
}

.gap-arrow {
  font-style: normal;
  opacity: 0.55;
}

.blank.skip {
  border-style: dashed;
  background: transparent;
  color: var(--fg-3);
}

.blank.ok {
  border-color: var(--ok-line);
  background: var(--ok-bg);
  color: var(--ok);
}

.blank.no {
  border-color: var(--bad-line);
  background: var(--bad-bg);
  color: var(--bad);
}

.optbox {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 3px 12px;
  margin-top: 12px;
  padding-top: 11px;
  border-top: 1px dashed var(--line-hair);
}

.optbox div {
  display: flex;
  gap: 7px;
  padding: 2px 4px;
  border-radius: var(--radius-xs);
  color: var(--fg-2);
  font-family: var(--font-serif);
  font-size: 16px;
  line-height: 1.65;
  cursor: pointer;
}

.optbox div:hover {
  background: var(--bg-subtle);
  color: var(--fg);
}

.optbox em {
  width: 14px;
  flex-shrink: 0;
  color: var(--fg-3);
  font-family: var(--font-serif);
  font-size: 14px;
  font-style: normal;
  font-weight: 700;
}

.optbox .hit {
  color: var(--ok);
  font-weight: 600;
}

.optbox .hit em {
  color: var(--ok);
}

.optbox .mis {
  color: var(--bad);
  text-decoration: line-through;
  text-decoration-color: var(--bad-line);
}

.optbox .mis em {
  color: var(--bad);
}

.optbox .pick {
  background: var(--bg-sunken);
  color: var(--fg);
  font-weight: 600;
}

.fallback {
  width: 100%;
  margin-top: 8px;
  padding: 6px 9px;
  border: 1px solid var(--line-soft);
  border-radius: 6px;
  background: var(--input-bg);
  color: var(--fg);
  font-family: var(--font-serif);
  font-size: 14px;
}

.empty {
  padding: 40px 0;
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  text-align: center;
}

@media (max-width: 640px) {
  .qcard {
    padding: 14px 16px;
  }

  .stem,
  .sum-text {
    font-size: 16.5px;
  }

  .opt {
    padding-right: 22px;
    font-size: 16.5px;
  }

  .sum-t {
    font-size: 17px;
  }
}
</style>
