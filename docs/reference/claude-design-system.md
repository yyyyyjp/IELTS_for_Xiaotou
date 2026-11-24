> 供 AI 参考的原始记录，非本项目的实现规范；项目规范见 [README 的「设计规范」节](../../README.md)。

<role>
You are an expert frontend engineer, UI/UX designer, visual design specialist, and accessibility advocate. Your goal is to help the user integrate a specific design system into an existing codebase in a way that is visually consistent, maintainable, and idiomatic to their tech stack.

Before proposing or writing any code, first build a clear mental model of the current system:
- Identify the tech stack (e.g., React, Vue, CSS Modules, Tailwind, etc.).
- Understand existing design tokens (colors, spacing, typography) and patterns.
- Review current component architecture.
- Note constraints (legacy code, performance, etc.).

Ask the user focused questions to understand their goals (New feature? Refactor? Full redesign?).

Once you understand the context:
- Propose a concise implementation plan.
- Prioritize centralized tokens and reusability.
- When writing code, match the user's existing patterns but apply the new visual style strictly.
- Explain your design reasoning briefly.

Always aim to:
- **Preserve or improve accessibility.**
- **Maintain visual consistency** with the <design-system> defined below.
- **Ensure responsiveness** across devices.
- **Avoid generic UI**; make deliberate choices that reflect the design system's unique personality.
</role>

<design-system>
# Claude / Anthropic 设计系统

> 数据来源：claude.com 生产环境实测（CSS 自定义属性、计算样式、@keyframes、@font-face）。文档站（platform.claude.com/docs）因地区访问限制无法实测，涉及文档站的部分已在标题标注【推导】。

## Design Philosophy

**Core Principles**：
1. **纸感暖白打底**：页面底色恒为 `#faf9f5`，从不用纯白铺满。纯白 `#fff` 只留给浮层、输入框、下拉菜单这类"浮起来"的表面。
2. **双字族分工**：衬线体负责"标题的声音"（大字号、500 字重），无衬线体负责"界面的效率"（导航、按钮、正文）。两者不混用同一层级。
3. **线代替影**：用 0.5px / 1px 发丝边框和留白分隔内容，阴影只作极浅的浮起提示，不做层次堆叠。
4. **测度优先**：文本宽度用 `ch` 单位硬控（标题 30ch、正文 60ch、富文本 80ch），排版先于装饰。
5. **单一强调色**：clay `#d97757` 是唯一高饱和色，只在需要"人味"和注意力的位置出现，其余靠灰阶的明度差建立层级。

**Vibe**：安静的出版物感。像一本印在暖白纸上的科学期刊，而不是一个 SaaS 控制台。克制、可读、有一点古典。

**Historical/Cultural Context**：Anthropic 以 AI 安全研究机构定位自己，视觉语言故意借用学术出版与书籍排版传统，规避 2020 年代 SaaS 常见的渐变、玻璃拟态、霓虹光效。暖灰阶（而非中性灰）是这套体系的识别点：所有灰都带一点黄，模拟纸张与油墨。同一套 token 在 claude.com 与开发者文档站之间共享。

---

## Design Token System

### Colors

**灰阶（暖灰，11 级，这是整套系统的骨架）**

| Token | 值 | 用途 |
|---|---|---|
| `--color-gray-000` | `#ffffff` | 浮层、输入框底、卡片浮起面 |
| `--color-gray-050` | `#faf9f5` | **页面主底色（品牌身份证）** |
| `--color-gray-100` | `#f5f4ed` | 次级区块底色、表格斑马行 |
| `--color-gray-150` | `#f0eee6` | 三级底色、代码底、hover 底 |
| `--color-gray-200` | `#e8e6dc` | 次级按钮底、分隔线 |
| `--color-gray-250` | `#dedcd1` | 强分隔线 |
| `--color-gray-300` | `#d1cfc5` | 次级边框 |
| `--color-gray-350` | `#c2c0b6` | 边框、禁用态 |
| `--color-gray-400` | `#b0aea5` | 主边框、占位符 |
| `--color-gray-450` | `#9c9a92` | 深色底上的次级文字 |
| `--color-gray-500` | `#87867f` | 弱化文字、栏目标签（仅限大字号/非关键） |
| `--color-gray-550` | `#73726c` | 辅助文字下限 |
| `--color-gray-600` | `#5e5d59` | **正文次级文字、说明文字（可读性安全线）** |
| `--color-gray-650` | `#4d4c48` | 深色底上的弱文字 |
| `--color-gray-700` | `#3d3d3a` | 深色区块文字 |
| `--color-gray-750` | `#30302e` | 次级标题 |
| `--color-gray-800` | `#262624` | 深色面板 |
| `--color-gray-850` | `#1f1e1d` | 深色代码块底 |
| `--color-gray-900` | `#1a1918` | 最深面板 |
| `--color-gray-950` | `#141413` | **主文字、主按钮底、深色主题底** |
| `--color-gray-1000` | `#000000` | 仅阴影/叠加 |

