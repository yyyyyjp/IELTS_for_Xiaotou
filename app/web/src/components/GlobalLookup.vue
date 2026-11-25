<script setup lang="ts">
import { onBeforeUnmount, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  closeLookup,
  expandSelectionToWordBoundaries,
  extractSelectionContext,
  isLookupCandidate,
  lookupBusy,
  lookupState,
  lookupSubword,
  markRecentSelection,
  openLookup,
  toggleLookupVocab,
  wasRecentSelection,
} from '../lookup'
import WordPopover from './WordPopover.vue'

const route = useRoute()

let downX = 0
let downY = 0
let downIgnored = false

function isIgnoredTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false
  if (target.closest('[data-lookup-popover]')) return true
  if (target.closest('[data-no-lookup]')) return true
  if (target.closest('input, textarea, select, [contenteditable="true"]')) return true
  return false
}

function onMouseDown(event: MouseEvent): void {
  if (event.button !== 0) return
  downX = event.clientX
  downY = event.clientY
  downIgnored = isIgnoredTarget(event.target)
}

function handleSelectionTrigger(event: MouseEvent): void {
  if (event.button !== 0) return
  if (downIgnored || isIgnoredTarget(event.target)) return

  const moved = Math.hypot(event.clientX - downX, event.clientY - downY) >= 3
  const isDouble = event.detail >= 2
  // 普通单击（未拖动且非双击）不触发划词，留给页面点击（如展开所在句译文）
  if (!moved && !isDouble) return

  const sel = window.getSelection()
  if (!sel || sel.isCollapsed || sel.rangeCount === 0) return

  const anchorEl =
    sel.anchorNode?.nodeType === Node.ELEMENT_NODE
      ? (sel.anchorNode as Element)
      : sel.anchorNode?.parentElement
  if (isIgnoredTarget(anchorEl ?? null)) return

  // 划词未完整包住单词时，自动吸附扩展到完整英文单词边界
  const range = expandSelectionToWordBoundaries(sel) ?? sel.getRangeAt(0)
  const raw = range.toString()
  if (!isLookupCandidate(raw)) return

  const rect = range.getBoundingClientRect()
  if (rect.width === 0 && rect.height === 0) return

  markRecentSelection()
  const ctx = extractSelectionContext(range.startContainer, raw.trim())
  void openLookup({
    word: raw,
    x: rect.left,
    y: rect.bottom,
    anchorTop: rect.top,
    context: ctx.context,
    contextZh: ctx.contextZh,
    sentenceId: ctx.sentenceId,
    para: ctx.para,
  })
}

function onDocumentClick(event: MouseEvent): void {
  if (!lookupState.value) return
  if (wasRecentSelection()) return
  if (event.target instanceof Element && event.target.closest('[data-lookup-popover]')) return
  closeLookup()
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && lookupState.value) {
    closeLookup()
  }
}

watch(() => route.fullPath, closeLookup)

onMounted(() => {
  document.addEventListener('mousedown', onMouseDown)
  document.addEventListener('mouseup', handleSelectionTrigger)
  document.addEventListener('click', onDocumentClick)
  document.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onMouseDown)
  document.removeEventListener('mouseup', handleSelectionTrigger)
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <WordPopover
    v-if="lookupState"
    :word="lookupState.word"
    :result="lookupState.result"
    :loading="lookupState.loading"
    :busy="lookupBusy"
    :context="lookupState.context"
    :context-zh="lookupState.contextZh"
    :saved="lookupState.saved"
    :x="lookupState.x"
    :y="lookupState.y"
    :anchor-top="lookupState.anchorTop"
    @close="closeLookup"
    @toggle="toggleLookupVocab"
    @lookup="lookupSubword"
  />
</template>
