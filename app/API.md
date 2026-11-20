# Tifo API 参考（v2）

给前端用的接口契约。所有接口前缀 `/api`，请求与响应均为 JSON（音频除外）。
线上调试：`http://127.0.0.1:8000/docs`。

约定：

- 时间统一用 **Unix 秒**（不是毫秒）；「今天」「连续天数」按服务器本地时区切日。
- 做题类接口默认 **不下发答案**；只有 `?answers=1` 或交卷/交答案之后才返回。
- 单词听写题的题干用 `{{word}}` 标出要填的位置，答案留在服务端。
- 单用户本地站点，没有鉴权。

---

## 1. 内容包 packs

一篇精读 / 一个词表 = 一个 JSON 文件（`server/content/packs/*.json`）。
服务启动时扫描，改动文件后调 `/packs/reload` 或重启即可，不用迁移数据库。

### GET /packs

```json
{
  "items": [{
    "id": "cam18-t3-p3",
    "kind": "reading",              // reading | deck
    "origin": "builtin",            // builtin 不可删；custom 可删
    "meta": {"book": "剑桥雅思 18", "test": "Test 3", "passage": "Passage 3",
             "title": "The case for mixed-ability classes", "durationSec": 1809},
    "counts": {"sentences": 54, "questions": 14, "words": 462, "items": 0},
    "progress": {
      "dictation": {"attempts": 0, "correct": 0},
      "reading": {"answered": 0, "correct": 0},
      "lastAt": null
    }
  }],
  "errors": {}                      // 文件名 -> 解析错误，坏文件不会拖垮整站
}
```

### GET /packs/{id}?answers=0

返回 `meta / counts / paragraphs / questionGroups / lexicon / items / progress`。
`paragraphs[].sentences[]` 结构：`{id, en, zh}`，`id` 形如 `p3s1`，听写与生词上下文都用它定位。

题型 `type`：

| type | 用途 | 组字段 | 每题字段 |
|---|---|---|---|
| `mcq` | 单选 | `options` | `stem / options / answer` |
| `summary` | 摘要选词填空 | `text`（含 `{{31}}`）、`options` | `no / answer` |
| `ynng` | Y/N/NG | — | `stem / answer` |
| `tfng` | T/F/NG | — | `stem / answer` |
| `gap` | 普通填空 | — | `stem / answer` |

`answer` 可能是字符串，也可能是数组（多空）。

### POST /packs/reload

重新扫描目录，返回 `{loaded, ids, errors}`。

### POST /packs/import

```json
{"name": "听力场景词", "text": "一行一题，字段用逗号/Tab/|/; 分隔"}
```

解析成 `deck` 内容包落盘。文本里的 `{{word}}` 可显式标空，不标就自动挑词。

### DELETE /packs/{id}

仅 `origin=custom` 可删；删除即删 JSON 文件。

---

## 2. 生词本 vocab

一个词头（`lemma`）只存一条，大小写不敏感；不同篇目遇到同一个词只追加 `contexts`。

### GET /vocab

| 参数 | 说明 |
|---|---|
| `q` | 模糊匹配单词 / 释义 / 例句 |
| `packId` | 只看来自某篇目的词 |
| `state` | `new / learning / review / suspended` |
| `due=1` | 只看到期 |
| `limit` / `offset` | 默认 200，最大 1000 |

返回 `{total, items[]}`，条目：

```json
{
  "id": 1, "lemma": "deposit", "word": "deposit",
  "gloss": "押金；存款", "pos": "n.", "phonetic": "", "note": "",
  "tags": [], "contexts": [{"packId":"cam18-t3-p3","sentenceId":"p3s1",
                            "en":"...", "zh":"...", "para":3}],
  "source": "剑桥雅思 18 · Test 3 · Passage 3",
  "state": "new", "dueAt": 1795000000, "due": true,
  "intervalDays": 0, "ease": 2.4, "reps": 0, "lapses": 0,
  "lastReviewedAt": 0, "createdAt": 1795000000, "updatedAt": 1795000000,
  "audioUrl": "/api/audio/xxx.mp3", "audioCached": true
}
```

### POST /vocab

```json
{"lemma": "deposit", "word": "deposit", "gloss": "押金", "pos": "n.",
 "source": "剑雅18 · T3 · P3",
 "context": {"packId": "cam18-t3-p3", "sentenceId": "p3s1",
             "en": "The landlord kept the deposit.", "zh": "房东留下了押金。"}}
```

返回 `{created, item}`。已存在时只补空字段、追加不重复的 context，不覆盖手工修改。

