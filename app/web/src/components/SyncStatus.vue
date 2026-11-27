<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'
import { adminApi, authEnabled, currentUser, logout } from '../auth'
import { t } from '../i18n'
import { coreDictCount, coreDictStatus } from '../localDict'
import {
  buildLocalSnapshot,
  lastSyncAt,
  lastSyncError,
  localCounts,
  pendingCount,
  precacheAllPacks,
  precachingPacks,
  restoreLocalSnapshot,
  syncNow,
  syncPhase,
} from '../sync'
import { toast } from '../toast'
import type { InviteRecord } from '../types'
import AppButton from './AppButton.vue'
import Icon from './Icon.vue'

const props = defineProps<{
  compact?: boolean
}>()

const open = ref(false)
const showInvites = ref(false)
const rootRef = ref<HTMLElement | null>(null)
const restoreInput = ref<HTMLInputElement | null>(null)

const invites = ref<InviteRecord[]>([])
const activeUsers = ref(0)
const inviteLoading = ref(false)
const inviteNote = ref('')
const inviteMaxUses = ref(1)
const creatingInvite = ref(false)

const isAdmin = computed(() => authEnabled.value && currentUser.value?.role === 'admin')

const label = computed(() => {
  if (syncPhase.value === 'syncing') return t('sync.syncing')
  if (syncPhase.value === 'pending') return t('sync.pending', { n: pendingCount.value })
  if (syncPhase.value === 'offline') return t('sync.offline')
  if (syncPhase.value === 'error') return t('sync.error')
  return t('sync.synced')
})

const lastSyncText = computed(() => {
  const ts = lastSyncAt.value
  if (!ts) return t('sync.never')
  const diff = Math.floor(Date.now() / 1000) - ts
  if (diff < 30) return t('sync.justNow')
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
})

const dictLabel = computed(() => {
  if (coreDictStatus.value === 'ready') {
    return t('sync.coreDictReady', { n: coreDictCount.value.toLocaleString() })
  }
  if (coreDictStatus.value === 'loading') return t('sync.coreDictLoading')
  return t('sync.coreDictNone')
})

function togglePanel(): void {
  open.value = !open.value
}

async function toggleInvites(): Promise<void> {
  showInvites.value = !showInvites.value
  if (showInvites.value) {
    await loadInvites()
  }
}

async function loadInvites(): Promise<void> {
  inviteLoading.value = true
  try {
    const res = await adminApi.listInvites()
    invites.value = res.items
    activeUsers.value = res.activeUsers
  } catch (err) {
    toast(err instanceof Error ? err.message : t('toast.loadFailed'))
  } finally {
    inviteLoading.value = false
  }
}

async function createInvite(): Promise<void> {
  if (creatingInvite.value) return
  creatingInvite.value = true
  try {
    const created = await adminApi.createInvite({
      maxUses: inviteMaxUses.value,
      note: inviteNote.value,
    })
    invites.value = [created, ...invites.value]
    inviteNote.value = ''
    await navigator.clipboard.writeText(created.code).catch(() => undefined)
    toast(t('auth.inviteCreated', { code: created.code }))
  } catch (err) {
    toast(err instanceof Error ? err.message : t('toast.loadFailed'))
  } finally {
    creatingInvite.value = false
  }
}

async function copyCode(code: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(code)
    toast(t('auth.inviteCopied'))
  } catch {
    /* ignore */
  }
}

async function revokeCode(code: string): Promise<void> {
  try {
    await adminApi.revokeInvite(code)
    await loadInvites()
    toast(t('auth.inviteRevoked'))
  } catch (err) {
    toast(err instanceof Error ? err.message : t('toast.loadFailed'))
  }
}

async function handlePrecache(): Promise<void> {
  try {
    const n = await precacheAllPacks((id) => api.packNetwork(id, true))
    toast(t('sync.precacheDone', { n }))
  } catch (err) {
    toast(err instanceof Error ? err.message : t('toast.loadFailed'))
  }
}

