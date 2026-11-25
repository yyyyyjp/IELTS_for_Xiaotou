# 小头雅思 · AI 参考

给 AI 读的工程文档，两节：接口契约、复盘流水线（导出 → 写 analysis.json → 合并）。
人读的说明在 [README](../README.md)，设计系统原始记录在
[reference/claude-design-system.md](reference/claude-design-system.md)。
下文所有命令都在**仓库根**执行。

## 一、接口契约

给前端用的接口契约。所有接口前缀 `/api`，请求与响应均为 JSON（音频除外）。
线上调试：`http://127.0.0.1:8000/docs`。

约定：

- 时间统一用 **Unix 秒**（不是毫秒）；「今天」「连续天数」按服务器本地时区切日。
- 做题类接口默认 **不下发答案**；只有 `?answers=1` 或交卷/交答案之后才返回。
- 单词听写题的题干用 `{{word}}` 标出要填的位置，答案留在服务端。
- 单用户本地站点，没有鉴权。
- 端点与参数以 `app/server/routers/*.py` 的路由装饰器为准，本文滞后时以代码为准（文末有自检命令）。

---

### 1. 内容包 packs

一篇精读 / 一个词表 = 一个 JSON 文件（`app/server/content/packs/*.json`）。
服务启动时扫描；运行中改文件不用重启，下一次请求会按 mtime 重新加载，也可以调 `/packs/reload`。

#### GET /packs

```json
{
  "items": [{
    "id": "cam18-t3-p3",
    "kind": "reading",              // reading | deck
    "origin": "builtin",            // builtin 不可删；custom 可删
    "meta": {"book": "剑桥雅思 18", "test": "Test 3", "passage": "Passage 3",
             "title": "The case for mixed-ability classes", "durationSec": 1809},
    "counts": {"sentences": 54, "questions": 14, "words": 462, "items": 0},
    // 列表里的 attempt 是子集；完整形状（含 answered/blank/byType）见 §1 的「复盘扩展」
    "attempt": {"source": "idictation", "durationSec": 1809, "score": 5, "total": 14,
                "wrong": 9, "accuracy": 0.3571},
    "hasReview": true, "hasGuide": true,
    "progress": {
      "dictation": {"attempts": 0, "correct": 0},
      "reading": {"answered": 0, "correct": 0},
      "lastAt": null
    }
  }],
  "errors": {}                      // 文件名 -> 解析错误，坏文件不会拖垮整站
}
```

#### GET /packs/{id}?answers=0

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
| `matching` | 匹配题 | `options` | `stem / answer` |

`answer` 可能是字符串，也可能是数组（多空）。

#### 复盘扩展（v2）

阅读不做站内作答时，内容包可以带一次**站外作答**和两份**AI 复盘**。三者都是可选的，
旧包不受影响。字段格式与导入流程见「复盘流水线」。

```jsonc
{
  // 复盘页唯一使用的完整形状，列表接口只给它的子集
  "attempt": {
    "source": "idictation", "submittedAt": "2026-11-20T10:00:00Z",
    "durationSec": 1809, "score": 5, "total": 14,
    "answered": 14, "blank": 0, "wrong": 9, "accuracy": 0.3571,
    "byType": [{"label": "选择题", "correct": 1, "total": 4, "accuracy": 0.25}]
  },
  "questionGroups": [{
    "type": "mcq", "from": 27, "to": 30,
    "items": [{"no": 27, "answer": "B", "mine": "C", "correct": false}]
  }],
  "review": {"title": "…", "sections": [], "diagnoses": [], "actions": []},
  "guide": {"title": "…", "band": [], "rows": [], "terms": []}
}
```

- `GET /packs/{id}`：始终带 `attempt` 与两个布尔值 `hasReview` / `hasGuide`；`review` / `guide`
  两个 key 也始终存在，只是值为 `null`，避免做题时看到答案。
- `GET /packs/{id}?answers=1`：带完整 `review` / `guide`，供复盘页渲染。
- `review` / `guide` 是自由结构，字段缺失时前端逐块降级，不会白屏。骨架见「复盘流水线」第 3 节。

#### 复盘页路由