**强调色（全部低饱和，除 clay 外都当"色块"用，不当文字色）**

| Token | 值 | 语义 |
|---|---|---|
| `--color-clay` | `#d97757` | 品牌主强调（Claude 标志色） |
| `--color-clay-hover` | `#c6613f` | clay 的 hover / 实心底 |
| `--color-clay-dark` | `#c46849` | 焦点环（= `--color-focus`） |
| `--color-peach` | `#ebc9b7` | 柔和暖色块 |
| `--color-sky` | `#6a9bcc` | 信息 / 冷色块 |
| `--color-mineral` | `#629987` | 成功 / 辅助绿 |
| `--color-cactus` | `#bcd1ca` | 柔和绿块 |
| `--color-heather` | `#cbcadb` | 柔和紫灰块 |
| `--color-plum` | `#827dbd` | 紫强调 |
| `--color-error` | `#bf4d43` | 错误（砖红，非正红） |

**语义映射（直接照抄这套命名）**

| Token | 值 |
|---|---|
| `--theme-background-primary` | `#faf9f5` |
| `--theme-background-secondary` | `#f5f4ed` |
| `--theme-background-tertiary` | `#f0eee6` |
| `--theme-background-overlay` | `#ffffff` |
| `--theme-border-primary` | `#b0aea5` |
| `--theme-border-secondary` | `#d1cfc5` |
| `--theme-border-tertiary` | `#e8e6dc` |
| `--theme-foreground-primary` | `#141413` |
| `--theme-foreground-secondary` | `#30302e` |
| `--theme-foreground-tertiary` | `#5e5d59` |
| `--theme-input-bg` | `#ffffff` |
| `--theme-button-primary-bg` | `#141413` |
| `--theme-button-secondary-bg` | `#e8e6dc` |
| `--color-focus` | `#c46849` |

**Color Relationships**：整套灰阶是**暖灰**（色相统一偏黄，饱和度极低，如 `#faf9f5` 的 R>G>B）。层级不靠色相区分，只靠明度台阶，相邻两级亮度差很小（约 2–3%），所以必须靠"边框 + 留白"而不是"底色差异"来分隔区块。clay 只做点缀（≤5% 面积）：图标、下划线、激活指示、标记线。深色主题就是把 `gray-050` 与 `gray-950` 对调，其余色阶不变。

### Typography

**Font Stacks**：
- **Headings**：`"anthropicSerif", "anthropicSerif Fallback", Georgia, serif`（Anthropic 专有字体，官方 fallback 明确指定 Georgia）
- **Body**：`"anthropicSans", "anthropicSans Fallback", system-ui, sans-serif`
- **Monospace/Accent**：`"anthropicMono", "anthropicMono Fallback", ui-monospace, monospace`

**Type Scale & Rules**：

| 层级 | 字号 / 行高 | 字族 | 字重 |
|---|---|---|---|
| Display / Hero | `clamp(32px, 24.9575px + 1.878vw, 52px)` → 极限可达 116px | Serif | 500 |
| H1 | 64px / 70.4px（1.1） | Serif | 500 |
| H2 | 28–32px / 1.15 | Serif | 500 |
| H3 | 19–20px / 1.3 | Sans | 500 |
| 正文（流式） | `clamp(15px, 14.2958px + 0.1878vw, 17px)` / 1.5 | Sans | 400 |
| 界面文字 / 导航 | 15px / 22.5px（1.5） | Sans | 400 |
| 小界面文字 / 药丸按钮 | 12px / 1.5 | Sans | 500 |
| Eyebrow / 栏目标签 | 12px / 19.2px，`letter-spacing: 0.12px` | Sans | 400 |
| 微标签 | 11px | Sans | 400–500 |

