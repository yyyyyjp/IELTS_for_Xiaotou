<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { t } from '../i18n'
import type { DictLookupResult } from '../types'
import { splitHighlight } from '../utils/words'
import AppButton from './AppButton.vue'
import AudioButton from './AudioButton.vue'
import Icon from './Icon.vue'

const props = defineProps<{
  word: string
  result: DictLookupResult | null
  loading?: boolean
  busy?: boolean
  context?: string
  contextZh?: string
  saved: boolean
  x: number
  y: number
  anchorTop?: number
}>()

const emit = defineEmits<{
  (event: 'close'): void
  (event: 'toggle'): void
  (event: 'lookup', word: string): void
}>()

const popRef = ref<HTMLElement | null>(null)
const popHeight = ref(240)
const showDictGloss = ref(false)
const showLoadingHint = ref(false)
let loadingTimer = 0

const WIDTH = computed(() => Math.min(340, window.innerWidth - 24))

function measure(): void {
  if (popRef.value) {
    popHeight.value = popRef.value.offsetHeight
  }
}

watch(
  () => [props.word, props.result, props.loading, showDictGloss.value],
  () => {
    nextTick(measure)
  },
)

watch(
  () => props.word,
  () => {
    showDictGloss.value = false
  },
)

watch(
  () => props.loading,
  (isLoading) => {
    window.clearTimeout(loadingTimer)
    if (isLoading) {
      loadingTimer = window.setTimeout(() => {
        showLoadingHint.value = true
      }, 90)
    } else {
      showLoadingHint.value = false
    }
  },
  { immediate: true },
)

onMounted(() => {
  nextTick(measure)
})

onBeforeUnmount(() => {
  window.clearTimeout(loadingTimer)
})

const left = computed(() => {
  const w = WIDTH.value
  return Math.min(Math.max(12, props.x - 24), Math.max(12, window.innerWidth - w - 12))
})

const top = computed(() => {
  const h = Math.min(popHeight.value, window.innerHeight - 24)
  const belowSpace = window.innerHeight - props.y - 12
  if (belowSpace >= h + 10) {
    return props.y + 10
  }
  const aboveAnchor = props.anchorTop ?? props.y
  if (aboveAnchor - h - 10 >= 12) {
    return aboveAnchor - h - 10
  }
  return Math.max(12, Math.min(window.innerHeight - h - 12, props.y + 10))
})

const parts = computed(() =>
  props.context ? splitHighlight(props.context, props.word) : [],
)

const displayTags = computed(() => {
  const items: { key: string; label: string; primary?: boolean }[] = []
  const res = props.result
  if (!res) return items
  for (const tag of res.tags ?? []) {
    const label = t(`dict.tag.${tag}`)
    items.push({ key: tag, label, primary: tag === 'ielts' })
  }
  if (res.oxford) {
    items.push({ key: 'oxford', label: t('dict.tag.oxford') })
  }
  return items.slice(0, 5)
})

const stars = computed(() => {
  const n = props.result?.collins ?? 0
  return n > 0 ? '★'.repeat(Math.min(5, n)) : ''
})

const hasBadges = computed(() => displayTags.value.length > 0 || Boolean(stars.value))
</script>

<template>
  <div
    ref="popRef"
    class="pop"
    data-lookup-popover
    role="dialog"
    :aria-label="word"
    :style="{ left: `${left}px`, top: `${top}px`, width: `${WIDTH}px` }"
    @click.stop
    @mouseup.stop
  >
    <div class="head">
      <div class="word-wrap">
        <div class="word serif">{{ word }}</div>
        <span v-if="result?.source === 'pack'" class="source-pill">
          {{ t('dict.sourcePack') }}
        </span>
      </div>
      <div class="actions">
        <AudioButton :text="word" :size="30" :label="t('reader.pronounce')" />
        <button type="button" class="close" :aria-label="t('common.close')" @click="emit('close')">
          <Icon name="x" :size="15" />
        </button>
      </div>
    </div>

    <div v-if="result?.phonetic || result?.pos || result?.formNote" class="sub">
      <span v-if="result?.phonetic" class="mono phonetic">/{{ result.phonetic }}/</span>
      <span v-if="result?.pos" class="pos">{{ result.pos }}</span>
      <span v-if="result?.formNote" class="form-note">{{ result.formNote }}</span>
    </div>

    <div v-if="hasBadges" class="badges">
      <span
        v-for="tag in displayTags"
        :key="tag.key"
        class="tag"
        :class="{ primary: tag.primary }"
      >{{ tag.label }}</span>
      <span v-if="stars" class="stars" :title="`Collins ${result?.collins}`">{{ stars }}</span>
    </div>

    <div class="body">
      <p v-if="loading && !result && showLoadingHint" class="gloss muted">
        {{ t('dict.lookingUp') }}
      </p>

      <template v-else-if="result?.gloss">
        <p class="gloss">{{ result.gloss }}</p>
        <div v-if="result.dictGloss" class="dict-extra">
          <button
            type="button"
            class="dict-toggle"
            @click="showDictGloss = !showDictGloss"
          >
            {{ showDictGloss ? t('dict.hideFullDict') : t('dict.fullDict') }}
          </button>
          <p v-if="showDictGloss" class="dict-gloss">{{ result.dictGloss }}</p>
        </div>
      </template>

      <div v-else-if="result?.tokens?.length" class="tokens">
        <div class="tokens-title">{{ t('dict.phraseBreakdown') }}</div>
        <button
          v-for="tok in result.tokens"
          :key="tok.word"
          type="button"
          class="token-row"
          @click="emit('lookup', tok.word)"
        >
          <span class="token-word serif">{{ tok.word }}</span>
          <span class="token-gloss">{{ tok.gloss }}</span>
        </button>
      </div>

      <p v-else-if="!loading" class="gloss muted">
        {{ result && !result.dictReady ? t('dict.notReady') : t('reader.noGloss') }}
      </p>

      <div v-if="context" class="context">
        <p class="en">
          <template v-for="(part, index) in parts" :key="index">
            <span :class="{ hit: part.hit }">{{ part.text }}</span>
          </template>
        </p>
        <p v-if="contextZh" class="zh">{{ contextZh }}</p>
      </div>
    </div>

    <AppButton
      :variant="saved ? 'secondary' : 'outline'"
      size="sm"
      block
      :disabled="busy"
      class="toggle"
      @click="emit('toggle')"
    >
      <Icon :name="saved ? 'check' : 'plus'" :size="15" />
      {{ saved ? t('reader.savedWord') : t('reader.addWord') }}
    </AppButton>
  </div>
