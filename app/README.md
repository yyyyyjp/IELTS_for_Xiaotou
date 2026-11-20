# Tifo · 雅思备考记录

精读、生词本、听写、作答记录，共用一套后端。前端在 `web/`，构建产物由后端直接托管。
接口契约见 **[API.md](API.md)**。

## 快速开始

```bat
双击 app\start.bat
```

- 服务：http://127.0.0.1:8000
- 接口文档：http://127.0.0.1:8000/docs

`start.bat` 只在**缺少依赖或缺少构建产物**时才安装/构建，正常启动约 2 秒。
已构建过就不需要 Node，也不需要联网。

打不开时的排查顺序：

1. 一定是访问 **http://127.0.0.1:8000**，不要双击 `web/index.html`（那是源码入口，直接打开必然白屏）。
2. 窗口一闪就关：右键 `start.bat` → 编辑，确认文件第一行是 `@echo off`，没有被记事本存成别的编码；或从命令行手动运行看报错。
3. 提示 8000 端口被占用：脚本会检测到并直接开浏览器，无需重复启动。
4. 页面打开但空白：`web/dist/index.html` 可能缺失，删掉 `web/dist` 后重新双击 `start.bat`（这一步需要 Node）。

开发模式（前端热更新）：

```bat
双击 app\dev.bat
```

前端目录与代码约定见 **[web/README.md](web/README.md)**：主题 token、中英字典、图标各自独立成文件，
页面只做编排，接口统一走 `src/api.ts`。

## 为什么这样拆

```
app/server/
├─ main.py              应用装配：路由、静态托管、启动扫描
├─ config.py            路径与参数（环境变量可覆盖）
├─ db.py                SQLite 连接 + 版本化迁移
├─ content/
│  ├─ loader.py         内容包读取、校验、缓存
│  └─ packs/*.json      教材内容（原文/译文/题目/词表）
├─ services/
│  ├─ grading.py        判分归一化
│  ├─ srs.py            间隔复习调度
│  └─ dictation.py      听写题目生成（挖空、题型）
├─ routers/
│  ├─ packs.py          内容包
│  ├─ vocab.py          生词本 + 复习
│  ├─ reading.py        精读作答
│  ├─ dictation.py      听写练习
│  ├─ stats.py          备考记录
│  ├─ media.py          TTS 与音频
│  └─ legacy.py         旧版接口（冻结，待删）
└─ data/
   ├─ app.db            只存记录：作答、会话、生词本、复习状态
   └─ audio/*.mp3       按「文本+音色+语速」哈希缓存
```

**内容和记录分开**，是这套结构唯一的硬约束：

- 教材是 JSON 文件，随 git 版本化。加一篇 = 加一个文件，不改代码、不写迁移、不怕删库。
- 数据库只有事件流：每次作答一条 `attempts`。所以能回答「哪天练了什么、哪个词错了几次」，
  而不用在题目表上反复覆盖 `status`。
- 题目按需生成：同一篇原文能出单词题、听词填句、整句听写，加题型只改
  `services/dictation.py`。

代价也说清楚：

- 内容包全量读进内存。几十篇、几百篇没问题；上千篇或要全文检索时，再换 SQLite FTS。
- 统计每次现算。个人数据量下毫秒级；真到百万条再考虑汇总表。
- 单用户、无鉴权。要多人用，得先加 `user_id` 与登录——这是唯一需要动表结构的地方。

## 加一篇新的精读

你已有的单文件精读页（内嵌 `const DATA` / `const DICT`）可以直接转：

```bat
app\server\.venv\Scripts\python.exe tools\pack_from_html.py "剑雅18-Test3-Passage3-精读与生词本.html" --id cam18-t3-p3
```

产出 `server/content/packs/cam18-t3-p3.json`，服务端下次启动或调 `POST /api/packs/reload` 即生效。

想把旧页面上的历史成绩一起带过来：

```bat
:: 先启动服务，再执行
app\server\.venv\Scripts\python.exe tools\pack_from_html.py "你的精读页.html" --id cam18-t3-p3 --history --post http://127.0.0.1:8000
```

手写内容包也可以，格式见 API.md 末尾。`lexicon` 的值支持简写：
`{"deposit": "n. 押金；存款"}`，词性会自动拆出来。

旧页面生词本里攒的词，用「复制 JSON」导出后导入：

```bat
app\server\.venv\Scripts\python.exe tools\import_vocab.py vocab.json --pack cam18-t3-p3 --post http://127.0.0.1:8000
```

## 一次练习的完整流程

1. `GET /api/packs/cam18-t3-p3` 拿原文、题目、词表（不含答案）。
2. 点词 → `POST /api/vocab` 收进生词本。
3. `POST /api/dictation/sessions` 开始单词听写；每题 `answer`，最后 `finish`。
4. `POST /api/reading/sessions` 做阅读；`submit` 交卷，返回逐题对错与正确答案。
5. `GET /api/stats/overview`、`/api/stats/daily?days=30` 看记录。
6. 每天清一次 `GET /api/vocab/review`，用 `POST /api/vocab/{id}/review` 打分。

## 测试

```bat
cd app\server
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest tests -q
```

44 个用例，覆盖内容包加载、判分归一化、SRS 调度、听写三种题型、
精读判分、生词本去重与导入导出、统计口径。测试用临时目录，不碰真实 `data/app.db`。

## 发音

`edge-tts`（微软 Edge 的神经音色，免费无需 Key），默认 `en-GB-SoniaNeural`、语速 `-5%`。

- 同一句只生成一次，文件名是内容哈希，改词就自动换新文件。
- 生成失败返回 503，前端可回退 `speechSynthesis`。
- 想换默认音色：改 `config.py`，或在请求里传 `voice`（可选值见 `GET /api/voices`）。

## 数据与备份

| 要备份的 | 路径 |
|---|---|
| 学习记录 | `app/server/data/app.db`（连同 `-wal`/`-shm`） |
| 音频缓存 | `app/server/data/audio/`（可重建，非必需） |
| 教材 | `app/server/content/packs/`（建议入 git） |

音频缓存按内容哈希命名，删词书不会自动删文件；长期可清理未被引用的 mp3。

## 已知边界

- **词形还原靠前端**。生词本以 `lemma` 去重，但后端不跑词形还原；
  旧页面的 `lookup()` 做了 `-s/-ed/-ing` 回退，新前端需要照做，或直接存原形。
- **挖空是启发式的**。优先取生词本里的词，其次最长实词，会跳过句中大写词（人名地名）
  和数字；没有词性标注，偶尔会挖到副词（如 `simply`）。
- **判分不认拼写近似**。大小写、标点、连字符、撇号写法都宽松处理，
  但 `authorisation` / `authorization` 算错——这是有意为之。
- **edge-tts 调的是非官方接口**，接口变动时降级为浏览器合成，功能不中断。
- **无鉴权、无多用户**。只适合本机或内网单人使用；公网部署前请加认证。