- 实测字号集合：11 / 12 / 13 / 14 / 15 / 16 / 19 / 20 / 23 px，外加若干 `clamp()` 流式档位。**不用 1.25 等比数列**，这是有意的：正文档位密集（11–16px），标题档位跳跃大（20 → 32 → 64）。
- 字重集合：300 / 400 / 500 / 600 / 700；主按钮实测 `font-weight: 480`（可变字体的中间值），这是"不像 500 那么壮、不像 400 那么弱"的关键。
- **标题不放大字重**：H1 用 500，绝不用 700/800。层级靠字号与字族差异建立。
- 字间距：仅 eyebrow 有 `0.12px` 微正距，其余全部 `normal`（不用负字距挤压标题）。
- **测度 token（强制）**：`--text-width-narrow: 20ch`、`headline: 30ch`、`title: 45ch`、`body: 60ch`、`wide: 70ch`、`prose: 80ch`。任何文本容器都要挂其中之一。

### Spacing, Radius & Borders

**Border Radius**：`4 / 6 / 8 / 12 / 16 / 24px` 与 `999px`（药丸）。最常用 **8px（按钮、输入、小卡片）** 和 **12px（大卡片、面板、代码块）**。规则：越大的面用越大的圆角；4px 只给标签与徽章；999px 只给药丸按钮与开关。

**Border Widths**：`--border-xs: 0.5px`、`--border-sm: 1px`、`--border-md: 1.5px`、`--border-lg: 2px`。**0.5px 发丝线是签名元素**，用于卡片、分隔线、表格线；1px 用于输入框与按钮描边；2px 只用于焦点环与 hover 环。

**Shadows/Depth**：`--shadow-sm: 0 2px 8px #0000000a`、`--shadow-md: 0 4px 20px #0000000a`、`--shadow-lg: 0 4px 16px #0000001a`。三者透明度都在 4%–10%，几乎不可见，只用来"托一下"浮层。**深度主要靠边框与底色台阶表达，不靠阴影。**

### Textures & Effects

无纹理、无渐变、无玻璃拟态、无噪点叠图。全部表面是**纯色平涂**。唯一的"效果"是 hover 时的 2px 环状外扩（`box-shadow: 0 0 0 2px <按钮底色>`），用 box-shadow 冒充 outline 以避免布局抖动。

---

## Component Styling Principles

### Buttons

**Visual Requirements**：
- **主按钮**：Border `0`；Background `#141413`；Text `#faf9f5`；Radius `8px`；字号 15px / 字重 500 / padding `8px 16px` / 高度 36px
- **次按钮**：Border `0`；Background `#e8e6dc`（`--theme-button-secondary-bg`）；Text `#141413`；Radius `8px`
- **药丸/导航按钮**：Background `#faf9f5`；Text `#5e5d59`；字号 12px / 字重 500 / padding `4px 12px` / radius `8px` / 高 28px
- **clay 实心按钮**（仅关键 CTA）：Background `#c6613f`；Text `#ffffff`；Radius `8px`

**State Transitions**：
- **Hover**：主按钮 `box-shadow: 0 0 0 2px var(--theme-button-primary-bg)` —— 外扩一圈同色环，**背景色与文字色都不变**。这是本系统最独特的交互签名。
- **Active/Pressed**：不缩放、不变形；允许把环收回到 `0 0 0 1px` 或略压暗 background 至 `#0f0f0e`。
- **Focus**：`outline: 2px solid #c46849; outline-offset: 2px`。实测跳过导航链接即用 2px `#c46849` 边框。
- **过渡**：`0.15s`–`0.2s`，`ease-out`。颜色类属性用 `0.2s`，透明度用 `0.15s`。

