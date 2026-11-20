<script setup lang="ts">
interface Choice {
  value: string
  label: string
  count?: number
}

defineProps<{
  modelValue: string
  options: Choice[]
  ariaLabel?: string
}>()

const emit = defineEmits<{ (event: 'update:modelValue', value: string): void }>()
</script>

<template>
  <div class="seg" role="tablist" :aria-label="ariaLabel">
    <button
      v-for="option in options"
      :key="option.value"
      type="button"
      role="tab"
      :aria-selected="modelValue === option.value"
      :class="{ on: modelValue === option.value }"
      @click="emit('update:modelValue', option.value)"
    >
      {{ option.label }}
      <span v-if="option.count !== undefined" class="count num">{{ option.count }}</span>
    </button>
  </div>
</template>

<style scoped>
.seg {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  border-radius: var(--radius-md);
  background: var(--bg-sunken);
}

button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  padding: 0 10px;
  border-radius: var(--radius-sm);
  color: var(--fg-3);
  font-size: var(--text-sm);
  font-weight: 400;
  line-height: 1;
  transition:
    background-color 0.2s var(--ease-out-cubic),
    color 0.2s var(--ease-out-cubic);
}

button:hover {
  color: var(--fg);
}

button.on {
  background: var(--bg-raise);
  color: var(--fg);
  font-weight: 500;
  box-shadow: var(--shadow-sm);
}

.count {
  color: var(--fg-3);
  font-size: var(--text-micro);
}

.on .count {
  color: var(--fg-2);
}
</style>
