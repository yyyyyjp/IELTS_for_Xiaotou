import type { Cite } from '../types'

export function citeKey(p: number, b: number): string {
  return `${p}:${b}`
}

/** 把 {p, b[]} 展开成 "段:句" 集合，供左栏标记。 */
export function citeKeys(cites?: Cite[]): string[] {
  const out: string[] = []
  for (const cite of cites ?? []) {
    for (const b of cite.b ?? []) out.push(citeKey(cite.p, b))
  }
  return out
}

export function citeParagraphs(cites?: Cite[]): number[] {
  const out: number[] = []
  for (const cite of cites ?? []) {
    if (!out.includes(cite.p)) out.push(cite.p)
  }
  return out.sort((a, b) => a - b)
}
