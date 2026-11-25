<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import GlobalLookup from './components/GlobalLookup.vue'
import SideNav from './components/SideNav.vue'
import Toast from './components/Toast.vue'
import { bootstrapSync } from './sync'

const route = useRoute()
/** 阅读视图是沉浸式的：不显示全局侧栏，内容自己负责返回入口。 */
const immersive = computed(() => route.meta.immersive === true)

onMounted(bootstrapSync)
</script>

<template>
  <div class="shell" :class="{ immersive }">
    <SideNav v-if="!immersive" />
    <main class="main">
      <RouterView v-slot="{ Component }">
        <Transition name="page" mode="out-in">
          <component :is="Component" />
        </Transition>
      </RouterView>
    </main>
    <GlobalLookup />
    <Toast />
  </div>
</template>

<style scoped>
.shell {
  min-height: 100svh;
}

.main {
  min-height: 100svh;
  margin-left: var(--nav-w);
}

.shell.immersive .main {
  margin-left: 0;
  height: 100svh;
  min-height: 0;
  overflow: hidden;
}

.page-enter-active,
.page-leave-active {
  transition: opacity 0.18s var(--ease-out-cubic);
}

.page-enter-from,
.page-leave-to {
  opacity: 0;
}

@media (max-width: 900px) {
  .main {
    margin-left: 0;
    padding-top: var(--topbar-h);
  }

  .shell.immersive .main {
    padding-top: 0;
    height: auto;
    overflow: visible;
  }
}
</style>
