<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    value: number
    total: number
    height?: number
    tone?: 'accent' | 'muted'
  }>(),
  { height: 3, tone: 'accent' },
)

const width = computed(() => {
  if (props.total <= 0) return 0
  return Math.min(100, Math.max(0, (props.value / props.total) * 100))
})
</script>

<template>
  <div
    class="bar"
    :class="tone"
    :style="{ height: `${height}px` }"
    role="progressbar"
    :aria-valuenow="value"
    :aria-valuemin="0"
    :aria-valuemax="total"
  >
    <span :style="{ width: `${width}%` }" />
  </div>
</template>

<style scoped>
.bar {
  width: 100%;
  overflow: hidden;
  border-radius: var(--radius-pill);
  background: var(--line-hair);
}

.bar span {
  display: block;
  height: 100%;
  border-radius: inherit;
  transition: width 0.4s var(--ease-out-quart);
}

.accent span {
  background: var(--accent);
}

.muted span {
  background: var(--fg-3);
}
</style>