前端 `/read/:id` 在 `attempt` 存在时默认进入复盘模式：左侧原文、右侧题解（可切总览），
顶部可切「读懂这篇」。没有 `attempt` 的包保持原来的作答模式。`POST /reading/sessions`
与 `POST /reading/sessions/{sid}/submit` 仍然可用。

#### POST /packs/reload

重新扫描目录，返回 `{loaded, ids, errors}`。

#### POST /packs/import

```json
{"name": "听力场景词", "text": "一行一题，字段用逗号/Tab/|/; 分隔", "book": "自定义"}
```

`book` 缺省为 `自定义`，写进 `meta.book`。
解析成 `deck` 内容包落盘。文本里的 `{{word}}` 可显式标空，不标就自动挑词。

#### DELETE /packs/{id}

仅 `origin=custom` 可删；删除即删 JSON 文件。

#### POST /packs/from-export

从 `ielts-practice-export` 导出的单篇数据（`passage / attempt / questions / groups`）与可选 `analysisText`（AI 生成的 JSON，自动剥离 Markdown 代码块）新建或更新内容包。支持 `dryRun=true` 仅做预览与引文/题号校验，`recordHistory=true` 幂等补录历史成绩。

#### POST /packs/export-prompt

根据尚未入库的单篇导出数据（含 `attempt.marks` 高亮与笔记轨迹）生成发给 AI 的标准复盘提示词。

#### POST /packs/{id}/analysis

向站内已有精读内容包注入或更新 AI 复盘（`review / guide / lexicon`），支持 `dryRun=true` 预览校验。

#### GET /packs/{id}/prompt

生成已有精读内容包的 AI 复盘提示词（带 `[p段号, b=段内0起句序]` 标号与作答详情）。

---

### 2. 生词本 vocab

一个词头（`lemma`）只存一条，大小写不敏感；不同篇目遇到同一个词只追加 `contexts`。

#### GET /vocab

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

#### POST /vocab

```json
{"lemma": "deposit", "word": "deposit", "gloss": "押金", "pos": "n.",
 "source": "剑雅18 · T3 · P3",
 "context": {"packId": "cam18-t3-p3", "sentenceId": "p3s1",
             "en": "The landlord kept the deposit.", "zh": "房东留下了押金。"}}
```

返回 `{created, item}`。已存在时只补空字段、追加不重复的 context，不覆盖手工修改。

#### PATCH /vocab/{id}

`{note?, gloss?, tags?, state?}`。

#### DELETE /vocab/{id}

#### GET /vocab/review?limit=20&includeNew=1

到期队列，按 `dueAt` 升序。每条都带 `audioUrl`，可直接播。

#### POST /vocab/{id}/review

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

#### POST /vocab/import

兼容旧 HTML 生词本的 localStorage 导出格式：

```json
{"packId": "cam18-t3-p3",
 "items": [{"word":"streaming","lemma":"streaming","gloss":"分流",
            "context":"The practice of 'streaming'...","zh":"……",
            "para":3,"sentId":"p3s1","src":"剑桥雅思 18 · Test 3 · Passage 3",
            "ts": 1795089000000}]}
```

返回 `{created, merged, skipped, ids}`。

#### GET /vocab/export?format=json|csv

CSV 带 UTF-8 BOM，Excel 直接打开不乱码。

#### GET /vocab/stats

`{total, byState, dueNow, addedToday}`。

---

### 3. 听写 dictation

题目是实时算出来的，不存库。三种模式：

| mode | 听什么 | 看什么 | 答案 |
|---|---|---|---|
| `word` | 单词 | 什么都不给（可给释义提示） | 1 个词 |
| `word_in_context` | 单词 | 例句，目标词挖空 | 1 个词 |
| `sentence` | 整句 | 句子，1–2 个空 | 按空位顺序 |

单词题来源：`source=vocab` 只取生词本；`pack` 用原文词表；`auto`（默认）优先生词本，空则用词表。

#### GET /dictation/items?packId=&mode=word&source=auto&limit=20&voice=

预览，不建会话。`voice` 缺省 `en-GB-SoniaNeural`，未知音色返回 400；`limit` 1–100。

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

#### POST /dictation/sessions

