<script setup lang="ts">
import { computed } from 'vue'
import type { Question } from '../types'
import { player } from '../audio'

const props = defineProps<{ question: Question }>()
const emit = defineEmits<{ close: [] }>()

const answers = computed(() => props.question.answers.join(' / '))

async function playSentence() {
  await player.speak(props.question.text)
}

async function playWord() {
  await player.speak(props.question.answers.join(', '))
}
</script>

<template>
  <div class="overlay" @click.self="emit('close')">
    <div class="panel" style="max-width: 620px">
      <h3 class="dm-word">{{ answers }}</h3>
      <div class="dm-sec"><i /><h4>原句</h4></div>
      <div class="dm-ex">
        <div class="en">{{ question.text }}</div>
        <div class="cn">{{ question.translation || '暂无翻译' }}</div>
        <div class="dm-row">
          <span class="muted">{{ question.meaning }}</span>
          <button class="dm-btn" @click="playWord">▶ 读答案</button>
          <button class="dm-btn" @click="playSentence">▶ 读整句</button>
        </div>
      </div>
      <div class="dm-sec"><i /><h4>作答</h4></div>
      <div class="dm-ex">
        <div class="cn">
          尝试 {{ question.attempts || 0 }} 次 ·
          {{ question.final === 'direct' ? '一次正确' : question.final === 'rewrite' ? '重写正确' : question.status === 'skipped' ? '已跳过' : '未完成' }}
        </div>
      </div>
      <div class="row">
        <div class="grow" />
        <button class="btn" @click="emit('close')">关闭 (Esc)</button>
      </div>
    </div>
  </div>
</template>
