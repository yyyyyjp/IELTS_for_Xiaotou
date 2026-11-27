<script setup lang="ts">
import { computed } from 'vue'
import { lang } from '../i18n'

interface Quote {
  en: string
  zh: string
  authorEn: string
  authorZh: string
}

const QUOTES: Quote[] = [
  {
    en: 'The limits of my language mean the limits of my world.',
    zh: '语言的边界，即是世界的边界。',
    authorEn: 'Ludwig Wittgenstein',
    authorZh: '路德维希·维特根斯坦',
  },
  {
    en: 'Reading furnishes the mind only with materials of knowledge; it is thinking that makes what we read ours.',
    zh: '阅读只为头脑提供知识的材料，唯有思考，才使所读之物真正属于我们。',
    authorEn: 'John Locke',
    authorZh: '约翰·洛克',
  },
  {
    en: 'To read without reflecting is like eating without digesting.',
    zh: '只读而不思，犹食而不化。',
    authorEn: 'Edmund Burke',
    authorZh: '埃德蒙·伯克',
  },
  {
    en: 'We are what we repeatedly do. Excellence, then, is not an act, but a habit.',
    zh: '反复之行塑就吾辈；卓越并非一次壮举，而是一种习惯。',
    authorEn: 'Will Durant',
    authorZh: '威尔·杜兰特',
  },
  {
    en: 'Words are, of course, the most powerful drug used by mankind.',
    zh: '言语，诚然是人类所使用的最具力量的药石。',
    authorEn: 'Rudyard Kipling',
    authorZh: '鲁德亚德·吉卜林',
  },
  {
    en: 'Patience is bitter, but its fruit is sweet.',
    zh: '耐心味苦，其果甚甜。',
    authorEn: 'Jean-Jacques Rousseau',
    authorZh: '让-雅克·卢梭',
  },
]

const picked = QUOTES[Math.floor(Math.random() * QUOTES.length)]
const isZh = computed(() => lang.value === 'zh')
</script>

<template>
  <div class="loading-stage" role="status" aria-live="polite" data-no-lookup>
    <div class="orb" aria-hidden="true">
      <span class="ring ring-outer" />
      <span class="ring ring-inner" />
      <span class="core" />
    </div>
    <figure class="quote">
      <blockquote class="quote-en serif">“{{ picked.en }}”</blockquote>
      <p v-if="isZh" class="quote-zh">{{ picked.zh }}</p>
      <figcaption class="quote-author">
        — {{ isZh ? picked.authorZh : picked.authorEn }}
      </figcaption>
    </figure>
  </div>
</template>

<style scoped>
.loading-stage {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 24px;
  min-height: 60svh;
  padding: 32px 24px;
  text-align: center;
}

.orb {
  position: relative;
  width: 52px;
  height: 52px;
}

.ring {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 1.5px solid transparent;
}

.ring-outer {
  border-top-color: var(--accent);
  border-right-color: color-mix(in srgb, var(--accent) 28%, transparent);
  animation: spin 1.6s cubic-bezier(0.55, 0.15, 0.45, 0.85) infinite;
}

.ring-inner {
  inset: 9px;
  border-bottom-color: var(--fg-2);
  border-left-color: color-mix(in srgb, var(--fg-2) 25%, transparent);
  animation: spin-rev 2.2s linear infinite;
}

.core {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent);
  transform: translate(-50%, -50%);
  animation: pulse 1.8s ease-in-out infinite;
}

.quote {
  max-width: 460px;
  margin: 0;
}

.quote-en {
  margin: 0;
  color: var(--fg);
  font-size: 16px;
  font-style: italic;
  line-height: 1.65;
  letter-spacing: 0.01em;
}

.quote-zh {
  margin: 8px 0 0;
  color: var(--fg);
  opacity: 0.72;
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  line-height: 1.6;
}

.quote-author {
  margin-top: 10px;
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: var(--text-xs);
  letter-spacing: 0.04em;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes spin-rev {
  to {
    transform: rotate(-360deg);
  }
}

@keyframes pulse {
  0%,
  100% {
    opacity: 0.45;
    transform: translate(-50%, -50%) scale(0.85);
  }
  50% {
    opacity: 1;
    transform: translate(-50%, -50%) scale(1.15);
  }
}

@media (prefers-reduced-motion: reduce) {
  .ring-outer,
  .ring-inner,
  .core {
    animation: none;
  }
}
</style>