```json
{"packId": "cam18-t3-p3", "mode": "word", "source": "vocab",
 "limit": 20, "itemIds": [], "voice": "en-GB-SoniaNeural"}
```

返回 `{sessionId, packId, mode, voice, startedAt, items[]}`。
题目快照存在会话里，所以中途改内容包不影响本轮到判分。

#### POST /dictation/sessions/{sid}/answer

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

#### POST /dictation/sessions/{sid}/finish

返回 `{total, answered, correct, accuracy, durationSec, wrong[], skipped[]}`。
结束后再答会 409。

#### GET /dictation/sessions/{sid}

断点续做：返回题目 + 已答内容（不含答案）。

#### GET /dictation/sessions?limit=20

历史练习列表。

---

### 4. 精读作答 reading

#### POST /reading/sessions

```json
{"packId": "cam18-t3-p3", "nos": []}
```

`nos` 为空表示全做。返回 `{sessionId, startedAt, nos, pack}`，`pack` 只含所选题目且不含答案。

#### POST /reading/sessions/{sid}/submit

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

#### POST /reading/history

补录历史成绩（例如旧页面上的 5/14）：

```json
{"packId": "cam18-t3-p3", "answers": {"27":"B"}, "durationMs": 1809000, "finishedAt": 1795000000}
```

`finishedAt` 缺省为当前时间；记录会写进 `attempts`，计入趋势图。

#### GET /reading/sessions?limit=20

阅读会话历史，按开始时间倒序，只列作答过或已结束的（`limit` 1–100）：

```json
{"items": [{"sessionId": "...", "packId": "cam18-t3-p3", "mode": "practice",
            "score": 5, "total": 14, "accuracy": 0.3571,
            "startedAt": 1795000000, "endedAt": 1795001809}]}
```

---

### 5. 记录与统计 stats

#### GET /stats/overview

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

#### GET /stats/daily?days=30

补齐空白天，适合直接画柱状图 / 热力图（`days` 最大 365）：

```json
{"from": "2026-10-21", "to": "2026-11-19",
 "items": [{"date": "2026-11-19",
            "dictation": {"attempts": 2, "correct": 1},
            "reading": {"answered": 17, "correct": 8},
            "review": 1, "attempts": 20, "correct": 10, "minutes": 30.1}]}
```

`minutes` 只统计已结束的会话，来自 `sessions` 表。

#### GET /stats/packs

每个内容包的累计正确率、最佳阅读得分、最后练习时间，按最近练习排序。

#### GET /stats/weak-words?limit=20

单词听写错得最多的词，附释义与 `vocabId`，可直接跳去复习。

#### GET /stats/kinds

图例用的固定四项，`{items: [{kind, label}]}`：
`dictation_word` 单词听写、`dictation_sentence` 句子听写、`reading_question` 阅读题、
`vocab_review` 复习。

---

### 6. 发音 media

#### GET /voices

`{default, rate, items: [{id, label, lang}]}`。可用音色见 `tts_service.VOICES`。

#### GET /tts/audio?text=&voice=&rate=

直接返回 mp3，按「文本+音色+语速」哈希缓存。**前端可以把它当普通音频地址用**：
首次请求会等 0.3–1 秒，之后是本地文件。

#### POST /tts

`{text, voice}` → `{url}`。旧接口，保留兼容。

#### POST /tts/batch

`{texts: [...], voice}` → `{items: [{text, ok, url}], total, done, failed, ok}`。
练习前预热，最多 200 条，并发 4。

#### GET /audio/{name}

音频文件，长缓存（`immutable`）。

---

### 7. 离线词典 dict

全站划词/点词查词接口，基于本地 ECDICT SQLite（`app/server/data/ecdict.db`，由 `tools/setup_ecdict.py` 构建）。

#### GET /dict/lookup?q=&packId=

分层查词：若传入 `packId` 且该文章包 `lexicon` 命中，优先返回本文语境释义并由 ECDICT 补全音标/标签/词典全义；否则查本地 ECDICT（含 `exchange` 不规则词根还原、英美拼写转换与短语拆词兜底），并附带当前生词本的 `saved` / `vocabId` 状态。

#### GET /dict/status

