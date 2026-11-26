# 小头雅思 · Cloudflare 上线部署指南

已为你配置好：
- Worker 入口：`src/index.ts`（含 `/api/sync`、`/api/packs*`、`/api/dict/bundle`、`/api/dict/shard/:letter`、`/api/audio/:name` 与静态资源托管）
- D1 数据库：`xiaotou-ielts-db`（ID：`2782ef36-07ef-4928-8781-a9777b8f5c8b`）
- R2 Bucket：`xiaotou-ielts`（APAC）
- 目标域名：`https://xiaotou-ielts.yyyyyjp.workers.dev`

---

## 一键部署步骤（本地终端执行）

### 1. 安装依赖并登录 Cloudflare
```powershell
cd app\cloud
npm install
npx wrangler login
```

### 2. 初始化 D1 数据库表结构 & 导入已有篇目
回到仓库根目录执行：
```powershell
cd ..\..
app\server\.venv\Scripts\python.exe tools\prepare_cloud_assets.py --upload
cd app\cloud
npx wrangler d1 execute xiaotou-ielts-db --remote --file=./schema.sql
npx wrangler d1 execute xiaotou-ielts-db --remote --file=./seed_packs.sql
```
> 上一步会自动生成并上传 `dict/core_dict.json.gz`（6.6 万核心词，1.96 MB）、27 个 `dict/shards/*.json.gz`（77 万全量首字母分片）以及本地已缓存的音频到 R2，并把所有精读篇目写入 D1。

### 3. 设置同步口令（强烈建议，防公网未授权访问）
```powershell
npx wrangler secret put SYNC_TOKEN
```
输入你自己的口令（例如一串随机密码）。

### 4. 构建前端并发布 Worker
```powershell
cd ..\web
npm run build
cd ..\cloud
npx wrangler deploy
```
发布完成后访问 `https://xiaotou-ielts.yyyyyjp.workers.dev`。

---

## 迁移你现有的本地数据（生词本 & 做题记录）

1. 打开你本地版网页左下角 **同步状态面板** → 点击 **「导出备份」**，保存 JSON 文件；
2. 打开线上版 `https://xiaotou-ielts.yyyyyjp.workers.dev`，左下角同步面板展开 **「云端接口与口令设置」**，填入刚刚设置的 `SYNC_TOKEN` 并保存；
3. 点击 **「恢复备份」** 选择刚才导出的 JSON，所有生词、复习进度与练习记录会自动同步到云端 D1。
4. 在面板点一次 **「缓存全部篇目」**，之后即使断网或 Cloudflare 连接卡顿，网页也能通过 PWA + IndexedDB 秒开使用，后台静默同步。
