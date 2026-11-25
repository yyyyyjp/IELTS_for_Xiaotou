<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { lang, setLang, t } from '../i18n'
import { dueCount, refreshVocabCounts } from '../state'
import { setTheme, theme } from '../theme'
import Icon from './Icon.vue'
import type { IconName } from '../icons'

const route = useRoute()

const links: { path: string; label: string; icon: IconName }[] = [
  { path: '/', label: 'nav.overview', icon: 'home' },
  { path: '/read', label: 'nav.read', icon: 'book' },
  { path: '/dictate', label: 'nav.dictate', icon: 'headphones' },
  { path: '/vocab', label: 'nav.vocab', icon: 'bookmark' },
  { path: '/stats', label: 'nav.stats', icon: 'chart' },
]

function isActive(path: string): boolean {
  return path === '/' ? route.path === '/' : route.path.startsWith(path)
}

onMounted(refreshVocabCounts)
watch(() => route.fullPath, refreshVocabCounts)
</script>

<template>
  <aside class="nav">
    <RouterLink to="/" class="brand" aria-label="小头雅思">小头雅思</RouterLink>

    <nav class="links" :aria-label="t('nav.overview')">
      <RouterLink
        v-for="link in links"
        :key="link.path"
        :to="link.path"
        class="link"
        :class="{ active: isActive(link.path) }"
        :aria-label="t(link.label)"
        :title="t(link.label)"
      >
        <Icon :name="link.icon" :size="18" />
        <span>{{ t(link.label) }}</span>
        <i v-if="link.path === '/vocab' && dueCount > 0" class="dot" aria-hidden="true" />
      </RouterLink>
    </nav>

    <div class="prefs">
      <div class="seg" role="group" :aria-label="t('theme.label')">
        <button
          :class="{ on: theme === 'light' }"
          :aria-label="t('theme.light')"
          :aria-pressed="theme === 'light'"
          :title="t('theme.light')"
          @click="setTheme('light')"
        >
          <Icon name="sun" :size="15" />
        </button>
        <button
          :class="{ on: theme === 'dark' }"
          :aria-label="t('theme.dark')"
          :aria-pressed="theme === 'dark'"
          :title="t('theme.dark')"
          @click="setTheme('dark')"
        >
          <Icon name="moon" :size="15" />
        </button>
      </div>

      <div class="seg lang" role="group" :aria-label="t('lang.label')">
        <button
          :class="{ on: lang === 'zh' }"
          :aria-pressed="lang === 'zh'"
          :aria-label="t('lang.label') + ' 中文'"
          @click="setLang('zh')"
        >
          中
        </button>
        <button
          :class="{ on: lang === 'en' }"
          :aria-pressed="lang === 'en'"
          :aria-label="t('lang.label') + ' English'"
          @click="setLang('en')"
        >
          EN
        </button>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.nav {
  position: fixed;
  inset: 0 auto 0 0;
  z-index: 40;
  display: flex;
  flex-direction: column;
  width: var(--nav-w);
  padding: 28px 16px 20px;
  border-right: 0.5px solid var(--line-hair);
  background: var(--bg-page);
}

.brand {
  padding: 0 10px 32px;
  font-family: var(--font-serif);
  font-size: 26px;
  font-weight: 500;
  line-height: 1;
  letter-spacing: 0;
}

.links {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}

.link {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  color: var(--fg-2);
  font-size: 14px;
  line-height: 1.4;
  text-align: left;
  transition: background-color 0.2s var(--ease-out-cubic), color 0.2s var(--ease-out-cubic);
}

.link span {
  flex: 1;
}

.link:hover {
  background: var(--bg-sunken);
  color: var(--fg);
}

.link.active {
  background: var(--bg-sunken);
  color: var(--fg);
  font-weight: 500;
  box-shadow: inset 2px 0 0 var(--accent);
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
}

.prefs {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 16px;
  border-top: 0.5px solid var(--line-hair);
}

.seg {
  display: flex;
  gap: 2px;
  padding: 2px;
  border-radius: var(--radius-md);
  background: var(--bg-sunken);
}

.seg button {
  display: grid;
  place-items: center;
  width: 28px;
  height: 24px;
  border-radius: var(--radius-xs);
  color: var(--fg-3);
  font-size: var(--text-micro);
  font-weight: 500;
  transition: background-color 0.2s var(--ease-out-cubic), color 0.2s var(--ease-out-cubic);
}

.seg button:hover {
  color: var(--fg);
}

.seg button.on {
  background: var(--bg-raise);
  color: var(--fg);
  box-shadow: var(--shadow-sm);
}

.seg.lang button {
  width: 32px;
}

@media (max-width: 900px) {
  .nav {
    inset: 0 0 auto 0;
    width: auto;
    height: var(--topbar-h);
    flex-direction: row;
    align-items: center;
    gap: 16px;
    padding: 0 14px;
    border-right: 0;
    border-bottom: 0.5px solid var(--line-hair);
    overflow-x: auto;
  }

  .brand {
    padding: 0;
    font-size: 21px;
  }

  .links {
    flex-direction: row;
    align-items: center;
    gap: 2px;
  }

  .link {
    width: 36px;
    height: 36px;
    padding: 0;
    justify-content: center;
  }

  .link span {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }

  .link.active {
    background: transparent;
    box-shadow: inset 0 -2px 0 var(--accent);
  }

  .link.active:hover {
    background: var(--bg-subtle);
  }

  .dot {
    position: absolute;
    top: 7px;
    right: 8px;
  }

  .prefs {
    gap: 6px;
    padding: 0;
    border: 0;
  }

  .seg button {
    width: 24px;
    height: 22px;
  }

  .seg.lang button {
    width: 28px;
  }
}

@media (max-width: 520px) {
  .brand {
    display: none;
  }

  .nav {
    gap: 8px;
  }
}
</style>
