import { ref } from 'vue'
import { api } from './api'

export const dueCount = ref(0)
export const vocabTotal = ref(0)

export async function refreshVocabCounts(): Promise<void> {
  try {
    const stats = await api.vocabStats()
    dueCount.value = stats.dueNow
    vocabTotal.value = stats.total
  } catch {
    /* 侧栏计数失败不打断主流程 */
  }
}