async function handleExport(): Promise<void> {
  const snap = await buildLocalSnapshot()
  const blob = new Blob([JSON.stringify(snap, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `xiaotou-backup-${currentUser.value?.login ?? 'local'}-${new Date().toISOString().slice(0, 10)}.json`
  a.click()
  URL.revokeObjectURL(url)
}

async function handleRestore(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  try {
    const raw = JSON.parse(await file.text())
    await restoreLocalSnapshot(raw)
    toast(t('sync.restored'))
  } catch (err) {
    toast(err instanceof Error ? err.message : t('toast.loadFailed'))
  } finally {
    input.value = ''
  }
}

function handleLogout(): void {
  open.value = false
  logout()
}

function onOutsideClick(event: MouseEvent): void {
  if (!open.value) return
  if (rootRef.value && event.target instanceof Node && !rootRef.value.contains(event.target)) {
    open.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', onOutsideClick)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onOutsideClick)
})
</script>

<template>
  <div ref="rootRef" class="sync-wrap" :class="{ compact: props.compact }" data-no-lookup>
    <button
      type="button"
      class="pill-btn"
      :class="syncPhase"
      :title="label"
      :aria-expanded="open"
      @click.stop="togglePanel"
    >
      <i class="dot" aria-hidden="true" />
      <span class="txt">{{ label }}</span>
    </button>

    <div v-if="open" class="panel" :class="{ 'drop-down': props.compact }" @click.stop>
      <div v-if="authEnabled && currentUser" class="user-bar">
        <img
          v-if="currentUser.avatarUrl"
          :src="currentUser.avatarUrl"
          :alt="currentUser.login"
          class="u-avatar"
        />
        <div class="u-info">
          <div class="u-login">
            @{{ currentUser.login }}
            <span v-if="isAdmin" class="admin-badge">{{ t('auth.adminBadge') }}</span>
          </div>
        </div>
        <button type="button" class="logout-btn" @click="handleLogout">
          {{ t('auth.logout') }}
        </button>
      </div>

      <div class="p-head">
        <span class="p-title">{{ t('sync.panelTitle') }}</span>
        <span class="p-state" :class="syncPhase">{{ label }}</span>
      </div>

      <div class="kv">
        <span>{{ t('sync.lastSync') }}</span>
        <span class="num">{{ lastSyncText }}</span>
      </div>

      <p v-if="lastSyncError" class="err-msg">{{ lastSyncError }}</p>

      <div class="stats-box">
        <div class="s-line">
          <span>{{ t('sync.localSummary') }}</span>
          <span class="num">
            {{ localCounts.vocab }} {{ t('common.words') }} · {{ t('sync.records', { n: localCounts.attempts }) }}
          </span>
        </div>
        <div class="s-line">
          <span>{{ t('sync.cachedPacks', { n: localCounts.cachedPacks }) }}</span>
          <span class="dict-tag" :class="{ ok: coreDictStatus === 'ready' }">{{ dictLabel }}</span>
        </div>
      </div>

      <div class="btn-grid">
        <AppButton size="sm" variant="outline" :disabled="syncPhase === 'syncing'" @click="syncNow">
          <Icon name="rotate" :size="13" />
          {{ t('sync.syncNow') }}
        </AppButton>
        <AppButton size="sm" :disabled="precachingPacks" @click="handlePrecache">
          <Icon name="cloud" :size="13" />
          {{ precachingPacks ? t('sync.precaching') : t('sync.precache') }}
        </AppButton>
        <AppButton size="sm" @click="handleExport">
          <Icon name="download" :size="13" />
          {{ t('sync.exportBackup') }}
        </AppButton>
        <AppButton size="sm" @click="restoreInput?.click()">
          <Icon name="upload" :size="13" />
          {{ t('sync.restoreBackup') }}
        </AppButton>
        <input
          ref="restoreInput"
          type="file"
          accept=".json"
          hidden
          @change="handleRestore"
        />
      </div>

      <!-- 仅管理员可见：邀请码管理 -->
      <div v-if="isAdmin" class="cfg-sec">
        <button type="button" class="cfg-toggle" @click="toggleInvites">
          <span>{{ t('auth.inviteManager') }}</span>
          <Icon :name="showInvites ? 'chevronDown' : 'chevronRight'" :size="13" />
        </button>

        <div v-if="showInvites" class="inv-box">
          <div class="inv-meta">
            {{ t('auth.activeUsers', { n: activeUsers }) }}
          </div>
          <div class="inv-create">
            <input
              v-model="inviteNote"
              type="text"
              class="cfg-input"
              :placeholder="t('auth.inviteNotePlaceholder')"
            />
            <select v-model.number="inviteMaxUses" class="cfg-select">
              <option :value="1">{{ t('auth.inviteUses', { n: 1 }) }}</option>
              <option :value="3">{{ t('auth.inviteUses', { n: 3 }) }}</option>
              <option :value="5">{{ t('auth.inviteUses', { n: 5 }) }}</option>
              <option :value="10">{{ t('auth.inviteUses', { n: 10 }) }}</option>
            </select>
            <AppButton size="sm" variant="primary" :disabled="creatingInvite" @click="createInvite">
              {{ t('auth.inviteNew') }}
            </AppButton>
          </div>

          <div v-if="inviteLoading" class="inv-empty">{{ t('common.loading') }}</div>
          <div v-else-if="invites.length" class="inv-list">
            <div
              v-for="inv in invites"
              :key="inv.code"
              class="inv-row"
              :class="{ dead: inv.revokedAt > 0 || inv.usedCount >= inv.maxUses }"
            >
              <div class="inv-left">
                <span class="inv-code mono">{{ inv.code }}</span>
                <span class="inv-sub">
                  {{ inv.usedCount }}/{{ inv.maxUses }}
                  <template v-if="inv.note"> · {{ inv.note }}</template>
                  <template v-if="inv.revokedAt > 0"> · {{ t('auth.revoked') }}</template>
                </span>
              </div>
              <div class="inv-ops">
                <button type="button" class="mini-op" @click="copyCode(inv.code)">
                  <Icon name="copy" :size="12" />
                </button>
                <button
                  v-if="inv.revokedAt === 0 && inv.usedCount < inv.maxUses"
                  type="button"
                  class="mini-op bad"
                  @click="revokeCode(inv.code)"
                >
                  <Icon name="x" :size="12" />
                </button>
              </div>
            </div>
          </div>
          <div v-else class="inv-empty">{{ t('common.empty') }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sync-wrap {
  position: relative;
  font-family: var(--font-sans);
}

.pill-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  width: 100%;
  padding: 6px 10px;
  border-radius: var(--radius-sm);
  color: var(--fg-2);
  font-size: var(--text-xs);
  line-height: 1.3;
  text-align: left;
  transition: background-color 0.15s var(--ease-out-cubic), color 0.15s var(--ease-out-cubic);
}

.sync-wrap.compact .pill-btn {
  width: auto;
  height: 30px;
  padding: 0 10px;
  border: 0.5px solid var(--line-soft);
  border-radius: var(--radius-md);
  background: var(--bg-page);
}

.pill-btn:hover {
  background: var(--bg-sunken);
  color: var(--fg);
}

.dot {
  flex-shrink: 0;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ok);
}

.pill-btn.syncing .dot {
  background: var(--sky);
  animation: sync-pulse 1s ease-in-out infinite;
}

.pill-btn.pending .dot {
  background: var(--accent);
}

.pill-btn.offline .dot {
  background: var(--fg-3);
}

.pill-btn.error .dot {
  background: var(--error);
}

@keyframes sync-pulse {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.45;
    transform: scale(0.82);
  }
}

.panel {
  position: absolute;
  left: 0;
  bottom: calc(100% + 8px);
  z-index: 95;
  width: 320px;
  max-height: min(560px, 80svh);
  overflow-y: auto;
  padding: 14px 15px;
  border: 0.5px solid var(--line-soft);
  border-radius: var(--radius-lg);
  background: var(--bg-raise);
  color: var(--fg);
  box-shadow: var(--shadow-md);
  animation: panel-in 0.15s var(--ease-out-quart);
}

.panel.drop-down {
  left: auto;
  right: 0;
  bottom: auto;
  top: calc(100% + 8px);
}

.user-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 0.5px solid var(--line-hair);
}