返回 `{ready, entries, path, coreReady, coreSize}`。

#### GET /dict/bundle

返回预压缩的核心离线词库（`core_dict.json.gz`，约 6.6 万词 / ~2MB gzip），供前端缓存至 IndexedDB 实现 0ms 离线查词。

---

### 8. 本地优先同步 sync

#### POST /sync

单往返增量双向同步：批量推送本地 `outbox`（`vocab` 集合并集 + LWW + `deletedAt` 墓碑、`sessions` LWW、`attempts` 按 `clientId` 幂等追加），并基于 `cursor` 增量拉取变更。配置环境变量 `XIAOTOU_SYNC_TOKEN` 后启用 Bearer / `X-Sync-Token` 口令校验。

#### GET /sync/export

导出全量学习状态快照 JSON（`vocab / sessions / attempts`）。

#### POST /sync/import

幂等合并恢复全量快照 JSON。

---

### 8. 系统

#### GET /api/health

不需要鉴权的自检接口，用于脚本判断服务是否就绪：

```json
{"ok": true, "ts": 1795450257, "dbVersion": 1,
 "packs": {"loaded": 1, "errors": {}},
 "dict": {"ready": true, "entries": 770611},
 "audio": {"defaultVoice": "en-GB-SoniaNeural", "cached": 11}}
```

---

### 9. 旧接口（冻结）

旧版句子听写页用的 `/books`、`/parse`、`/progress`，行为与之前一致，仅作过渡。
新前端不再调用，`app/server/routers/legacy.py` 已冻结，只修 bug 不加功能：

| 端点 | 行为 |
|---|---|
| `GET /books` | 词书列表，附统计与 `prepare` 进度 |
| `GET /books/{id}` | 单本词书 |
| `GET /books/{id}/questions` | 题目列表 |
| `POST /parse` | 只解析粘贴文本，返回前 20 条 |
| `POST /books` | 从文本建词书 |
| `DELETE /books/{id}` | 删除词书；内置词包返回 400 |
| `POST /books/{id}/reset` | 重置整本进度 |
| `GET /books/{id}/prepare` | 音频预热进度 |
| `POST /progress` | 写单题状态（todo/correct/wrong/skipped） |

---

### 附：内容包 JSON 结构

```jsonc
{
  "schemaVersion": 1,
  "id": "cam18-t3-p3",
  "kind": "reading",
  "origin": "builtin",
  "meta": {"book": "剑桥雅思 18", "test": "Test 3", "passage": "Passage 3",
           "title": "The case for mixed-ability classes", "durationSec": 1809, "order": 0},
  "attempt": {"source": "idictation", "durationSec": 1809, "score": 5, "total": 14,
              "wrong": 9, "accuracy": 0.3571},   // 子集，完整见 §1「复盘扩展」
  "paragraphs": [
    {"no": 1, "sentences": [{"id": "p1s1", "en": "Picture this scene.", "zh": "想象这样一幅场景。"}]}
  ],
  "questionGroups": [
    {"id": "mcq", "type": "mcq", "from": 27, "to": 30, "instruction": "Choose the correct letter.",
     "items": [{"no": 27, "stem": "...", "options": [{"key": "A", "text": "..."}],
                "answer": "B", "mine": "C", "correct": false}]}
  ],
  "lexicon": {"deposit": "n. 押金；存款"},
  "review": {"title": "9 道错题：5 道指错了地方", "sections": [{"kind": "mcq"}]},
  // 这里只示意顶层 key；完整骨架与字段约定见「复盘流水线」第 3–5 节
  "guide": {"title": "它在为「混合能力班级」辩护", "band": [{"n": 1, "f": "样板课", "s": "t"}]}
}
```

`kind=deck` 时用 `items` 而不是 `paragraphs/questionGroups`：

```json
{"word": "deposit", "sentence": "The landlord kept the deposit.",
 "translation": "房东留下了押金。", "meaning": "押金", "answers": ["deposit"]}
```

---

### 附：端点自检

文档滞后时用这两条命令对一下，差集就是漏写或写错的端点（`/api/health` 在 `main.py` 里、
不在 routers，会出现一次前缀差异）：