### PATCH /vocab/{id}

`{note?, gloss?, tags?, state?}`。

### DELETE /vocab/{id}

### GET /vocab/review?limit=20&includeNew=1

到期队列，按 `dueAt` 升序。每条都带 `audioUrl`，可直接播。

### POST /vocab/{id}/review

```json
{"grade": "good", "durationMs": 3200}
```

`grade`：`again / hard / good / easy`。返回 `{item, nextDueAt, intervalDays, state}`。

调度规则（`services/srs.py`）：

| 档位 | 间隔 | ease |
|---|---|---|
| again | 10 分钟后重来，`state=learning` | −0.2 |
| hard | `max(1, 上次×1.2)` 天 | −0.05 |
| good | 第 1 次 1 天，第 2 次 3 天，之后 `上次×ease` | 不变 |
| easy | 首次 3 天，之后 `上次×ease×1.3` | +0.1 |

间隔上限 365 天，ease 限制在 1.3–3.0。

### POST /vocab/import

兼容旧 HTML 生词本的 localStorage 导出格式：

```json
{"packId": "cam18-t3-p3",
 "items": [{"word":"streaming","lemma":"streaming","gloss":"分流",
            "context":"The practice of 'streaming'...","zh":"……",
            "para":3,"sentId":"p3s1","src":"剑桥雅思 18 · Test 3 · Passage 3",
            "ts": 1795089000000}]}
```

返回 `{created, merged, skipped, ids}`。

### GET /vocab/export?format=json|csv

CSV 带 UTF-8 BOM，Excel 直接打开不乱码。

### GET /vocab/stats

`{total, byState, dueNow, addedToday}`。

---

## 3. 听写 dictation

题目是实时算出来的，不存库。三种模式：

| mode | 听什么 | 看什么 | 答案 |
|---|---|---|---|
| `word` | 单词 | 什么都不给（可给释义提示） | 1 个词 |
| `word_in_context` | 单词 | 例句，目标词挖空 | 1 个词 |
| `sentence` | 整句 | 句子，1–2 个空 | 按空位顺序 |

单词题来源：`source=vocab` 只取生词本；`pack` 用原文词表；`auto`（默认）优先生词本，空则用词表。

### GET /dictation/items?packId=&mode=word&source=auto&limit=20

预览，不建会话：

```json
{"count": 1, "items": [{
  "id": "cam18-t3-p3:w:deposit", "packId": "cam18-t3-p3", "type": "word",
  "audioText": "deposit",
  "audioUrl": "/api/audio/xxx.mp3",   // 未缓存时是 /api/tts/audio?text=...
  "audioCached": true,
  "text": "",
  "blankCount": 1,
  "blankLengths": [7],
  "hint": {"gloss": "押金", "pos": "n.",
           "context": "The landlord kept the {{}}.",
           "contextZh": "房东留下了押金。"},
  "source": "vocab"
}]}
```

`text` 与 `hint.context` 里的空位统一写作 `{{}}`，不含答案；`blankLengths` 给前端定输入框宽度。

句子题 `text` 形如 `"It's an English {{}} lesson..."`，几个空就有几个 `{{}}`。

### POST /dictation/sessions

```json
{"packId": "cam18-t3-p3", "mode": "word", "source": "vocab",
 "limit": 20, "itemIds": [], "voice": "en-GB-SoniaNeural"}
```

返回 `{sessionId, packId, mode, voice, startedAt, items[]}`。
题目快照存在会话里，所以中途改内容包不影响本轮到判分。

### POST /dictation/sessions/{sid}/answer

```json
{"itemId": "cam18-t3-p3:w:deposit", "input": "deposit", "replays": 1, "durationMs": 2500}
```

`input` 可以是字符串或数组（多空）。返回：

```json
{"itemId": "...", "correct": true, "parts": [true],
 "expected": ["deposit"], "firstTime": true}
```

同一题重复作答：每次都会写一条 `attempts`，但会话统计按 **最终答案** 计。

`firstTime=false` 表示这题之前答过。

### POST /dictation/sessions/{sid}/finish

返回 `{total, answered, correct, accuracy, durationSec, wrong[], skipped[]}`。
结束后再答会 409。

### GET /dictation/sessions/{sid}

断点续做：返回题目 + 已答内容（不含答案）。

### GET /dictation/sessions?limit=20

历史练习列表。

---

## 4. 精读作答 reading

### POST /reading/sessions

```json
{"packId": "cam18-t3-p3", "nos": []}
```

