# tifo 前端

Vue 3 + TypeScript + Vite + vue-router。没有 UI 组件库，样式全部走 CSS 变量。

## 目录

```
src/
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
├─ components/        可复用展示组件：Icon/Button/Card/Segmented/…
├─ views/             页面：只做编排与取数
└─ utils/             纯函数：判分展示、日期、词形、音频播放
```

## 约定

- **颜色、字号、圆角、间距只能引用 `styles/tokens.css` 的变量**，组件里不写死 hex。
- **所有界面文案走 `t('key')`**，不要在图里散落中文字符串；内容数据（原文、释义）除外。
- **所有图标进 `icons.ts`**，用 `<Icon name="…" />`，不引图标库、不用 emoji。
- **接口只从 `api.ts` 调**；请求/响应类型进 `types.ts`。
- **页面取数、组件不取数**。需要跨页共享的状态放 `state.ts`，别复制。
- 设计基线：暖白 `#faf9f5`、衬线 500 标题、0.5px 发丝线、clay 只做线/点/图标、
  hover 用 2px 同色环、focus 用 2px `#c46849` 轮廓。
- 间距只用 16 / 24 / 32 / 48，不要 20 / 28 这类非阶梯值（组件内部微调除外）。

## 加页面

1. 在 `views/` 新建 `.vue`，从 `api.ts` 取数。
2. 在 `router.ts` 加一条懒加载路由。
3. 在 `SideNav.vue` 的 `links` 里加一项（图标先写进 `icons.ts`）。
4. 需要的新文案同时补 `i18n.ts` 的 `zh` 与 `en`。

## 命令

```bat
npm run dev        :: 前端 5173，/api 代理到 8000
npm run typecheck  :: vue-tsc
npm run build      :: 产出 dist，后端同端口托管
```
