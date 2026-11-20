<script setup lang="ts">
import { computed } from 'vue'
import { t } from '../i18n'
import type { LexEntry } from '../types'
import { splitHighlight } from '../utils/words'
import AppButton from './AppButton.vue'
import AudioButton from './AudioButton.vue'
import Icon from './Icon.vue'

const props = defineProps<{
  word: string
  entry: LexEntry | null
  context?: string
  contextZh?: string
  saved: boolean
  x: number
  y: number
}>()

const emit = defineEmits<{
  (event: 'close'): void
  (event: 'toggle'): void
}>()

const WIDTH = 304

const left = computed(() => Math.min(Math.max(12, props.x - 24), window.innerWidth - WIDTH - 12))
const top = computed(() => {
  const below = props.y + 240 < window.innerHeight
  return below ? props.y + 10 : Math.max(12, props.y - 246)
})
const parts = computed(() =>
  props.context ? splitHighlight(props.context, props.word) : [],
)
</script>

<template>
  <div
    class="pop"
    role="dialog"
    :aria-label="word"
    :style="{ left: `${left}px`, top: `${top}px`, width: `${WIDTH}px` }"
    @click.stop
  >
    <div class="head">
      <div class="word serif">{{ word }}</div>
      <div class="actions">
        <AudioButton :text="word" :size="30" :label="t('reader.pronounce')" />
        <button type="button" class="close" :aria-label="t('common.close')" @click="emit('close')">
          <Icon name="x" :size="15" />
        </button>
      </div>
    </div>

    <div v-if="entry?.pos || entry?.phonetic" class="sub">
      <span v-if="entry?.pos">{{ entry.pos }}</span>
      <span v-if="entry?.phonetic" class="mono">{{ entry.phonetic }}</span>
    </div>

    <p class="gloss">{{ entry?.gloss || t('reader.noGloss') }}</p>

    <div v-if="context" class="context">
      <p class="en">
        <template v-for="(part, index) in parts" :key="index">
          <span :class="{ hit: part.hit }">{{ part.text }}</span>
        </template>
      </p>
      <p v-if="contextZh" class="zh">{{ contextZh }}</p>
    </div>

    <AppButton
      :variant="saved ? 'secondary' : 'primary'"
      size="sm"
      block
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
  z-index: 70;
  padding: 16px;
  border: 0.5px solid var(--line-hair);
  border-radius: var(--radius-lg);
  background: var(--bg-raise);
  box-shadow: var(--shadow-md);
  animation: panel-in 0.18s var(--ease-out-quart);
}

.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.word {
  font-size: 21px;
  font-weight: 500;
  line-height: 1.2;
  word-break: break-word;
}

.actions {
  display: flex;
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
  gap: 8px;
  margin-top: 4px;
  color: var(--fg-3);
  font-size: var(--text-xs);
}

.mono {
  font-family: var(--font-mono);
}

.gloss {
  margin-top: 8px;
  color: var(--fg);
  font-size: 14px;
  line-height: 1.55;
}

.context {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 0.5px solid var(--line-hair);
}

.en {
  color: var(--fg-2);
  font-size: var(--text-sm);
  line-height: 1.55;
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
  line-height: 1.5;
}

.toggle {
  margin-top: 16px;
}
</style>
