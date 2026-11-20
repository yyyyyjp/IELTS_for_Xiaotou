import { ref } from 'vue'

export const toastText = ref('')
let timer = 0

export function toast(text: string): void {
  toastText.value = text
  window.clearTimeout(timer)
  timer = window.setTimeout(() => {
    toastText.value = ''
  }, 2200)
}
