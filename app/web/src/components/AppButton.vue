<script setup lang="ts">
withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'ghost' | 'clay' | 'outline'
    size?: 'sm' | 'md'
    block?: boolean
    disabled?: boolean
    type?: 'button' | 'submit'
  }>(),
  { variant: 'secondary', size: 'md', block: false, disabled: false, type: 'button' },
)
</script>

<template>
  <button
    :type="type"
    class="btn"
    :class="[variant, size, { block, disabled }]"
    :disabled="disabled"
  >
    <slot />
  </button>
</template>

<style scoped>
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 0;
  border-radius: var(--radius-md);
  font-family: var(--font-sans);
  font-size: 15px;
  font-weight: 500;
  line-height: 1;
  white-space: nowrap;
  transition:
    background-color 0.2s var(--ease-out-cubic),
    box-shadow 0.2s var(--ease-out-cubic),
    color 0.2s var(--ease-out-cubic);
}

.btn.md {
  height: 36px;
  padding: 0 16px;
}

.btn.sm {
  height: 30px;
  padding: 0 12px;
  font-size: var(--text-sm);
}

.block {
  width: 100%;
}

.primary {
  background: var(--bg-inverse);
  color: var(--fg-on-dark);
}

.primary:hover:not(.disabled) {
  box-shadow: 0 0 0 2px var(--bg-inverse);
}

.secondary {
  background: var(--bg-sunken);
  color: var(--fg);
}

.secondary:hover:not(.disabled) {
  box-shadow: 0 0 0 2px var(--bg-sunken);
}

.ghost {
  background: transparent;
  color: var(--fg-2);
}

.ghost:hover:not(.disabled) {
  background: var(--bg-sunken);
  color: var(--fg);
}

.outline {
  background: var(--bg-page);
  color: var(--fg);
  border: 1px solid var(--fg);
}

.outline:hover:not(.disabled) {
  background: var(--bg-sunken);
}

.clay {
  background: var(--accent-strong);
  color: #ffffff;
}

.clay:hover:not(.disabled) {
  box-shadow: 0 0 0 2px var(--accent-strong);
}

.disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
