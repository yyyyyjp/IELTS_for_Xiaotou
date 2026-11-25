import type {
  PackDetail,
  PackSummary,
  SyncAttemptRecord,
  SyncSessionRecord,
  VocabItem,
} from './types'

export type StoreName =
  | 'meta'
  | 'dict_blob'
  | 'packs_summary'
  | 'packs_detail'
  | 'vocab'
  | 'sessions'
  | 'attempts'
  | 'outbox'

export interface CachedPackDetail {
  id: string
  withAnswers: boolean
  mtime: number
  detail: PackDetail
}

export interface OutboxRecord {
  opId: string
  kind: 'vocab' | 'session' | 'attempt'
  key: string
  payload: unknown
  ts: number
}

export type CompactDictTuple = [string, string, string, string, number, string]

const DB_NAME = 'xiaotou_local_v1'
const DB_VERSION = 1

let dbPromise: Promise<IDBDatabase | null> | null = null
const memFallback = new Map<StoreName, Map<string, unknown>>()

function getMemStore(store: StoreName): Map<string, unknown> {
  let map = memFallback.get(store)
  if (!map) {
    map = new Map()
    memFallback.set(store, map)
  }
  return map
}

function keyFieldOf(store: StoreName): string {
  switch (store) {
    case 'meta':
    case 'dict_blob':
      return 'key'
    case 'vocab':
      return 'lemma'
    case 'attempts':
      return 'clientId'
    case 'outbox':
      return 'opId'
    default:
      return 'id'
  }
}

export function openLocalDb(): Promise<IDBDatabase | null> {
  if (dbPromise) return dbPromise
  if (typeof indexedDB === 'undefined') {
    dbPromise = Promise.resolve(null)
    return dbPromise
  }
  dbPromise = new Promise((resolve) => {
    try {
      const req = indexedDB.open(DB_NAME, DB_VERSION)
      req.onupgradeneeded = () => {
        const db = req.result
        const stores: StoreName[] = [
          'meta',
          'dict_blob',
          'packs_summary',
          'packs_detail',
          'vocab',
          'sessions',
          'attempts',
          'outbox',
        ]
        for (const name of stores) {
          if (!db.objectStoreNames.contains(name)) {
            db.createObjectStore(name, { keyPath: keyFieldOf(name) })
          }
        }
      }
      req.onsuccess = () => resolve(req.result)
      req.onerror = () => resolve(null)
    } catch {
      resolve(null)
    }
  })
  return dbPromise
}

export async function idbGet<T>(store: StoreName, key: string): Promise<T | undefined> {
  const db = await openLocalDb()
  if (!db) return getMemStore(store).get(key) as T | undefined
  return new Promise((resolve) => {
    try {
      const tx = db.transaction(store, 'readonly')
      const req = tx.objectStore(store).get(key)
      req.onsuccess = () => resolve(req.result as T | undefined)
      req.onerror = () => resolve(undefined)
    } catch {
      resolve(undefined)
    }
  })
}

export async function idbGetAll<T>(store: StoreName): Promise<T[]> {
  const db = await openLocalDb()
  if (!db) return Array.from(getMemStore(store).values()) as T[]
  return new Promise((resolve) => {
    try {
      const tx = db.transaction(store, 'readonly')
      const req = tx.objectStore(store).getAll()
      req.onsuccess = () => resolve((req.result ?? []) as T[])
      req.onerror = () => resolve([])
    } catch {
      resolve([])
    }
  })
}

export async function idbCount(store: StoreName): Promise<number> {
  const db = await openLocalDb()
  if (!db) return getMemStore(store).size
  return new Promise((resolve) => {
    try {
      const tx = db.transaction(store, 'readonly')
      const req = tx.objectStore(store).count()
      req.onsuccess = () => resolve(req.result ?? 0)
      req.onerror = () => resolve(0)
    } catch {
      resolve(0)
    }
  })
}

export async function idbPut<T extends object>(store: StoreName, value: T): Promise<void> {
  const db = await openLocalDb()
  if (!db) {
    const kf = keyFieldOf(store)
    const k = String((value as Record<string, unknown>)[kf] ?? '')
    if (k) getMemStore(store).set(k, value)
    return
  }
  return new Promise((resolve) => {
    try {
      const tx = db.transaction(store, 'readwrite')
      tx.objectStore(store).put(value)
      tx.oncomplete = () => resolve()
      tx.onerror = () => resolve()
    } catch {
      resolve()
    }
  })
}

export async function idbPutMany<T extends object>(store: StoreName, values: T[]): Promise<void> {
  if (!values.length) return
  const db = await openLocalDb()
  if (!db) {
    const kf = keyFieldOf(store)
    const m = getMemStore(store)
    for (const v of values) {
      const k = String((v as Record<string, unknown>)[kf] ?? '')
      if (k) m.set(k, v)
    }
    return
  }
  return new Promise((resolve) => {
    try {
      const tx = db.transaction(store, 'readwrite')
      const os = tx.objectStore(store)
      for (const v of values) os.put(v)
      tx.oncomplete = () => resolve()
      tx.onerror = () => resolve()
    } catch {
      resolve()
    }
  })
}

export async function idbDelete(store: StoreName, key: string): Promise<void> {
  const db = await openLocalDb()
  if (!db) {
    getMemStore(store).delete(key)
    return
  }
  return new Promise((resolve) => {
    try {
      const tx = db.transaction(store, 'readwrite')
      tx.objectStore(store).delete(key)
      tx.oncomplete = () => resolve()
      tx.onerror = () => resolve()
    } catch {
      resolve()
    }
  })
}

export async function idbDeleteMany(store: StoreName, keys: string[]): Promise<void> {
  if (!keys.length) return
  const db = await openLocalDb()
  if (!db) {
    const m = getMemStore(store)
    for (const k of keys) m.delete(k)
    return
  }
  return new Promise((resolve) => {
    try {
      const tx = db.transaction(store, 'readwrite')
      const os = tx.objectStore(store)
      for (const k of keys) os.delete(k)
      tx.oncomplete = () => resolve()
      tx.onerror = () => resolve()
    } catch {
      resolve()
    }
  })
}

export async function getMeta<T>(key: string, fallback: T): Promise<T> {
  const row = await idbGet<{ key: string; value: T }>('meta', key)
  return row ? row.value : fallback
}

export async function setMeta<T>(key: string, value: T): Promise<void> {
  await idbPut('meta', { key, value })
}

export type LocalVocab = VocabItem & { deletedAt: number }
export type { PackSummary, PackDetail, SyncSessionRecord, SyncAttemptRecord }