.u-avatar {
  width: 24px;
  height: 24px;
  border-radius: 50%;
}

.u-info {
  flex: 1;
  min-width: 0;
}

.u-login {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: var(--text-xs);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.admin-badge {
  padding: 1px 5px;
  border-radius: var(--radius-xs);
  background: color-mix(in srgb, var(--accent) 14%, var(--bg-raise));
  color: var(--accent-strong);
  font-size: 10px;
  font-weight: 600;
}

.logout-btn {
  flex-shrink: 0;
  color: var(--fg-3);
  font-size: 11px;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.logout-btn:hover {
  color: var(--fg);
}

.p-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.p-title {
  font-size: var(--text-sm);
  font-weight: 600;
}

.p-state {
  color: var(--ok);
  font-size: 11px;
  font-weight: 500;
}

.p-state.pending {
  color: var(--accent-strong);
}

.p-state.error {
  color: var(--error);
}

.p-state.offline {
  color: var(--fg-3);
}

.kv {
  display: flex;
  justify-content: space-between;
  color: var(--fg-3);
  font-size: var(--text-xs);
}

.err-msg {
  margin: 6px 0 0;
  padding: 5px 8px;
  border-radius: var(--radius-xs);
  background: var(--bad-bg);
  color: var(--bad);
  font-size: 11px;
}

.stats-box {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-top: 10px;
  padding: 9px 10px;
  border-radius: var(--radius-sm);
  background: var(--bg-subtle);
  font-size: 11.5px;
  color: var(--fg-2);
}

.s-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.dict-tag {
  color: var(--fg-3);
  font-size: 11px;
}

.dict-tag.ok {
  color: var(--ok);
}

.btn-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  margin-top: 12px;
}

.cfg-sec {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 0.5px solid var(--line-hair);
}

.cfg-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 2px 0;
  color: var(--fg-2);
  font-size: var(--text-xs);
  font-weight: 500;
}

