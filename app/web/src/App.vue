<script setup lang="ts">
import { RouterView } from 'vue-router'
import { toastState } from './toast'
</script>

<template>
  <RouterView />
  <div v-if="toastState.text" :key="toastState.key" class="toast">{{ toastState.text }}</div>
</template>