```bash
grep -rhoE '@router\.(get|post|patch|delete)\("[^"]*"' app/server/routers | sed -E 's/.*\("([^"]*)"/\1/' | sort -u
grep -oE '^#### (GET|POST|PATCH|DELETE) [^ ?]*' docs/AI.md | awk '{print $3}' | sort -u
```

## 二、复盘流水线

站内阅读不做「做题」，只做「读」和「复盘」。做题在 idictation 上完成，导出作答数据，
由 AI 写成复盘，再合并成一个内容包。这样站内留下的是一份可以慢慢看的讲义，而不是又一套题库。

```
idictation 做题
   ↓  ielts-practice-export（JSONL）
passages / questions / groups / attempts
   ↓  AI 写 analysis.json
tools/pack_from_export.py
   ↓
app/server/content/packs/<id>.json
   ↓
/read/<id>   精读对照 · 题解 / 复盘 · 读懂这篇
```

### 1. 导出

导出脚本属于外部 skill `ielts-practice-export`（**本仓库不含** `scripts/`），在能跑 Python 的
环境里执行：

```bash
python3 scripts/export.py --out ./ielts-data --modules reading --books 剑雅18
python3 scripts/validate.py --in ./ielts-data
```

产物里复盘只需要四个文件：`passages.jsonl`、`questions.jsonl`、`groups.jsonl`、
`attempts.jsonl`。脚本默认取该篇**最新一次**提交；要指定某一次，传 `--attempt-id`。

### 2. 写 analysis.json

把该篇的四个 JSONL 对应行（或整个文件，让 AI 自己按 `part_id` 筛）交给 AI，要求它**只输出
一个 JSON 对象**，保存为 `analysis.json`。这个对象的 `review` / `guide` 会原样进入内容包。

怎么分析、诊断写到什么程度，由你自己决定，本仓库不做规定。唯一的硬约束是下一节的结构：
字段名、题型取值、题号范围、`cites` 编号错一个，导入后就读不出来。

### 3. analysis.json 格式

只输出一个 JSON 对象，不要 Markdown 代码块，不要解释。除 `review.title`、`items[].no` 外
都可缺省，缺了只是少一块，不会白屏：

```json
{
  "review": {
    "kicker": "复盘 · 书名 · Test · Passage",
    "title": "一句话标题",
    "lede": "总述文字。",
    "stats": [["5 / 14", "得分", 1], ["30:09", "用时", 0], ["9", "错题数", 1]],
    "bars": [["选择 27–30", 25, "1/4"], ["摘要 31–35", 60, "3/5"]],
    "sections": [
      {
        "kind": "mcq",
        "title": "选择题 27–30",
        "from": 27,
        "to": 30,
        "diag": "本组共性，可空",
        "items": [
          {
            "no": 27,
            "label": "why-wrong",
            "tag": "选择题",
            "diag": "诊断文字",
            "chain": "正确链条",
            "cites": [{"p": 1, "b": [3, 5, 6]}]
          }
        ]
      },
      {
        "kind": "summary",
        "title": "摘要填空 31–35",
        "from": 31,
        "to": 35,
        "diag": "本组共性",
        "note": "本组补充，可空",
        "cites": [{"p": 7, "b": [2, 3]}],
        "rows": [
          {
            "no": 32,
            "minePhrase": "wrong classes",
            "corPhrase": "bottom sets",
            "src": "原文依据短语",
            "diag": "诊断文字",
            "cites": [{"p": 7, "b": [2]}]
          }
        ]
      },
      {
        "kind": "ynng",
        "title": "判断题 36–40",
        "from": 36,
        "to": 40,
        "diag": "本组共性",
        "items": [
          {"no": 37, "label": "why-wrong", "diag": "诊断文字", "cites": [{"p": 9, "b": [1, 2]}]}
        ]
      },
      {"kind": "tfng", "title": "判断题 36–40", "from": 36, "to": 40, "diag": "本组共性",
       "items": [{"no": 36, "label": "why-wrong", "diag": "诊断文字", "cites": [{"p": 6, "b": [4, 5]}]}]},
      {"kind": "gap", "title": "填空题 21–26", "from": 21, "to": 26, "diag": "本组共性",
       "items": [{"no": 21, "label": "why-wrong", "diag": "诊断文字", "cites": [{"p": 2, "b": [1]}]}]},
      {"kind": "matching", "title": "匹配题 14–19", "from": 14, "to": 19, "diag": "本组共性",
       "items": [{"no": 14, "label": "why-wrong", "diag": "诊断文字", "cites": [{"p": 4, "b": [0]}]}]}
    ],
    "diagnoses": [{"n": "病灶 01", "t": "对象漂移", "p": "……"}],
    "actions": ["可执行动作……"],
    "end": "收尾一段。"
  },
  "guide": {
    "kicker": "读懂 · 书名 · Test · Passage",
    "title": "这篇文章在干什么",
    "lede": "总述文字。",
    "thesis": "一句话主旨。",
    "structureTitle": "N 段里，有 M 段不是作者在说话",
    "band": [{"n": 1, "f": "样板课", "s": "t"}],
    "legend": [{"s": "t", "text": "作者本人（6 段）"}],
    "argument": {
      "negativeTitle": "反方",
      "negative": [{"t": "反问　", "p": "（第 2 段）……"}],
      "positiveTitle": "作者",
      "positive": [{"t": "第一刀 · 实证　", "p": "（第 7 段）……"}],
      "punch": "论证落点。"
    },
    "rows": [{"n": 1, "w": "作者", "s": "t", "d": "这一段在干什么。"}],
    "terms": [{"k": "ZPD", "en": "zone of proximal development", "d": "……"}],
    "echo": {"neg": "开头的说法", "pos": "结尾的回应", "note": "为什么这是呼应"},
    "why": [{"t": "第 5 段：整段没有归属标记", "p": "……"}],
    "side": "顺带的建议，可空。",
    "end": "收尾一段。"
  }
}
```

