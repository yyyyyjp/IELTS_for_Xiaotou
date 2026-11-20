<script setup lang="ts">
import { ref } from 'vue'
import { ttsUrl } from '../api'
import { t } from '../i18n'
import { playUrl } from '../utils/audio'
import Icon from './Icon.vue'

const props = withDefaults(
  defineProps<{
    text?: string
    url?: string
    size?: number
    label?: string
  }>(),
  { size: 36, label: '' },
)

const playing = ref(false)

async function play(event: MouseEvent): Promise<void> {
  event.stopPropagation()
  if (playing.value) return
  const src = props.url || (props.text ? ttsUrl(props.text) : '')
  if (!src) return
  playing.value = true
  try {
    await playUrl(src, props.text ?? '')
  } finally {
    playing.value = false
  }
}
</script>

<template>
  <button
    type="button"
    class="audio"
    :class="{ playing }"
    :style="{ width: `${size}px`, height: `${size}px` }"
    :aria-label="label || t('common.play')"
    :title="label || t('common.play')"
    @click="play"
  >
    <Icon name="volume" :size="Math.round(size * 0.46)" />
  </button>
</template>

<style scoped>
.audio {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  border: 0.5px solid var(--line-soft);
  border-radius: 50%;
  background: transparent;
  color: var(--fg-2);
  transition:
    background-color 0.2s var(--ease-out-cubic),
    color 0.2s var(--ease-out-cubic);
}

.audio:hover {
  background: var(--bg-sunken);
  color: var(--fg);
}

.audio.playing {
  color: var(--accent);
}
</style>
