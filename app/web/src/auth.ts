import { ref } from 'vue'
import { t } from './i18n'
import { setActiveLocalDbUser } from './localDb'
import { clearLookupCache } from './lookup'
import { apiBaseUrl, registerUnauthorizedHandler, resetSyncRuntime } from './sync'
import type { AuthMeResponse, AuthUser, InviteRecord } from './types'

const TOKEN_KEY = 'xiaotou.authToken'
const USER_KEY = 'xiaotou.authUser'

export type AuthState = 'loading' | 'unauthenticated' | 'pending' | 'authenticated'

export const authState = ref<AuthState>('loading')
export const authEnabled = ref(false)
export const currentUser = ref<AuthUser | null>(null)
export const authError = ref('')

export function getAuthToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? ''
  } catch {
    return ''
  }
}

export function setAuthToken(token: string): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* ignore */
  }
}

function saveCachedUser(user: AuthUser | null): void {
  try {
    if (user) localStorage.setItem(USER_KEY, JSON.stringify(user))
    else localStorage.removeItem(USER_KEY)
  } catch {
    /* ignore */
  }
}

function loadCachedUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as AuthUser) : null
  } catch {
    return null
  }
}

function consumeHashParams(): void {
  if (typeof window === 'undefined') return
  const hash = window.location.hash
  if (!hash || (!hash.includes('auth_token=') && !hash.includes('auth_error='))) return
  const params = new URLSearchParams(hash.replace(/^#/, ''))
  const token = params.get('auth_token')
  const err = params.get('auth_error')
  if (token) {
    setAuthToken(token)
    authError.value = ''
  }
  if (err) {
    authError.value = err
  }
  window.history.replaceState(null, '', window.location.pathname + window.location.search)
}

export function startGithubLogin(): void {
  authError.value = ''
  window.location.href = `${apiBaseUrl()}/auth/github/login`
}

export async function initAuth(): Promise<void> {
  authState.value = 'loading'
  consumeHashParams()

  const token = getAuthToken()
  const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {}

  try {
    const res = await fetch(`${apiBaseUrl()}/auth/me`, { headers })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = (await res.json()) as AuthMeResponse
    authEnabled.value = Boolean(data.authEnabled)

    if (!data.authEnabled) {
      const localUser: AuthUser = data.user ?? {
        id: 'local',
        githubId: '',
        login: 'local',
        name: t('auth.localMode'),
        avatarUrl: '',
        role: 'admin',
        status: 'active',
      }
      currentUser.value = localUser
      setActiveLocalDbUser(localUser.id)
      authState.value = 'authenticated'
      return
    }

    if (!data.authenticated || !data.user) {
      setAuthToken('')
      saveCachedUser(null)
      currentUser.value = null
      authState.value = 'unauthenticated'
      return
    }

    currentUser.value = data.user
    saveCachedUser(data.user)
    if (data.user.status !== 'active') {
      authState.value = 'pending'
      return
    }

    setActiveLocalDbUser(data.user.id)
    authState.value = 'authenticated'
  } catch {
    // 断网或云端短暂抖动时：若本机已缓存有效已激活登录态，允许直接离线进入自己专属 IndexedDB
    const cached = loadCachedUser()
    if (token && cached && cached.status === 'active') {
      authEnabled.value = true
      currentUser.value = cached
      setActiveLocalDbUser(cached.id)
      authState.value = 'authenticated'
      return
    }
    authEnabled.value = true
    currentUser.value = null
    authState.value = 'unauthenticated'
  }
}

export async function activateWithInvite(code: string): Promise<void> {
  const token = getAuthToken()
  const res = await fetch(`${apiBaseUrl()}/auth/activate`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ code: code.trim() }),
  })
  const body = (await res.json().catch(() => ({}))) as {
    detail?: string
    token?: string
    user?: AuthUser
  }
  if (!res.ok || !body.user) {
    throw new Error(body.detail || `HTTP ${res.status}`)
  }
  if (body.token) setAuthToken(body.token)
  currentUser.value = body.user
  saveCachedUser(body.user)
  setActiveLocalDbUser(body.user.id)
  authState.value = 'authenticated'
}

export function logout(): void {
  setAuthToken('')
  saveCachedUser(null)
  currentUser.value = null
  authError.value = ''
  clearLookupCache()
  resetSyncRuntime()
  setActiveLocalDbUser('anonymous')
  authState.value = 'unauthenticated'
}

registerUnauthorizedHandler(() => {
  if (authEnabled.value && authState.value === 'authenticated') {
    logout()
    authError.value = 'session_expired'
  }
})

// ── 管理员邀请码 API ──────────────────────────────────────────────────────

async function adminFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAuthToken()
  const res = await fetch(`${apiBaseUrl()}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`)
  }
  return body as T
}

export const adminApi = {
  listInvites: () => adminFetch<{ activeUsers: number; items: InviteRecord[] }>('/admin/invites'),
  createInvite: (payload: { maxUses?: number; note?: string }) =>
    adminFetch<InviteRecord>('/admin/invites', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  revokeInvite: (code: string) =>
    adminFetch<{ ok: true }>(`/admin/invites/${encodeURIComponent(code)}`, { method: 'DELETE' }),
}