</template>

<style scoped>
.pop {
  position: fixed;
  z-index: 90;
  display: flex;
  flex-direction: column;
  max-height: min(460px, calc(100vh - 24px));
  padding: 16px;
  border: 0.5px solid var(--line-soft);
  border-radius: var(--radius-lg);
  background: var(--bg-raise);
  color: var(--fg);
  font-family: var(--font-sans);
  box-shadow: var(--shadow-md);
  animation: panel-in 0.16s var(--ease-out-quart);
}

.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.word-wrap {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
}

.word {
  font-size: 21px;
  font-weight: 500;
  line-height: 1.2;
  word-break: break-word;
}

.source-pill {
  padding: 1px 6px;
  border-radius: var(--radius-pill);
  background: var(--bg-sunken);
  color: var(--fg-2);
  font-size: 11px;
  line-height: 1.5;
  white-space: nowrap;
}

.actions {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 4px;
}

.close {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  color: var(--fg-3);
}

.close:hover {
  background: var(--bg-sunken);
  color: var(--fg);
}

.sub {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px 10px;
  margin-top: 4px;
  color: var(--fg-2);
  font-size: var(--text-xs);
  line-height: 1.4;
}

.mono {
  font-family: var(--font-mono);
}

.phonetic {
  color: var(--fg-2);
}

.pos {
  font-weight: 500;
  color: var(--fg);
}

.form-note {
  color: var(--fg-3);
}

.badges {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  margin-top: 8px;
}

.tag {
  padding: 1px 6px;
  border: 0.5px solid var(--line-hair);
  border-radius: var(--radius-xs);
  background: var(--bg-subtle);
  color: var(--fg-2);
  font-size: 11px;
  line-height: 1.45;
}

.tag.primary {
  border-color: color-mix(in srgb, var(--accent) 35%, transparent);
  background: color-mix(in srgb, var(--accent) 12%, var(--bg-raise));
  color: var(--accent-strong);
  font-weight: 500;
}

.stars {
  margin-left: 2px;
  color: var(--warn);
  font-size: 11px;
  letter-spacing: 0.5px;
}

.body {
  overflow-y: auto;
  margin-top: 10px;
  padding-right: 2px;
}

.gloss {
  color: var(--fg);
  font-size: 14px;
  line-height: 1.55;
  white-space: pre-line;
  word-break: break-word;
}

.gloss.muted {
  color: var(--fg-3);
}

.dict-extra {
  margin-top: 8px;
}

.dict-toggle {
  padding: 0;
  color: var(--fg-3);
  font-size: var(--text-xs);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.dict-toggle:hover {
  color: var(--fg);
}

.dict-gloss {
  margin-top: 6px;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  background: var(--bg-subtle);
  color: var(--fg-2);
  font-size: var(--text-xs);
  line-height: 1.55;
  white-space: pre-line;
}

.tokens {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.tokens-title {
  margin-bottom: 2px;
  color: var(--fg-3);
  font-size: var(--text-xs);
}

.token-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  width: 100%;
  padding: 5px 8px;
  border-radius: var(--radius-sm);
  background: var(--bg-subtle);
  color: var(--fg);
  text-align: left;
  transition: background-color 0.15s var(--ease-out-cubic);
}

.token-row:hover {
  background: var(--bg-sunken);
}

.token-word {
  flex-shrink: 0;
  font-size: 14px;
  font-weight: 500;
}

.token-gloss {
  color: var(--fg-2);
  font-size: var(--text-xs);
  line-height: 1.45;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.context {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 0.5px solid var(--line-hair);
}

.en {
  color: var(--fg);
  font-family: var(--font-serif);
  font-size: var(--text-sm);
  line-height: 1.55;
}

.hit {
  color: var(--fg);
  font-weight: 600;
  box-shadow: inset 0 -1px 0 var(--accent);
}

.zh {
  margin-top: 4px;
  color: var(--fg-2);
  font-size: var(--text-xs);
  line-height: 1.5;
}

.toggle {
  flex-shrink: 0;
  margin-top: 14px;
}
</style>