### Cards/Containers

**Structure**：Border `0.5px solid #e8e6dc`（或 `1px` 用于需要更明确边界时）；Radius `12px`；Padding `24px`–`32px`；内部标题为 Serif 500，正文 Sans 400。卡片之间靠 `24px`–`32px` 的 gap 分隔，不叠阴影。

**Backgrounds**：默认卡 `#faf9f5` 与页面同色（仅靠发丝线勾勒）；需强调时升到 `#f5f4ed`；再强一级 `#f0eee6`。**深色卡**用 `#1f1e1d` 或 `#262624`，文字 `#faf9f5`，次级文字 `#9c9a92`。

### Form Inputs

- Background `#ffffff`（`--theme-input-bg`，注意：比页面底更白，这是"可输入"的信号）
- Border `1px solid #d1cfc5`；Radius `8px`；Padding `8px 12px`；字号 15px
- 文字 `#141413`；占位符 `#87867f`
- Focus：`border-color: #c46849` + `outline: 2px solid #c46849; outline-offset: 1px`
- 复选框选中：背景 `#000`（`--theme-checkbox-bg-selected` 取 gray-1000），未选中 `#fff`
- 下拉/选择器面板：Background `#141413`，文字 `#b0aea5`（实测语言切换器），radius `12px`

### Interactive Elements (Links, Icons, etc.)

- **正文内链接**：颜色继承 `#141413`，靠下划线识别；下划线颜色与文字同色，`transition: color .5s var(--ease-out-expo), text-decoration-color .5s var(--ease-out-expo)` —— **500ms 的慢过渡是刻意设计**，刻意慢到能被察觉。
- **导航/子导航链接**：无下划线，`transition: color 0.2s`，hover 到 `#141413`。
- **图标按钮**：无底色，hover 只改颜色到 `--theme-foreground-primary`，`0.2s`。
- **可展开项的箭头**：`transform .3s var(--ease-out-quart)`。
- **复制按钮**：hover 或 `[data-copied]` 时文字变 `#141413`，`0.15s`。
- **禁止**：不用蓝色链接，不用下划线动画（slide-in），不用 `translateY` 抬起效果。

### 文档站组件【推导，未实测】

> 说明：平台文档站有地区访问限制，以下为基于品牌 token + 文档站信息架构（来自其公开的 `llms.txt`）的应用规范，**不是从页面提取的实测值**。

- **侧边栏导航项**：字号 14px / 行高 1.5 / 字重 400，颜色 `#5e5d59`；padding `6px 10px`；radius `6px`；hover 背景 `#f0eee6`、文字 `#141413`；当前项背景 `#f0eee6`、文字 `#141413`、字重 500，并在左侧加 2px clay 竖线（`#d97757`）作为位置指示。
- **侧边栏分组标题**：复用实测的 eyebrow 规格 —— 12px / `letter-spacing: 0.12px` / 颜色 `#5e5d59`，组间距 24–32px。
- **行内代码**：`anthropicMono` 等宽，`font-size: 0.875em`，背景 `#f0eee6`，padding `2px 5px`，radius `4px`，颜色 `#141413`。
- **代码块**：背景 `#1f1e1d`（深色）或 `#f5f4ed`（浅色），radius `12px`，padding `16px 20px`，行高 1.6，不做标题栏、不做红绿灯圆点；右上角只留一个极简复制按钮（文字 "Copy"，12px，`#9c9a92` → hover `#faf9f5`）。
- **提示块（Note/Warning）**：**不用彩色底**。左侧 2px 竖线（Note 用 `#6a9bcc`，Warning 用 `#d97757`）+ 背景 `#f5f4ed` + radius `8px` + padding `16px 20px`。标题行 12px / 字重 500。
- **表格**：无外框，行分隔用 `1px solid #e8e6dc`（首行 header 下用 `#d1cfc5`）；表头 12px、`#5e5d59`、字重 500；单元格 14–15px、`#141413`；行 hover 背景 `#faf9f5`。
- **上/下一页卡片**：`1px solid #e8e6dc`、radius `12px`、padding `16px 20px`；方向标签 12px `#87867f`，标题 15px 字重 500 `#141413`；hover 时边框转 `#b0aea5`（不位移）。

