# Tifo · 雅思句子听写

导入自己的词书（CSV/TXT），听句子、填句中的空。发音走微软 Neural 英音，音频落盘缓存，全浏览器音质一致。

## 快速开始

```bat
双击 app\start.bat
```

首次运行会自动建虚拟环境、装依赖、构建前端，然后打开 http://127.0.0.1:8000

开发模式（前端热更新）：

```bat
双击 app\dev.bat
```

前端 http://127.0.0.1:5173 ・ 接口文档 http://127.0.0.1:8000/docs

## 目录

```
app/
├─ server/                 FastAPI 后端
│  ├─ main.py              路由（词书/题目/发音/进度）
│  ├─ db.py                SQLite 建表与存取
│  ├─ parser.py            词书文本解析
│  ├─ tts_service.py       edge-tts 生成与缓存
│  └─ data/
│     ├─ app.db            数据库（词书、题目、进度）
│     └─ audio/*.mp3       音频缓存，按 文本+音色+语速 哈希命名
└─ web/                    Vue 3 + TypeScript + Vite
   └─ src/
      ├─ api.ts            后端接口封装
      ├─ audio.ts         播放器 + 切分填空 + 音色打分
      ├─ views/LobbyView.vue
      ├─ views/StageView.vue
      └─ components/       ImportDialog / VocabSheet / ExplainDialog
```

## 导入格式

一行一题，字段分隔符支持 `,` `Tab` `|` `;`，顺序不限，自动判断哪列是句子。

```csv
单词,例句,例句翻译,释义
authorisation,"You'll need authorisation to keep pets in the apartment.",你需要获得授权。,授权
```

段落多空，用 `{{ }}` 或 `[[ ]]` 标出要挖的词，一行可多个空：

```
The landlord said the {{deposit}} is {{refundable}} if we {{cancel}} two weeks ahead.,押金可退。
```

只有英文句子也能用，会自动挑一个实词挖空（跳过 the/is/of 这类功能词）。

## 关键设计

**发音：为什么用后端生成而不是浏览器 speechSynthesis**

`SpeechSynthesisUtterance` 只暴露 `text/lang/voice/rate/pitch/volume`，不支持 SSML，也无法逐词控制重读——重音位置由引擎内部决定。改用 edge-tts（微软 Edge 的神经网络音色，免费无 Key）在服务端生成 mp3：

- `en-GB-SoniaNeural` 自带韵律模型，句重音、弱读、连读是自动生成的，接近雅思听感
- 同一句只生成一次，之后 `<audio>` 直接播，0 延迟
- 音质不随浏览器变化
- 生成失败时前端回退 `speechSynthesis`

导入后后台并发（4 路）预生成，大厅显示进度；播放时若还没生成则按需现场合成。

**多空填空**

`buildSegments(text, answers)` 按出现顺序做整词定位，切成「文本 / 空」序列。支持一句一空（背单词）和一段多空（快速过）。

**雅思模式**

每句最多播 2 遍，播完不再给听，回退到已做过的题也不重置计数。可随时切「宽松」模式。这个约束比音色更能提高难度——雅思的难点是只听一遍、无字幕。

## 已知边界

- **逐词重读控制不了**。Web Speech API 没有 SSML；要精确控制 `emphasis`/`break` 需要 Azure/Google Cloud TTS 的 SSML 接口（要 Key，且必须预生成）。
- edge-tts 调的是微软 Edge 朗读接口，非官方 SDK。若接口变动，降级为浏览器合成，功能不中断。
- 音频缓存按内容哈希，删词书不会删音频（可被其他书复用）。长期使用可清理 `data/audio` 里未被引用的文件。

## 常见操作

| 场景 | 做法 |
|---|---|
| 重新生成某本书的音频 | 删掉 `data/audio` 对应文件后重启服务 |
| 备份 | 复制 `server/data/` 整个目录 |
| 清空所有进度 | 舞台右侧「词表」→「重置本书进度」 |
| 换默认音色 | `tts_service.py` 的 `DEFAULT_VOICE`，或在导入时逐个词书选择 |