约定：

- `kind` 只有六个值，决定右栏怎么渲染：

  | kind | 渲染 | 内容放哪 |
  |---|---|---|
  | `mcq` | 选择题卡（选项 + 对错标记） | `items[]` |
  | `summary` | 摘要正文 + 逐空行 | `rows[]`（每空一行），组级 `cites` 兜底 |
  | `ynng` | Y/N/NG 题卡 | `items[]` |
  | `tfng` | T/F/NG 题卡 | `items[]` |
  | `gap` | 普通填空题卡 | `items[]` |
  | `matching` | 匹配题（先列选项池，再逐题） | `items[]` |

- `summary` 之外都用 `items[]`；`summary` 的每一空写进 `rows[]`，`no` 必须与题号一致。
- `cites` 两种写法都接受：`{"p": 1, "b": [3, 5]}`（段号 1 起、段内句序 0 起），或
  `"p1s4"`（句序从 1 起）。构建时 `clean_cites` 会把后者转成前者，优先写对象形式。
- `stats` / `bars` 可以省略：**前端**（`ReviewOverview.vue`）会按 `attempt` 与 `byType` 兜底，
  构建脚本只负责透传。
- `band[].s` 只能是 `t`（作者）、`a`（反方/假设）、`g`（中立定义）。
- `sections[].title` 可省略，前端会按 `kind` 和 `from/to` 生成标题。

### 4. 合并

```bat
app\server\.venv\Scripts\python.exe tools\pack_from_export.py ^
  --export .\ielts-data ^
  --book 剑雅18 --test "Test 4" --part "Passage 1" ^
  --analysis .\analysis\cam18-t4-p1.json ^
  --post http://127.0.0.1:8000
```

- `--id` 省略时按 `cam18-t4-p1` 生成。
- `--post` 会把这次作答补录进 `app.db`，记录页和热力图才会算上；不传就只写内容包。
- 同 id 的旧包如果存在，词表默认沿用（`--no-keep-lexicon` 可关闭）。
- 词表也可以在 `analysis.json` 的 `lexicon` 里补：`{"word": "v. 释义"}`。

服务运行中不需要重启，下一次请求会按文件 mtime 重新加载；也可以用 `POST /api/packs/reload`。

### 5. 字段规则

骨架与题型取值见上一节，这里只列字段约定。