`nos` 为空表示全做。返回 `{sessionId, startedAt, nos, pack}`，`pack` 只含所选题目且不含答案。

### POST /reading/sessions/{sid}/submit

```json
{"answers": {"27": "B", "31": "H"}, "durationMs": 1500000}
```

未作答按错处理。返回：

```json
{"sessionId": "...", "durationMs": 1500000,
 "score": 5, "total": 14, "accuracy": 0.3571,
 "items": [{"no": 27, "group": "mcq", "mine": "C", "answer": ["B"], "correct": false}],
 "pack": { "...": "带答案的内容包，用于复盘" }}
```

重复交卷 409。

### POST /reading/history

补录历史成绩（例如旧页面上的 5/14）：

```json
{"packId": "cam18-t3-p3", "answers": {"27":"B"}, "durationMs": 1809000, "finishedAt": 1795000000}
```

`finishedAt` 缺省为当前时间；记录会写进 `attempts`，计入趋势图。

---

## 5. 记录与统计 stats

### GET /stats/overview

```json
{
  "date": "2026-11-19",
  "today": {"attempts": 20, "correct": 10, "accuracy": 0.5, "minutes": 30.1,
            "dictation": {"attempts": 2, "correct": 1},
            "reading": {"answered": 17, "correct": 8},
            "review": 1},
  "streak": {"current": 1, "longest": 1, "studyDays": 1},
  "totals": {"words": 1, "dueNow": 0, "attempts": 20, "correct": 10,
             "dictationAttempts": 2, "readingQuestions": 17, "packs": 1},
  "lastStudyAt": 1795000000
}
```

### GET /stats/daily?days=30

补齐空白天，适合直接画柱状图 / 热力图（`days` 最大 365）：

```json
{"from": "2026-10-21", "to": "2026-11-19",
 "items": [{"date": "2026-11-19",
            "dictation": {"attempts": 2, "correct": 1},
            "reading": {"answered": 17, "correct": 8},
            "review": 1, "attempts": 20, "correct": 10, "minutes": 30.1}]}
```

`minutes` 只统计已结束的会话，来自 `sessions` 表。

### GET /stats/packs

每个内容包的累计正确率、最佳阅读得分、最后练习时间，按最近练习排序。

### GET /stats/weak-words?limit=20

单词听写错得最多的词，附释义与 `vocabId`，可直接跳去复习。

---

## 6. 发音 media

### GET /voices

`{default, rate, items: [{id, label, lang}]}`。可用音色见 `tts_service.VOICES`。

### GET /tts/audio?text=&voice=&rate=

直接返回 mp3，按「文本+音色+语速」哈希缓存。**前端可以把它当普通音频地址用**：
首次请求会等 0.3–1 秒，之后是本地文件。

### POST /tts

`{text, voice}` → `{url}`。旧接口，保留兼容。

### POST /tts/batch

`{texts: [...], voice}` → `{items: [{text, ok, url}], total, done, failed, ok}`。
练习前预热，最多 200 条，并发 4。

### GET /audio/{name}

音频文件，长缓存（`immutable`）。

---

## 7. 旧接口（冻结）

`/books`、`/books/{id}/questions`、`/parse`、`/progress` 等是旧版句子听写页的接口，
行为与之前一致，仅作过渡。新前端上线后连同 `routers/legacy.py` 一起删除。

---

## 附：内容包 JSON 结构

```jsonc
{
  "schemaVersion": 1,
  "id": "cam18-t3-p3",
  "kind": "reading",
  "origin": "builtin",
  "meta": {"book": "剑桥雅思 18", "test": "Test 3", "passage": "Passage 3",
           "title": "The case for mixed-ability classes", "durationSec": 1809, "order": 0},
  "paragraphs": [
    {"no": 1, "sentences": [{"id": "p1s1", "en": "Picture this scene.", "zh": "想象这样一幅场景。"}]}
  ],
  "questionGroups": [
    {"id": "mcq", "type": "mcq", "from": 27, "to": 30, "instruction": "Choose the correct letter.",
     "items": [{"no": 27, "stem": "...", "options": [{"key": "A", "text": "..."}], "answer": "B"}]}
  ],
  "lexicon": {"deposit": "n. 押金；存款"}
}
```

`kind=deck` 时用 `items` 而不是 `paragraphs/questionGroups`：

```json
{"word": "deposit", "sentence": "The landlord kept the deposit.",
 "translation": "房东留下了押金。", "meaning": "押金", "answers": ["deposit"]}
```
