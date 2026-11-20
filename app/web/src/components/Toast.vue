<script setup lang="ts">
import { toastText } from '../toast'
</script>

<template>
  <Transition name="toast">
    <div v-if="toastText" class="toast" role="status">{{ toastText }}</div>
  </Transition>
</template>

<style scoped>
.toast {
  position: fixed;
  left: 50%;
  bottom: 32px;
  z-index: 80;
  transform: translateX(-50%);
  padding: 9px 16px;
  border-radius: var(--radius-md);
  background: var(--bg-inverse);
  color: var(--fg-on-dark);
  font-size: var(--text-sm);
  box-shadow: var(--shadow-md);
  white-space: nowrap;
}

.toast-enter-active,
.toast-leave-active {
  transition: opacity 0.18s var(--ease-out-cubic), transform 0.18s var(--ease-out-cubic);
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translate(-50%, 6px);
}

@media (max-width: 900px) {
  .toast {
    bottom: 24px;
  }
}
</style>
