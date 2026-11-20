<script setup lang="ts">
defineProps<{
  eyebrow?: string
  title: string
}>()
</script>

<template>
  <header class="head">
    <div class="lead">
      <div v-if="eyebrow" class="eyebrow">{{ eyebrow }}</div>
      <h1>{{ title }}</h1>
      <div v-if="$slots.meta" class="meta"><slot name="meta" /></div>
    </div>
    <div v-if="$slots.actions" class="actions"><slot name="actions" /></div>
  </header>
</template>

<style scoped>
.head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-5);
  margin-bottom: var(--space-6);
}

.lead {
  min-width: 0;
}

h1 {
  margin-top: 10px;
  font-size: var(--text-h1);
  max-width: var(--measure-headline);
}

.meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 14px;
  margin-top: 10px;
  color: var(--fg-2);
  font-size: var(--text-sm);
}

.actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  padding-bottom: 2px;
}

@media (max-width: 720px) {
  .head {
    flex-direction: column;
    align-items: flex-start;
    gap: 16px;
  }

  .actions {
    width: 100%;
  }
}
</style>
