# Tifo · 雅思备考记录

精读、生词本、听写、作答记录，共用一套后端。前端在 `app/web/`，构建产物由后端直接托管。
接口契约、复盘流程与写作提示词都在 [docs/AI.md](docs/AI.md)（那份是给 AI 的，人看本文即可）。

- [快速开始](#快速开始)
- [目录结构](#目录结构)
- [架构：内容与记录分开](#架构内容与记录分开)
- [一次练习的完整流程](#一次练习的完整流程)
- [阅读：复盘为主，站内不重做](#阅读复盘为主站内不重做)
- [加内容](#加内容)
- [测试](#测试)
- [发音](#发音)
- [数据与备份](#数据与备份)
- [已知边界](#已知边界)
- [前端代码约定](#前端代码约定)
- [加页面](#加页面)
- [文档](#文档)
- [设计规范](#设计规范)

## 快速开始

```bat
双击 app\start.bat
```

- 服务：http://127.0.0.1:8000
- 接口文档：http://127.0.0.1:8000/docs

`start.bat` 只在**缺少依赖或缺少构建产物**时才安装/构建，正常启动约 2 秒。
已构建过就不需要 Node，也不需要联网。

打不开时的排查顺序：

1. 一定是访问 **http://127.0.0.1:8000**，不要双击 `app/web/index.html`（那是源码入口，直接打开必然白屏）。
2. 窗口一闪就关：右键 `app\start.bat` → 编辑，确认文件第一行是 `@echo off`，没有被记事本存成别的编码；或从命令行手动运行看报错。
3. 提示 8000 端口被占用：脚本会检测到并直接开浏览器，无需重复启动。
4. 页面打开但空白：`app/web/dist/index.html` 可能缺失，删掉 `app/web/dist` 后重新双击 `start.bat`（这一步需要 Node）。

开发模式（前端热更新，两个窗口）：

```bat
双击 app\dev.bat
```

## 目录结构

```
tifo/
├─ app/
│  ├─ start.bat          一键启动：检查依赖与 dist，缺什么装什么
│  ├─ dev.bat            开发模式：uvicorn --reload + vite
│  ├─ server/            FastAPI 后端（见下）
│  └─ web/               前端源码 + 构建产物（见「前端代码约定」）
├─ tools/                内容导入脚本（pack_from_export / pack_from_html / import_vocab）
├─ docs/                 AI.md（接口/复盘/提示词）与 reference/（设计系统原文）
├─ prototype/            早期静态原型，仅存档
└─ 剑雅18-Test3-Passage3-精读与生词本.html   旧的单文件精读页，可转成内容包
```

`app/server/`：

```
server/
├─ main.py              应用装配：路由、静态托管、启动扫描
├─ config.py            路径与参数（环境变量可覆盖）
├─ db.py                SQLite 连接 + 版本化迁移
├─ parser.py            粘贴文本 → 词条/题目
├─ tts_service.py       edge-tts 封装与音频缓存
├─ content/
│  ├─ loader.py         内容包读取、校验、缓存（按 mtime 热加载）
│  ├─ packs/*.json      教材内容（原文/译文/题目/词表）
│  └─ imports/*.json    AI 产出的 analysis.json 存档，供重跑合并
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
├─ tests/               pytest，48 个用例，用临时目录
└─ data/
   ├─ app.db            只存记录：作答、会话、生词本、复习状态
   └─ audio/*.mp3       按「文本+音色+语速」哈希缓存
```

`_rea/`（第三方平台截图）与 `.workbuddy/`（本地记忆）不入库。

## 架构：内容与记录分开

**内容和记录分开**，是这套结构唯一的硬约束：

- 教材是 JSON 文件，随 git 版本化。加一篇 = 加一个文件，不改代码、不写迁移、不怕删库。
- 数据库只有事件流：每次作答一条 `attempts`。所以能回答「哪天练了什么、哪个词错了几次」，
  而不用在题目表上反复覆盖 `status`。
- 题目按需生成：同一篇原文能出单词题、听词填句、整句听写，加题型只改
  `app/server/services/dictation.py`。

代价也说清楚：

- 内容包全量读进内存。几十篇、几百篇没问题；上千篇或要全文检索时，再换 SQLite FTS。
- 统计每次现算。个人数据量下毫秒级；真到百万条再考虑汇总表。
- 单用户、无鉴权。要多人用，得先加 `user_id` 与登录——这是唯一需要动表结构的地方。

## 一次练习的完整流程

页面：`/` 总览、`/read` 篇目、`/read/:id` 精读、`/dictate` 听写、`/vocab` 生词、`/stats` 记录。

1. `GET /api/packs/cam18-t3-p3` 拿原文、题目、词表（不含答案）。
2. 点词 → `POST /api/vocab` 收进生词本。
3. `POST /api/dictation/sessions` 开始单词听写；每题 `answer`，最后 `finish`。
4. `POST /api/reading/sessions` 做阅读；`submit` 交卷，返回逐题对错与正确答案。
5. `GET /api/stats/overview`、`/api/stats/daily?days=30` 看记录。
6. 每天清一次 `GET /api/vocab/review`，用 `POST /api/vocab/{id}/review` 打分。

## 阅读：复盘为主，站内不重做

阅读的主流程不在站内做题，而是：

1. 在 idictation 上做完一篇；
2. 用 `ielts-practice-export` 导出 JSONL；
3. 让 AI 按 [docs/AI.md](docs/AI.md)「写作提示词」一节写一份 `analysis.json`；
4. 合并成内容包，站内只负责「读」和「复盘」。

```bat
app\server\.venv\Scripts\python.exe tools\pack_from_export.py ^
  --export .\ielts-data ^
  --book 剑雅18 --test "Test 4" --part "Passage 1" ^
  --analysis .\analysis\cam18-t4-p1.json ^
  --post http://127.0.0.1:8000
```

产出 `app/server/content/packs/<id>.json`，页面 `/read/<id>` 默认进入复盘模式：

- 左栏原文，点词收词、点句看译文；
- 右栏「题解 / 复盘」：逐题诊断、原文出处跳转、三个病灶、下一篇的动作；
- 顶部「读懂这篇」：结构带、正反论证、逐段在干什么、术语、首尾呼应。

点某道题或某个摘要空位时，左栏把那道题的答案句点上 peach 底色，段落序号左侧出现一条
clay 竖线，并滚动过去。格式细节、字段规则、排错与接口字段都在 [docs/AI.md](docs/AI.md)。

## 加内容

**一、复盘包**（主路径）——见上节，完整参数在 [docs/AI.md](docs/AI.md)「复盘流水线」。

**二、旧的单文件精读页**（内嵌 `const DATA` / `DICT` / `REV` / `MEANS`）：

```bat
app\server\.venv\Scripts\python.exe tools\pack_from_html.py "剑雅18-Test3-Passage3-精读与生词本.html" --id cam18-t3-p3
```

产出 `app/server/content/packs/cam18-t3-p3.json`，服务端按文件 mtime 自动重载，也可以调
`POST /api/packs/reload`。页面里带 `REV` / `MEANS` 会一并转成复盘；`--dump-analysis` 可以
另存一份 `analysis.json` 作为以后写复盘的参照。

想把旧页面上的历史成绩一起带过来：

```bat
:: 先启动服务，再执行
app\server\.venv\Scripts\python.exe tools\pack_from_html.py "你的精读页.html" --id cam18-t3-p3 --history --post http://127.0.0.1:8000
```

**三、手写内容包**：格式见 [docs/AI.md](docs/AI.md)「接口契约」的附录。`lexicon` 的值支持简写：
`{"deposit": "n. 押金；存款"}`，词性会自动拆出来。

旧页面生词本里攒的词，用「复制 JSON」导出后导入：

```bat
app\server\.venv\Scripts\python.exe tools\import_vocab.py vocab.json --pack cam18-t3-p3 --post http://127.0.0.1:8000
```

## 测试

```bat
cd app\server
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest tests -q
```

48 个用例，覆盖内容包加载、判分归一化、SRS 调度、听写三种题型、
精读判分、生词本去重与导入导出、统计口径。测试用临时目录，不碰真实 `data/app.db`。

## 发音

`edge-tts`（微软 Edge 的神经音色，免费无需 Key），默认 `en-GB-SoniaNeural`、语速 `-5%`。

- 同一句只生成一次，文件名是内容哈希，改词就自动换新文件。
- 生成失败返回 503，前端可回退 `speechSynthesis`。
- 想换默认音色：改 `app/server/config.py`，或在请求里传 `voice`（可选值见 `GET /api/voices`）。

## 数据与备份

| 要备份的 | 路径 |
|---|---|
| 学习记录 | `app/server/data/app.db`（连同 `-wal`/`-shm`） |
| 音频缓存 | `app/server/data/audio/`（可重建，非必需） |
| 教材 | `app/server/content/packs/`（建议入 git） |

音频缓存按内容哈希命名，删词书不会自动删文件；长期可清理未被引用的 mp3。

## 已知边界

- **词形还原在前端**。生词本以 `lemma` 去重，但后端不跑词形还原；`app/web/src/utils/words.ts`
  的 `lookup()` 已做 `'s` / `s'` / `n't` / `-ies` / `-es` / `-s` / `-ed` / `-ing` / 双写 回退。
- **挖空是启发式的**。优先取生词本里的词，其次最长实词，会跳过句中大写词（人名地名）
  和数字；没有词性标注，偶尔会挖到副词（如 `simply`）。
- **判分不认拼写近似**。大小写、标点、连字符、撇号写法都宽松处理，
  但 `authorisation` / `authorization` 算错——这是有意为之。
- **edge-tts 调的是非官方接口**，接口变动时降级为浏览器合成，功能不中断。
- **无鉴权、无多用户**。只适合本机或内网单人使用；公网部署前请加认证。

## 前端代码约定

Vue 3 + TypeScript + Vite + vue-router，没有 UI 组件库，样式全部走 CSS 变量。
全部前端代码都在 `app/web/`，本节即其说明。

```
app/web/src/
├─ main.ts            入口：样式、主题、语言、路由
├─ App.vue            壳层：侧栏 + RouterView + Toast
├─ router.ts          路由表（按页面懒加载）
├─ styles/
│  ├─ tokens.css      设计 token：灰阶、clay、圆角、字号、明暗主题
│  └─ base.css        reset、排版、focus、滚动条、动效降级
├─ theme.ts           主题状态（light/dark，写 html[data-theme] + localStorage）
├─ i18n.ts            语言字典与 t()（zh/en，写 html[lang] + localStorage）
├─ icons.ts           全部图标 path（stroke 1.5）
├─ api.ts             后端接口封装，唯一 fetch 出口
├─ types.ts           与 API 对齐的类型
├─ state.ts           跨页面的少量共享状态（待复习数）
├─ toast.ts           轻量提示状态
├─ components/        14 个展示组件：AppButton / AudioButton / Card / GuidePane / Icon /
│                     PageHeader / ProgressBar / QuestionRail / ReviewOverview / ReviewRail /
│                     Segmented / SideNav / Toast / WordPopover
├─ views/             6 个页面：Home / Passages / Reader / Dictation / Vocab / Stats
└─ utils/             纯函数：audio / cites / format / rich / words
```

- **颜色、字号、圆角、间距只能引用 `styles/tokens.css` 的变量**，组件里不写死 hex。
- **所有界面文案走 `t('key')`**，不要在图里散落中文字符串；内容数据（原文、释义）除外。
- **所有图标进 `icons.ts`**，用 `<Icon name="…" />`，不引图标库、不用 emoji。
- **接口只从 `api.ts` 调**；请求/响应类型进 `types.ts`。
- **页面取数、组件不取数**。需要跨页共享的状态放 `state.ts`，别复制。
- **间距只用 16 / 24 / 32 / 48**，不要 20 / 28 这类非阶梯值（组件内部微调除外）。
- 设计基线不在这里复述，见 [设计规范](#设计规范)。

```bat
npm run dev        :: 前端 5173，/api 代理到 8000
npm run typecheck  :: vue-tsc
npm run build      :: 产出 dist，后端同端口托管
```

## 加页面

1. 在 `app/web/src/views/` 新建 `.vue`，从 `api.ts` 取数。
2. 在 `router.ts` 加一条懒加载路由。
3. 在 `SideNav.vue` 的 `links` 里加一项（图标先写进 `icons.ts`）。
4. 需要的新文案同时补 `i18n.ts` 的 `zh` 与 `en`。

## 文档

| 文档 | 讲什么 |
|---|---|
| [docs/AI.md](docs/AI.md) | 给 AI 的工程参考：接口契约、复盘流水线、复盘写作提示词 |
| [docs/reference/claude-design-system.md](docs/reference/claude-design-system.md) | 设计系统原始记录（给 AI 用，非本项目规范） |

## 设计规范

`app/web/src/styles/tokens.css` 是唯一真值，本节只写项目实际在用的那部分；改色先改
`tokens.css`，再回来同步这里。另有一份 claude.com 的原始实测记录（**给 AI 用**），其中的 `--color-*`
变量名、H1 64px、Tailwind 段都不适用于本项目，冲突时以本节和 `tokens.css` 为准。

**色板**（下表为浅色主题的值，深色主题在 `tokens.css` 的 `[data-theme="dark"]` 里覆盖）

| 用途 | Token | 值 |
|---|---|---|
| 页面底 / 次级面 / 凹陷 / 浮起 | `--bg-page` `--bg-subtle` `--bg-sunken` `--bg-raise` | `#faf9f5` `#f5f4ed` `#f0eee6` `#ffffff` |
| 正文 / 次级文字 / 弱化文字 | `--fg` `--fg-2` `--fg-3` | `#141413` `#5e5d59` `#73726c` |
| 发丝线 / 柔线 / 硬线 | `--line-hair` `--line-soft` `--line-strong` | `#e8e6dc` `#dedcd1` `#d1cfc5` |
| 主强调（只做线/点/图标） | `--clay` `--clay-hover` `--clay-dark` | `#d97757` `#c6613f` `#c46849` |
| 柔和暖色块 | `--peach` | `#ebc9b7` |
| 冷色块 / 辅助绿 / 错误 | `--sky` `--mineral` `--error` | `#6a9bcc` `#629987` `#bf4d43` |

明暗主题只翻语义层（`--bg-*` / `--fg*` / `--line-*`），强调色不变。

**字体**

- 标题：`Georgia, "Times New Roman", "DengXian", "等线", "SimHei", "黑体", "Heiti SC", "PingFang SC", serif`
- 界面：`Inter, -apple-system, "Segoe UI", "DengXian", "等线", "SimHei", "PingFang SC", sans-serif`
- 等宽：`"JetBrains Mono", Consolas, monospace`

**字号**（`--text-*`）

| 档 | 值 | 用途 |
|---|---|---|
| display | `clamp(34px, 3.2vw, 52px)` | 首屏标题 |
| h1 | `clamp(28px, 2.2vw, 36px)` | 页面标题 |
| h2 / h3 | 24 / 19 | 区块标题 |
| body / sm / xs / micro | 15 / 13 / 12 / 11 | 正文与说明 |

标题用 500 字重，不要 700。

**间距 / 圆角 / 描边 / 测度**

- 间距阶梯 4/8/12/16/24/32/48/64/96；页面级只用 **16 / 24 / 32 / 48**。
- 圆角 4/6/8/12/16/24/999；大面积容器用大圆角。
- 分隔线一律 **0.5px** 发丝线（`--line-hair`），不要 1px 实线堆叠。
- 正文测度 60ch，长文 68ch，窄栏 20ch，标题 30ch。

**组件规则**

- clay 只做线、点、图标、激活指示（面积 ≤5%），**不做浅底正文色**（对比度 2.96:1）。
- hover 用 2px 同色外环（`box-shadow: 0 0 0 2px`），不靠变色。
- focus 用 `2px solid #c46849`，offset 2px，键盘可见。
- 阴影只用于浮层（`--shadow-sm/md`），平面内容不加阴影。
- 按钮圆角 8px；主按钮黑底白字，次按钮透明 + 1px 边框。

**语义色**

| 语义 | Token | 浅色值 |
|---|---|---|
| 正确 | `--ok` `--ok-bg` `--ok-line` | `#3f6b55` `#edf3ea` `#cfdfc8` |
| 错误 | `--bad` `--bad-bg` `--bad-line` | `#a34329` `#f8e9e3` `#eed2c6` |
| 警示 | `--warn` | `#8a6a2f` |
| 反方/假设块 | `--band-a-bg` `--band-a-line` | `#f7ece4` `#ecd8c9` |
| 答案句 | `--hl-answer` `--hl-line` | `--peach` / `--clay` |

答案句高亮：句子铺 `--hl-answer` 底色，段落序号左侧一条 2px `--hl-line` 竖线；深色主题下
底色用 `color-mix(clay 30%, bg-page)`。

**反模式**：emoji 当图标、组件里写死 hex、冷灰 `#f5f5f5`、clay 当正文文字色、20/28px 间距、
阴影叠加、渐变与玻璃拟态、标题 700、正文超过 68ch。

**自检**：底色是暖白不是纯白；clay 只出现在线/点/图标；区块靠边框与留白分隔而不是底色差；
正文测度已设；focus 环在键盘下可见。

完整原文（含 `<role>` 元提示、Tailwind 段、64px 标题）没有并进本文，单独放在
[docs/reference/claude-design-system.md](docs/reference/claude-design-system.md)，供 AI 生成界面时参考，
不作为本项目的实现规范。
