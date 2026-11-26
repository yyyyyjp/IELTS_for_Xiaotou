# 小头雅思 · Cloudflare 多用户上线部署指南

架构组件：
- Worker 入口：`src/index.ts`（GitHub OAuth + 邀请码激活 + 按 `user_id` 严格隔离的 `/api/sync`、`/api/packs*` + 公共 R2 离线词典与静态资源托管）
- D1 数据库：`xiaotou-ielts-db`（ID：`2782ef36-07ef-4928-8781-a9777b8f5c8b`）
- R2 Bucket：`xiaotou-ielts`（APAC）
- 目标域名：`https://xiaotou-ielts.yyyyyjp.workers.dev`
- 管理员账号：`wrangler.toml` 中 `ADMIN_GITHUB_LOGIN = "yyyyyjp"`（首次 GitHub 登录自动激活为 `admin` 并接管 `u_admin` 存量数据）

---

## 一、首次部署步骤

### 1. 安装依赖并登录 Cloudflare
```powershell
cd app\cloud
npm install
npx wrangler login
```

### 2. 初始化 D1 表结构 & 上传公共词典到 R2
```powershell
cd ..\..
app\server\.venv\Scripts\python.exe tools\prepare_cloud_assets.py --upload
cd app\cloud
npx wrangler d1 execute xiaotou-ielts-db --remote --yes --file=./schema.sql
npx wrangler d1 execute xiaotou-ielts-db --remote --yes --file=./seed_packs.sql
```
> 若是从旧版单用户 D1 升级到多用户 v2，请执行一次无损迁移脚本（不要重复执行）：
> ```powershell
> npx wrangler d1 execute xiaotou-ielts-db --remote --yes --file=./migrate_v2_multiuser.sql
> ```

### 3. 配置 GitHub OAuth & JWT Secrets
先在 GitHub `Settings → Developer settings → OAuth Apps` 创建应用：
- Homepage URL：`https://xiaotou-ielts.yyyyyjp.workers.dev`
- Authorization callback URL：`https://xiaotou-ielts.yyyyyjp.workers.dev/api/auth/github/callback`

然后写入 Worker Secrets（不要提交到代码库）：
```powershell
npx wrangler secret put GITHUB_CLIENT_ID
npx wrangler secret put GITHUB_CLIENT_SECRET
npx wrangler secret put JWT_SECRET
```
> `JWT_SECRET` 建议使用 32 字节以上随机字符串，用于签发 30 天有效期的 HS256 JWT。

### 4. 构建前端并发布 Worker
```powershell
cd ..\web
npm run build
cd ..\cloud
npx wrangler deploy
```

---

## 二、多用户数据隔离与邀请码使用

1. **强制登录**：未登录访问页面只显示 GitHub 登录门禁；除 `/api/health`、`/api/auth/*` 及公共只读离线词典/音频外，其余接口未登录一律返回 `401`。
2. **严格按用户隔离**：每位用户的原文篇目（`packs`）、作答历史（`sessions`/`attempts`）、AI 复盘与精读导读、生词本（`vocab`）在 D1 按 `user_id` 隔离，浏览器 IndexedDB 也按 `xiaotou_local_v2_<userId>` 物理分库（仅公共词典缓存在 `xiaotou_dict_v1`）。
3. **邀请码管理**：管理员登录后，在左下角同步面板展开 **「邀请码管理」**，可指定可用次数与备注生成邀请码（格式 `XT-XXXX-XXXX`）、一键复制或随时作废。新用户首次用 GitHub 登录后输入有效邀请码即可激活使用。
