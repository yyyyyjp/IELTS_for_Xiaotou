<script setup lang="ts">
withDefaults(
  defineProps<{
    variant?: 'plain' | 'subtle' | 'raised'
    padding?: 'none' | 'sm' | 'md' | 'lg'
  }>(),
  { variant: 'plain', padding: 'md' },
)
</script>

<template>
  <section class="card" :class="[variant, `pad-${padding}`]">
    <slot />
  </section>
</template>

<style scoped>
.card {
  border: 0.5px solid var(--line-hair);
  border-radius: var(--radius-lg);
  background: var(--bg-page);
}

.subtle {
  background: var(--bg-subtle);
}

.raised {
  background: var(--bg-raise);
  box-shadow: var(--shadow-sm);
}

.pad-none {
  padding: 0;
}

.pad-sm {
  padding: 16px;
}

.pad-md {
  padding: 24px;
}

.pad-lg {
  padding: 32px;
}
</style>
