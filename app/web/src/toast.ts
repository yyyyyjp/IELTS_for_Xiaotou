import { ref } from 'vue'

export const toastState = ref<{ text: string; key: number }>({ text: '', key: 0 })

export function toast(text: string): void {
  toastState.value = { text, key: Date.now() }
  window.setTimeout(() => {
    if (Date.now() - toastState.value.key >= 880) {
      toastState.value = { text: '', key: 0 }
    }
  }, 900)
}