.cfg-toggle:hover {
  color: var(--fg);
}

.inv-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}

.inv-meta {
  color: var(--fg-3);
  font-size: 11px;
}

.inv-create {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 64px auto;
  gap: 5px;
}

.cfg-input,
.cfg-select {
  padding: 5px 7px;
  border: 0.5px solid var(--line-soft);
  border-radius: var(--radius-xs);
  background: var(--input-bg);
  color: var(--fg);
  font-size: 11.5px;
}

.inv-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 160px;
  overflow-y: auto;
}

.inv-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 5px 8px;
  border-radius: var(--radius-xs);
  background: var(--bg-subtle);
}

.inv-row.dead {
  opacity: 0.52;
}

.inv-left {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.inv-code {
  font-size: 11.5px;
  font-weight: 600;
}

.inv-sub {
  color: var(--fg-3);
  font-size: 10.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inv-ops {
  display: flex;
  gap: 2px;
}

.mini-op {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: var(--radius-xs);
  color: var(--fg-3);
}

.mini-op:hover {
  background: var(--bg-sunken);
  color: var(--fg);
}

.mini-op.bad:hover {
  color: var(--error);
}

.inv-empty {
  color: var(--fg-3);
  font-size: 11px;
  text-align: center;
  padding: 6px 0;
}

.mono {
  font-family: var(--font-mono);
}

@media (max-width: 900px) {
  .sync-wrap:not(.compact) .txt {
    display: none;
  }

  .sync-wrap:not(.compact) .pill-btn {
    width: 28px;
    height: 28px;
    padding: 0;
    justify-content: center;
  }

  .panel {
    left: auto;
    right: 0;
    bottom: auto;
    top: calc(100% + 8px);
  }
}
</style>