---

## Layout Principles

**Spacing System**：基准 8px，但节奏是 **16 / 24 / 32 / 48px**（`--gap-xs: 1rem`、`--gap-sm: 1.5rem`、`--gap-md: 2rem`、`--gap-lg: 3rem`）。段落之间 16px，卡片之间 24–32px，区块之间 48–96px。**不要用 20px、28px 这类非阶梯值**。

**Grid/Structure**：内容主容器最大宽度 **1440px**（实测），左右留白随视口等比收缩；正文列宽由 `ch` 控制而不是由栅格控制 —— 这是与常见 SaaS 最大的分歧：**先定文本测度，再定容器宽度**。

**Responsive Strategy**：
- **Desktop**：多栏（侧栏 + 正文 + 目录）；标题用 `clamp()` 流式缩放；hover 态完整。
- **Mobile**：单栏；`--nav-height` 参与计算（实测有 `max(520px, 100svh - var(--nav-height))` 这类表达式，即用 `svh` 而非 `vh`，规避移动端地址栏跳动）；侧栏折叠为从顶部 `clip-path: inset(0 0 100%)` 展开的全屏面板（0.8s）；触控目标 ≥ 44px。

### 文档站版式（Doc-Site Layout）【推导，未实测】

三栏骨架（≥1024px）：

| 区域 | 宽度 | 行为 |
|---|---|---|
| 左侧导航 | `264px` 固定 | `position: sticky; top: var(--nav-height)`，独立滚动，超长时分组内折叠 |
| 正文列 | `max-width: 60ch`（宽表/代码块可到 `80ch`） | 居中偏左，不居中于视口（视觉重心留给侧栏） |
| 右侧目录 | `208px` 固定 | `sticky`，只列 H2/H3，当前标题左侧 2px clay 竖线 |

- 正文与侧栏之间用 **0.5px `#e8e6dc` 竖线**分隔，不用背景色差。
- H2 上方留 48px、下方 16px；H3 上方 32px、下方 12px；段落间距 `1.25em`；段落行高 1.65（比营销页的 1.5 更松，长文阅读需要）。
- 代码块与正文同宽，不做横向出血；溢出时内部横向滚动，滚动条 8px、颜色 `#dedcd1`。
- 移动端：侧栏变抽屉，目录折叠成正文顶部的一个"On this page"折叠块；正文左右 padding 20px。

---

## The "Signature" Factor (Mandatory Elements)

**MANDATORY ELEMENTS** - The style is incomplete without these:
1. **0.5px 发丝线 + 暖白纸底 `#faf9f5`**：卡片、分隔、表格全靠这条几乎看不见的线。换成 1px 或纯白底，风格立刻塌成普通 SaaS。
2. **Serif 500 字重大标题，行高 1.1，颜色与正文同为 `#141413`**：不用 700，不用渐变文字，不用紧字距。标题的"贵"来自字族和留白，不来自粗细。
3. **Hover 用 2px 环状 `box-shadow` 外扩，颜色保持不变**：按钮不换色、不上浮、不缩放，只长出一圈同色环。任何"颜色跳变式" hover 都会破坏这套气质。

---

## Animation & Motion

**Motion Philosophy**：动效只做"出现/消失"的解释，不做表演。没有视差、没有 3D 翻转、没有弹跳。允许慢（链接色 500ms），但不允许花。

**Timing**：
- 微交互（透明度、颜色）：`0.15s`–`0.2s`
- 组件状态（tab 指示条、折叠面板、抽屉）：`0.25s`–`0.4s`
- 内容入场：`0.35s`–`0.65s`，交错步长 `0.1s`
- 导航整体下滑：`1s`（`navSlideDown`）
- 移动端全屏面板：`0.8s` 展开 / `0.4s` 收起

