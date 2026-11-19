<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { api } from '../api'
import type { ParsedItem, Voice } from '../types'
import { toast } from '../toast'

const emit = defineEmits<{ close: []; created: [id: string] }>()

const text = ref('')
const name = ref('')
const voice = ref('en-GB-SoniaNeural')
const voices = ref<Voice[]>([])
const items = ref<ParsedItem[]>([])
const count = ref(0)
const blanks = ref(0)
const creating = ref(false)
const err = ref('')

let timer = 0
let seq = 0

const SAMPLE = [
  '单词,例句,例句翻译,释义',
  'authorisation,"You\'ll need authorisation to keep pets in the apartment.",你需要获得授权才能在公寓里养宠物。,授权',
  'disposal,Rubbish disposal is on Wednesdays.,垃圾清理是在每周三。,处理/清理',
  'refundable,Could you confirm whether the deposit is refundable?,能否确认押金是否可退？,可退的',
  'The landlord said the {{deposit}} is {{refundable}} if we {{cancel}} two weeks ahead.,房东说提前两周取消的话押金可退。,',
].join('\n')

async function doParse() {
  const raw = text.value.trim()
  if (!raw) {
    items.value = []
    count.value = 0
    blanks.value = 0
    err.value = ''
    return
  }
  const mySeq = ++seq
  try {
    const res = await api.parse(raw)
    if (mySeq !== seq) return
    count.value = res.count
    blanks.value = res.blanks
    items.value = res.items
    err.value = res.count ? '' : '没解析出内容，检查每行是否有英文句子'
  } catch (e) {
    if (mySeq !== seq) return
    err.value = (e as Error).message
  }
}

watch(text, () => {
  window.clearTimeout(timer)
  timer = window.setTimeout(doParse, 240)
})

function pickFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    text.value = String(reader.result ?? '')
    if (!name.value) name.value = file.name.replace(/\.[^.]+$/, '')
    doParse()
  }
  reader.readAsText(file, 'utf-8')
  input.value = ''
}

function useSample() {
  text.value = SAMPLE
  name.value = '示例词书'
  doParse()
}

async function submit() {
  if (!count.value) return
  creating.value = true
  try {
    const res = await api.createBook({ name: name.value.trim(), text: text.value, voice: voice.value })
    toast(`已导入 ${res.count} 题`)
    emit('created', res.id)
  } catch (e) {
    err.value = (e as Error).message
  } finally {
    creating.value = false
  }
}

onMounted(async () => {
  try {
    const v = await api.voices()
    voices.value = v.items
    voice.value = v.default
  } catch {
    voices.value = []
  }
  window.setTimeout(() => {
    const ta = document.querySelector<HTMLTextAreaElement>('#imp-text')
    ta?.focus()
  }, 80)
})
</script>

<template>
  <div class="overlay" @click.self="emit('close')">
    <div class="panel">
      <h3>导入词书</h3>
      <div class="hint">
        一行一题，字段用 <code>Tab</code> / <code>|</code> / <code>,</code> 分隔，顺序不限，自动识别哪列是句子。<br />
        推荐：<code>单词,例句,例句翻译,释义</code>。段落多空用 <code v-pre>{{ 单词 }}</code> 在句中标出来。<br />
        导入后由后端生成微软 Neural 英音，全浏览器音质一致。
      </div>

      <input v-model="name" class="field" placeholder="词书名称（可留空）" autocomplete="off" />

      <textarea
        id="imp-text"
        v-model="text"
        class="field"
        placeholder="authorisation,&quot;You'll need authorisation to keep pets in the apartment.&quot;,你需要获得授权。,授权"
      />

      <div class="row">
        <label class="btn">
          选择文件（.txt / .csv）
          <input type="file" accept=".txt,.csv,.md,text/plain" style="display: none" @change="pickFile" />
        </label>
        <button class="btn" @click="useSample">填入示例</button>
        <select v-if="voices.length" v-model="voice" class="field" style="width: auto; max-width: 230px; margin: 0">
          <option v-for="v in voices" :key="v.id" :value="v.id">{{ v.label }}</option>
        </select>
      </div>

      <div v-if="count" class="msg-ok">识别到 {{ count }} 题 · {{ blanks }} 个空</div>
      <div v-else-if="err" class="msg-err">{{ err }}</div>

      <div class="row" style="margin-top: 14px">
        <div class="grow" />
        <button class="btn" @click="emit('close')">取消</button>
        <button class="btn btn-primary" :disabled="!count || creating" @click="submit">
          {{ creating ? '导入中…' : '导入并开始' }}
        </button>
      </div>

      <div v-if="items.length" class="preview">
        <div v-for="(it, i) in items" :key="i" class="pv">
          <b>{{ i + 1 }}. {{ it.answers.join(' / ') }}</b>
          &nbsp;{{ it.text.slice(0, 96) }}{{ it.text.length > 96 ? '…' : '' }}
          <span class="cn">{{ it.translation || it.meaning }}</span>
        </div>
        <div v-if="count > items.length" class="pv" style="color: #9ca3af">
          …… 还有 {{ count - items.length }} 题
        </div>
      </div>
    </div>
  </div>
</template>
