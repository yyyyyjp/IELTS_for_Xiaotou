/**
 * GitHub OAuth 2.0 + HS256 JWT 认证工具（纯 Web Crypto API，零第三方依赖）。
 */

export interface AuthUser {
  id: string
  githubId: string
  login: string
  name: string
  avatarUrl: string
  role: 'admin' | 'user'
  status: 'active' | 'pending'
}

export interface JwtClaims {
  sub: string
  login: string
  role: 'admin' | 'user'
  status: 'active' | 'pending'
  iat: number
  exp: number
}

const enc = new TextEncoder()
const dec = new TextDecoder()

function toBase64Url(bytes: Uint8Array): string {
  let bin = ''
  for (let i = 0; i < bytes.length; i += 1) bin += String.fromCharCode(bytes[i])
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function fromBase64Url(str: string): Uint8Array {
  const pad = str.length % 4 === 0 ? '' : '='.repeat(4 - (str.length % 4))
  const b64 = str.replace(/-/g, '+').replace(/_/g, '/') + pad
  const bin = atob(b64)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i += 1) out[i] = bin.charCodeAt(i)
  return out
}

export function randomHex(bytesLen = 16): string {
  const buf = new Uint8Array(bytesLen)
  crypto.getRandomValues(buf)
  return Array.from(buf, (b) => b.toString(16).padStart(2, '0')).join('')
}

export function generateInviteCode(): string {
  const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
  const buf = new Uint8Array(8)
  crypto.getRandomValues(buf)
  const chars = Array.from(buf, (b) => alphabet[b % alphabet.length])
  return `XT-${chars.slice(0, 4).join('')}-${chars.slice(4, 8).join('')}`
}

async function importHmacKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    'raw',
    enc.encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign', 'verify'],
  )
}

export async function signJwt(
  user: Pick<AuthUser, 'id' | 'login' | 'role' | 'status'>,
  secret: string,
  ttlSec = 30 * 86400,
): Promise<string> {
  const now = Math.floor(Date.now() / 1000)
  const header = toBase64Url(enc.encode(JSON.stringify({ alg: 'HS256', typ: 'JWT' })))
  const claims: JwtClaims = {
    sub: user.id,
    login: user.login,
    role: user.role,
    status: user.status,
    iat: now,
    exp: now + ttlSec,
  }
  const payload = toBase64Url(enc.encode(JSON.stringify(claims)))
  const data = `${header}.${payload}`
  const key = await importHmacKey(secret)
  const sig = await crypto.subtle.sign('HMAC', key, enc.encode(data))
  return `${data}.${toBase64Url(new Uint8Array(sig))}`
}

export async function verifyJwt(token: string, secret: string): Promise<JwtClaims | null> {
  if (!token || !secret) return null
  const parts = token.split('.')
  if (parts.length !== 3) return null
  try {
    const [h, p, s] = parts
    const key = await importHmacKey(secret)
    const sigBytes = fromBase64Url(s)
    const valid = await crypto.subtle.verify(
      'HMAC',
      key,
      sigBytes.buffer as ArrayBuffer,
      enc.encode(`${h}.${p}`),
    )
    if (!valid) return null
    const claims = JSON.parse(dec.decode(fromBase64Url(p))) as JwtClaims
    if (!claims?.sub || !claims.exp) return null
    if (claims.exp < Math.floor(Date.now() / 1000)) return null
    return claims
  } catch {
    return null
  }
}

export function extractBearer(req: Request): string {
  const auth = req.headers.get('authorization') ?? ''
  if (auth.toLowerCase().startsWith('bearer ')) {
    return auth.slice(7).trim()
  }
  return ''
}

export function getCookie(req: Request, name: string): string {
  const raw = req.headers.get('cookie') ?? ''
  for (const part of raw.split(';')) {
    const idx = part.indexOf('=')
    if (idx <= 0) continue
    if (part.slice(0, idx).trim() === name) {
      return decodeURIComponent(part.slice(idx + 1).trim())
    }
  }
  return ''
}

export function userRowToPublic(r: Record<string, unknown>): AuthUser {
  return {
    id: String(r.id),
    githubId: String(r.github_id ?? ''),
    login: String(r.login ?? ''),
    name: String(r.name ?? ''),
    avatarUrl: String(r.avatar_url ?? ''),
    role: r.role === 'admin' ? 'admin' : 'user',
    status: r.status === 'active' ? 'active' : 'pending',
  }
}