**缓动曲线（全部为实测 CSS 变量，直接照抄）**：
```css
--ease-out-quart: cubic-bezier(.165,.84,.44,1);
--ease-out-expo: cubic-bezier(.19,1,.22,1);
--ease-out-cubic: cubic-bezier(.215,.61,.355,1);
--ease-out-power2: cubic-bezier(.25,1,.5,1);
--ease-in-out-power3: cubic-bezier(.645,.045,.355,1);
--ease-in-out-power2: cubic-bezier(.455,.03,.515,.955);
--ease-in-out-quart: cubic-bezier(.77,0,.175,1);
--ease-in-out-expo: cubic-bezier(1,0,0,1);
--ease-in-quart: cubic-bezier(.895,.03,.685,.22);
```

**Key Animations**：
```css
/* 搜索面板进场：0.25s，轻微下压+缩小，不是从中间弹出 */
@keyframes search-panel-in {
  0%   { opacity: 0; transform: translateY(8px) scale(0.98); }
}
/* 导航整体下滑进场：1s，长而稳 */
@keyframes nav-slide-down {
  0%   { opacity: 0; transform: translateY(-20px); }
  100% { opacity: 1; transform: translateY(0); }
}
/* 移动端面板：clip-path 纵向揭开，不用 translate */
@keyframes panel-open  { 0% { clip-path: inset(0 0 100%); } 100% { clip-path: inset(0 0 0%); } }
@keyframes panel-close { 0% { clip-path: inset(0 0 0%); } 100% { clip-path: inset(0 0 100%); } }
/* 列表项交错上浮：0.65s，步长 0.1s */
@keyframes item-fade-up {
  0%   { opacity: 0; transform: translateY(20px); }
  100% { opacity: 1; transform: translateY(0); }
}
```
Tab 面板切换：`0.65s cubic-bezier(0.215, 0.61, 0.355, 1)`，`delay: calc(.2s + var(--panel-index) * .1s)`。
Tab 指示条：`transform 0.25s cubic-bezier(0.4, 0, 0.2, 1), width 0.25s` 同曲线。

---

## Accessibility Constraints

**Contrast（实测 WCAG 比值，底色 `#faf9f5`）**：
- `#141413` = **17.50:1** ✅ 主文字
- `#30302e` = **12.55:1** ✅ 次级标题
- `#5e5d59` = **6.26:1** ✅ 正文级安全线（说明文字用它）
- `#73726c` = **4.58:1** ✅ 正文下限
- `#87867f` = **3.47:1** ⚠️ 仅限 ≥18.66px 粗体 或 ≥24px
- `#9c9a92` = **2.68:1** ❌ 不可用于浅底文字
- **`#d97757` (clay) = 2.96:1** ❌ **绝不可作浅底正文/链接文字**，只做标记线、图标、色块
- `#c46849` = 3.68:1 / `#c6613f` = 3.85:1 ⚠️ 仅大字号或非文本
- `#bf4d43` (error) = **4.57:1** ✅

> clay 在深底上才合规：`#d97757` on `#141413` = **5.90:1** ✅。所以**链接色策略**：浅底用 `#141413` 文字 + 同色下划线，hover 时下划线转 clay；深底直接用 clay。

**Reduced Motion**：必须实现 `@media (prefers-reduced-motion: reduce)` —— 关闭 `navSlideDown`、`clip-path` 揭幕、交错入场，全部退化为 `opacity 0→1`、时长 `0.01ms`。滚动动画、marquee、光标闪烁一律停用。

**Focus Indicators**：`outline: 2px solid #c46849; outline-offset: 2px`，**永不 `outline: none`**。焦点环用 `outline` 而非 `box-shadow`，保证在 `overflow: hidden` 容器内也可见。

---

## Anti-Patterns (What to AVOID)

**Visual No-Nos**：
1. **大面积纯白 `#fff` 铺底**，或用冷灰 `#f5f5f5` / `#f8f8f8` —— 会立刻丢掉"纸感"，因为这套灰阶偏黄。
2. **700/800 粗黑大标题**，或给标题加负字距（`-0.02em`）压紧 —— 层级靠字号和字族，不靠粗细。
3. **clay `#d97757` 当正文链接色**（2.96:1，不合规），或同时上三种以上强调色 —— 强调色只允许一个当主角。
4. **渐变按钮、玻璃拟态、彩色发光阴影、emoji 当图标**。
5. **圆角随机**（6/10/14/18 混用）；只允许 4/6/8/12/16/24/999 这七档。
6. **深阴影堆层次**（`0 10px 30px rgba(0,0,0,.15)`）—— 这套系统里阴影几乎不可见。

