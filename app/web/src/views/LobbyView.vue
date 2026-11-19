<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import type { Book } from '../types'
import ImportDialog from '../components/ImportDialog.vue'
import { toast } from '../toast'
import { player } from '../audio'

const router = useRouter()
const books = ref<Book[]>([])
const loading = ref(true)
const showImport = ref(false)
const serverVoice = ref('')
const browserVoice = ref('')

const imported = computed(() => books.value.filter((b) => b.source === 'import'))
const builtin = computed(() => books.value.filter((b) => b.source === 'builtin'))
const preparing = computed(() =>
  imported.value.some((b) => b.prepare && !b.prepare.ready && b.prepare.total > 0),
)

let timer = 0

async function load() {
  try {
    books.value = await api.books()
  } catch (err) {
    toast((err as Error).message)
  } finally {
    loading.value = false
  }
}

async function loadVoices() {
  try {
    const v = await api.voices()
    serverVoice.value = v.items.find((x) => x.id === v.default)?.label ?? v.default
  } catch {
    serverVoice.value = ''
  }
  browserVoice.value = player.browserVoiceLabel
  if (!browserVoice.value) {
    window.speechSynthesis?.addEventListener('voiceschanged', () => {
      browserVoice.value = player.browserVoiceLabel
    })
  }
}

function enter(b: Book) {
  router.push(`/stage/${b.id}`)
}

async function remove(b: Book) {
  if (!window.confirm(`删除词书「${b.name}」？该词书的练习进度会一并清除。`)) return
  try {
    await api.deleteBook(b.id)
    await load()
  } catch (err) {
    toast((err as Error).message)
  }
}

function progressText(b: Book): string {
  if (b.source === 'import' && b.prepare && !b.prepare.ready) {
    return `生成音频 ${b.prepare.done}/${b.prepare.total}`
  }
  return `已掌握 ${b.done}/${b.total}`
}

function onImported(id: string) {
  showImport.value = false
  router.push(`/stage/${id}`)
}

onMounted(async () => {
  await Promise.all([load(), loadVoices()])
  timer = window.setInterval(() => {
    if (preparing.value) load()
  }, 2500)
})

onUnmounted(() => window.clearInterval(timer))
</script>

<template>
  <div class="lobby">
    <div class="lobby-top">
      <div class="logo"><i />Tifo · 雅思听写</div>
      <div class="grow" />
      <button class="btn btn-primary" @click="showImport = true">＋ 导入词书</button>
    </div>

    <div class="voice-line">
      发音引擎：<b>{{ serverVoice || '微软 Neural 英音' }}</b>
      <span style="color: #a78bfa">·</span> 后端生成 mp3，全浏览器音质一致
      <span v-if="browserVoice" style="color: var(--muted)">
        · 断网兜底 {{ browserVoice.split(' - ')[0].split(' (')[0] }}
      </span>
    </div>

    <template v-if="!loading">
      <div v-if="imported.length">
        <h2 class="sec">我的词书 <span class="count">{{ imported.length }}</span></h2>
        <div class="cards">
          <div v-for="b in imported" :key="b.id" class="book-card" @click="enter(b)">
            <div class="book-cover">{{ b.name.slice(0, 1) }}</div>
            <div style="min-width: 0; flex: 1">
              <h3>{{ b.name }}</h3>
              <p>{{ b.intro }}</p>
              <div class="meta">{{ b.total }} 题 · {{ progressText(b) }}</div>
            </div>
            <button class="book-del" title="删除词书" @click.stop="remove(b)">×</button>
          </div>
        </div>
      </div>

      <div v-else>
        <h2 class="sec">我的词书</h2>
        <div class="empty">
          还没有导入任何词书。<br />
          点右上角「＋ 导入词书」，把 CSV / TXT 粘进去，句子会自动生成雅思英音。
        </div>
      </div>

      <h2 class="sec">内置词库 <span class="count">{{ builtin.length }}</span></h2>
      <div class="cards">
        <div v-for="b in builtin" :key="b.id" class="book-card" @click="enter(b)">
          <div class="book-cover" style="background: linear-gradient(135deg, #f97316, #ef4444)">
            真
          </div>
          <div style="min-width: 0; flex: 1">
            <h3>{{ b.name }}</h3>
            <p>{{ b.intro }}</p>
            <div class="meta">{{ b.total }} 题 · {{ progressText(b) }}</div>
          </div>
        </div>
      </div>
    </template>

    <ImportDialog v-if="showImport" @close="showImport = false" @created="onImported" />
  </div>
</template>
