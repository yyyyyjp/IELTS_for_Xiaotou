const ALLOWED = new Set(['em', 'b', 'strong', 'i', 'u', 'br', 'code', 'span'])

/** 复盘内容里的轻量富文本：只保留排版标签，丢掉属性与脚本。 */
export function rich(value?: string | null): string {
  if (!value) return ''
  return String(value)
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/<style[\s\S]*?<\/style>/gi, '')
    .replace(/<([a-z][\w-]*)(?:\s[^>]*)?\/>/gi, (match, tag: string) =>
      ALLOWED.has(tag.toLowerCase()) ? `<${tag.toLowerCase()}>` : '',
    )
    .replace(/<([a-z][\w-]*)(?:\s[^>]*)?>/gi, (match, tag: string) =>
      ALLOWED.has(tag.toLowerCase()) ? `<${tag.toLowerCase()}>` : '',
    )
    .replace(/<\/([a-z][\w-]*)>/gi, (match, tag: string) =>
      ALLOWED.has(tag.toLowerCase()) ? `</${tag.toLowerCase()}>` : '',
    )
}