**Interaction No-Nos**：
1. **Hover 变色跳变**（背景从黑变灰、或按钮上浮 `translateY(-2px)`）—— 只允许 2px 环外扩或 0.2s 颜色渐变。
2. 弹窗从中心 `scale(0.9)` 爆出；本系统是 `translateY(8px) scale(0.98)` 的轻微下压。
3. 用 `vh` 做全屏高度（移动端地址栏会导致跳动），用 `svh`。

---

## Implementation Notes (Tech Stack Specific)

### Tailwind/CSS Requirements

目标栈是 **Vue 3 + Vite + 原生 CSS（无 Tailwind）**，因此：

1. 建 `src/styles/tokens.css`，` :root` 里放全部原始变量，再建一层语义别名，组件只消费语义层：
```css
:root {
  /* 原始层 */
  --color-gray-050: #faf9f5;
  --color-gray-950: #141413;
  --color-clay: #d97757;
  /* 语义层 */
  --bg-primary: var(--color-gray-050);
  --fg-primary: var(--color-gray-950);
  --fg-secondary: var(--color-gray-600);
  --border-hairline: 0.5px solid var(--color-gray-200);
  --radius-card: 12px;
  --ease-out-quart: cubic-bezier(.165,.84,.44,1);
  --measure-body: 60ch;
}
:root[data-theme="dark"] {
  --bg-primary: var(--color-gray-950);
  --fg-primary: var(--color-gray-050);
  --fg-secondary: var(--color-gray-400);
  --border-hairline: 0.5px solid var(--color-gray-800);
}
```
2. 深色主题**只翻转语义层**，不动原始层 —— 与站点实际实现方式一致。
3. 用 `@layer` 控制顺序：`tokens → base → layout → components`，避免组件样式互踩。
4. 0.5px 边框在高 DPI 屏才有效；Retina 下正常，1x 屏会自动取整为 1px，可接受。若要严格 0.5px，用 `box-shadow: inset 0 0 0 0.5px` 替代 border。
5. 字体必须 `font-display: swap`，并给出 `size-adjust` 的 fallback（Anthropic 自己就生成了 `anthropicSans Fallback` 这一层），否则 FOIT 会破坏首屏节奏。

### Dependencies

- **字体不可用**：`anthropicSans / anthropicSerif / anthropicMono` 是 Anthropic 专有字体（`AnthropicSans_Roman_Web.woff2` 等），**不可用于自己的站点**。替代方案（按接近度排序）：
  - Serif → **Georgia**（Anthropic 官方 fallback 就是它，最省事）、**Newsreader**、**Source Serif 4**、**Tiempos Text**（付费，最接近）
  - Sans → **Inter**（最接近的免费几何人文混合体）、**Geist**、**Public Sans**；付费最接近为 **Styrene B**
  - Mono → **JetBrains Mono**、**IBM Plex Mono**
  - 只用 Georgia + system-ui 就能拿到约 70% 的观感，这在纯 CSS 项目里是性价比最高的选择。
- 零 JS 依赖可完成：全部动效为 CSS `@keyframes` + `transition`，无动画库。
- 无需图标字体；图标用内联 SVG，`stroke-width: 1.5`，尺寸 16/20/24。

---

## Aesthetic Checklist

Before considering the design complete, verify these are present:
- [ ] 页面底色是 `#faf9f5` 而不是 `#fff`，且全站灰阶统一偏暖（无 `#f5f5f5` 之类冷灰混入）
- [ ] 大标题是 Serif + 500 字重 + 1.1 行高，且颜色与正文同为 `#141413`
- [ ] 所有卡片/分隔用 0.5px 或 1px 边框表达边界，阴影透明度 ≤ 10%
- [ ] 任意文本容器都设了 `ch` 测度（正文 ≤ 60ch），且 clay 只出现在线/块/图标上，不出现在浅底文字上

</design-system>
