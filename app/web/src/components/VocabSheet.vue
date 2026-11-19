<script setup lang="ts">
import { onMounted, ref } from 'vue'
import type { Question } from '../types'
import { player } from '../audio'
import { api } from '../api'
import { toast } from '../toast'

const props = defineProps<{ questions: Question[]; bookId: string; current: number }>()
const emit = defineEmits<{ close: []; jump: [index: number]; reset: [] }>()

const items = ref<Question[]>(props.questions)

function statusTag(q: Question): { cls: string; text: string } {
  if (q.status === 'correct') return { cls: 'tag-g', text: q.final === 'direct' ? '一次正确' : '重写正确' }
  if (q.status === 'skipped') return { cls: 'tag-y', text: '跳过' }
  if (q.status === 'wrong') return { cls: 'tag-r', text: '错' }
  return { cls: 'tag-p', text: '未做' }
}

async function play(q: Question) {
  await player.playQuestion(q)
}

async function resetAll() {
  if (!window.confirm('重置本书全部进度？')) return
  try {
    await api.resetBook(props.bookId)
    items.value = items.value.map((q) => ({ ...q, status: 'todo', attempts: 0, final: '' }))
    toast('已重置')
    emit('reset')
  } catch (e) {
    toast((e as Error).message)
  }
}

onMounted(() => {
  const el = document.querySelector<HTMLElement>('.sheet-panel .li.cur')
  el?.scrollIntoView({ block: 'center' })
})
</script>

<template>
  <div class="overlay" style="justify-content: flex-end; padding: 0" @click.self="emit('close')">
    <div class="sheet-panel">
      <h3 style="margin: 0 0 4px; font-size: 15px">词表</h3>
      <div class="muted" style="margin-bottom: 12px">共 {{ items.length }} 题</div>
      <div
        v-for="(q, i) in items"
        :key="q.id"
        class="li"
        :class="{ cur: i === current }"
        style="cursor: pointer"
        @click="emit('jump', i)"
      >
        <div style="min-width: 0">
          <div class="w">{{ q.answers.join(' / ') }}</div>
          <div class="s">{{ q.text.slice(0, 46) }}{{ q.text.length > 46 ? '…' : '' }}</div>
        </div>
        <div style="display: flex; align-items: center; gap: 8px; flex: none">
          <button class="spk" title="播放" @click.stop="play(q)">▶</button>
          <span class="tag" :class="statusTag(q).cls">{{ statusTag(q).text }}</span>
        </div>
      </div>
      <button class="btn btn-danger" style="width: 100%; margin-top: 16px" @click="resetAll">
        重置本书进度
      </button>
      <button class="btn btn-primary" style="width: 100%; margin-top: 8px" @click="emit('close')">
        关闭 (Esc)
      </button>
    </div>
  </div>
</template>