| 字段 | 说明 |
|---|---|
| `review.title` | 复盘页标题，唯一必填的顶层字段 |
| `review.kicker` / `lede` | 抬头与总述，可空 |
| `review.stats` | `[值, 标签, 是否标红]`；不给就由前端按 `attempt` 生成 |
| `review.bars` | `[标签, 百分比 0–100, 右侧文字]`；不给就由前端按 `byType` 生成 |
| `sections[].kind` | `mcq` / `summary` / `ynng` / `tfng` / `gap` / `matching`，决定渲染方式 |
| `sections[].from/to` | 题号范围，用来把 section 对到 questionGroup |
| `sections[].items[]` | 除 `summary` 外用；`no` 必须与 `questionGroups` 里的 `no` 一致 |
| `sections[].rows[]` | `summary` 专用：每空的 `minePhrase` / `corPhrase` / `src` / `diag` |
| `rows[].cites` | 点这个空位时显示答案句；缺省时错误空回退到组级 `cites` |
| `label` | `why-right` / `why-wrong`，前端翻译；也可以直接写中文，原样显示 |
| `cites` | `{"p": 1, "b": [3, 5]}`，或 `"p1s4"` 简写；构建期统一成前者 |
| `band[].s` | `t` 作者 / `a` 反方或假设 / `g` 中立定义 |
| `echo` | 首尾对照；`neg` 和 `pos` 都空就不渲染这一节 |
| `diagnoses` / `actions` | 病灶与动作，总览页用 |

除 `review.title`、`sections[].items[].no` 外，其余字段都可以缺。缺了只是少一块，不会白屏。

#### 引用怎么数

导出里的 `passages.sentences[].i` 是**全文序号**（0 起），而复盘里的 `b` 是**段内序号**
（0 起），两者不同。换算时按 `sentences[].paragraph` 分组后再数。举例：A 段第 4 句是
全文第 4 句，`{"p": 1, "b": [3]}`；B 段第 1 句在全文里可能是第 9 句，仍写 `{"p": 2, "b": [0]}`。

也接受字符串简写 `"p3s5"`（段 3 第 5 句，句序从 1 起），`tools/review_pack.py::clean_cites`
会在构建时转成 `{"p": 3, "b": [4]}`。

#### 高亮行为

点某道题（题卡）或某个摘要空位时，左栏才把那道题的答案句点亮：peach 色块（`--hl-answer`）
+ 段落序号左侧一条 clay 竖线（`--hl-line`），其余句子保持纸面原样。点「原文出处」或摘要空位
会滚到对应答案句；摘要空位被点时，右栏对应行展开「答案句」块（英文 + 译文）。

### 6. 旧 HTML 页面

以前那种单文件精读页（`const DATA` + `REV` + `MEANS`）也能直接转：

```bat
app\server\.venv\Scripts\python.exe tools\pack_from_html.py "剑雅18-Test3-Passage3-精读与生词本.html" --id cam18-t3-p3 --dump-analysis app\server\content\imports\cam18-t3-p3-analysis.json
```

它会把 `mine`、`REV`、`MEANS` 一起带进来；`--analysis` 可以用外部 JSON 覆盖页面内嵌的
复盘。`cam18-t3-p3` 就是这样生成的。

### 7. 排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 页面只有原文，没有复盘 | `review` 为空 | 检查 analysis 里的 `review.sections`；重跑合并 |
| 复盘 tab 不出现 | 没有 `attempt` | 这篇在导出里没有作答记录；先确认 `attempt_id` |
| 题号对不上 | section 的 `from/to` 与 questionGroup 不一致 | `--dump-analysis` 后对照 pack 的题号 |
| 引文跳不过去 | `p/b` 数错 | `p` 从 1 起、`b` 从 0 起；或改用 `"p1s4"` |
| 词表是空的 | 导出不带词表 | 用 `--lexicon`、`analysis.lexicon`，或沿用旧包 |
| 记录页没有这次成绩 | 没传 `--post` | 重新跑并加 `--post http://127.0.0.1:8000` |
| 统计条/进度条不显示 | 没有 `attempt` 或 `byType` | 前端兜底也依赖它们；补 `attempt` 或手写 `stats`/`bars` |
