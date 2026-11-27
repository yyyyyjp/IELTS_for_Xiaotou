<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  activateWithInvite,
  authError,
  authState,
  currentUser,
  logout,
  startGithubLogin,
} from '../auth'
import AppButton from './AppButton.vue'

const inviteCode = ref('')
const submitting = ref(false)
const activateErr = ref('')

const errorText = computed(() => {
  if (activateErr.value) return activateErr.value
  switch (authError.value) {
    case 'access_denied':
      return 'GitHub sign-in was canceled.'
    case 'invalid_state':
      return 'Sign-in verification expired. Please try again.'
    case 'session_expired':
      return 'Session expired. Please sign in again.'
    case '':
      return ''
    default:
      return `Sign-in failed (${authError.value}).`
  }
})

async function submitInvite(): Promise<void> {
  if (!inviteCode.value.trim() || submitting.value) return
  submitting.value = true
  activateErr.value = ''
  try {
    await activateWithInvite(inviteCode.value)
  } catch (err) {
    activateErr.value = err instanceof Error ? err.message : 'Activation failed.'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="gate" data-no-lookup>
    <div class="card">
      <div class="brand serif">Xiaotou IELTS</div>

      <template v-if="authState === 'pending' && currentUser">
        <div class="user-chip">
          <img
            v-if="currentUser.avatarUrl"
            :src="currentUser.avatarUrl"
            :alt="currentUser.login"
            class="avatar"
          />
          <div class="user-meta">
            <div class="u-name">{{ currentUser.name || currentUser.login }}</div>
            <div class="u-login mono">@{{ currentUser.login }}</div>
          </div>
        </div>

        <form class="form" @submit.prevent="submitInvite">
          <input
            v-model="inviteCode"
            type="text"
            class="code-input mono"
            autocomplete="off"
            spellcheck="false"
            placeholder="Invite code (XT-XXXX-XXXX)"
          />
          <AppButton variant="primary" block :disabled="submitting || !inviteCode.trim()" type="submit">
            {{ submitting ? 'Activating…' : 'Activate' }}
          </AppButton>
        </form>

        <p v-if="errorText" class="err">{{ errorText }}</p>

        <button type="button" class="switch-btn" @click="logout">
          Switch account
        </button>
      </template>

      <template v-else>
        <button type="button" class="gh-btn" @click="startGithubLogin">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true">
            <path
              d="M12 2C6.48 2 2 6.58 2 12.23c0 4.52 2.87 8.35 6.84 9.7.5.1.68-.22.68-.49 0-.24-.01-.88-.01-1.73-2.78.62-3.37-1.37-3.37-1.37-.45-1.18-1.11-1.49-1.11-1.49-.91-.64.07-.63.07-.63 1 .07 1.53 1.06 1.53 1.06.89 1.56 2.34 1.11 2.91.85.09-.66.35-1.11.63-1.37-2.22-.26-4.56-1.14-4.56-5.08 0-1.12.39-2.04 1.03-2.76-.1-.26-.45-1.31.1-2.73 0 0 .84-.28 2.75 1.05a9.35 9.35 0 0 1 5 0c1.91-1.33 2.75-1.05 2.75-1.05.55 1.42.2 2.47.1 2.73.64.72 1.03 1.64 1.03 2.76 0 3.95-2.34 4.82-4.57 5.07.36.32.68.94.68 1.9 0 1.37-.01 2.48-.01 2.82 0 .27.18.6.69.49A10.22 10.22 0 0 0 22 12.23C22 6.58 17.52 2 12 2z"
            />
          </svg>
          <span>Continue with GitHub</span>
        </button>

        <p v-if="errorText" class="err">{{ errorText }}</p>
      </template>
    </div>
  </div>
</template>

<style scoped>
.gate {
  display: grid;
  place-items: center;
  min-height: 100svh;
  padding: 24px;
  background: var(--bg-page);
  color: var(--fg);
}

.card {
  width: min(392px, 100%);
  padding: 36px 32px 30px;
  border: 0.5px solid var(--line-soft);
  border-radius: var(--radius-xl);
  background: var(--bg-raise);
  box-shadow: var(--shadow-md);
  text-align: center;
}

.brand {
  font-size: 28px;
  font-weight: 500;
  line-height: 1.1;
  letter-spacing: -0.01em;
}

.gh-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  width: 100%;
  height: 44px;
  margin-top: 26px;
  padding: 0 18px;
  border-radius: var(--radius-md);
  background: var(--bg-inverse);
  color: var(--fg-on-dark);
  font-size: 14px;
  font-weight: 500;
  transition: opacity 0.16s var(--ease-out-cubic), transform 0.12s;
}

.gh-btn:hover {
  opacity: 0.9;
}

.gh-btn:active {
  transform: scale(0.99);
}

.user-chip {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  margin-top: 20px;
  padding: 8px 14px;
  border: 0.5px solid var(--line-hair);
  border-radius: var(--radius-pill);
  background: var(--bg-subtle);
  text-align: left;
}

.avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
}

.u-name {
  font-size: var(--text-sm);
  font-weight: 500;
  line-height: 1.2;
}

.u-login {
  color: var(--fg-3);
  font-size: 11px;
}

.form {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 20px;
}

.code-input {
  width: 100%;
  height: 42px;
  padding: 0 12px;
  border: 0.5px solid var(--line-strong);
  border-radius: var(--radius-md);
  background: var(--input-bg);
  color: var(--fg);
  font-size: 15px;
  letter-spacing: 0.08em;
  text-align: center;
  text-transform: uppercase;
}

.code-input:focus {
  outline: none;
  border-color: var(--focus);
}

.mono {
  font-family: var(--font-mono);
}

.err {
  margin-top: 14px;
  padding: 8px 10px;
  border: 0.5px solid var(--bad-line);
  border-radius: var(--radius-sm);
  background: var(--bad-bg);
  color: var(--bad);
  font-size: var(--text-xs);
  line-height: 1.5;
}

.switch-btn {
  margin-top: 16px;
  color: var(--fg-3);
  font-size: var(--text-xs);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.switch-btn:hover {
  color: var(--fg);
}
</style>
