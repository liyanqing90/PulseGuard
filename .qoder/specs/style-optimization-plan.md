# PulseGuard 样式优化方案

## Context

PulseGuard 是一个本地/LAN 监控操作台，前端使用 React + Ant Design v6 + Vite 构建。当前代码纪律性较高：设计 token 集中在 `designSystem.ts`，CSS 变量集中在 `styles.css`，无 CSS-in-JS，无渐变，无装饰性元素。

**用户痛点**：视觉质感不够精致，需要提升交互和布局品质感。同时存在多处重复 UI 片段需要整合。

**原则**：所有改动走设计系统，优先使用 AntD 组件 props 和主题覆盖，不引入新依赖（除非确实必要），保持运维台的美学风格。

---

## Phase 1: 设计 Token 扩展（基础层）

### 1.1 扩展间距 token

**文件**: `frontend/src/designSystem.ts`

当前 `spacing` 只有 4 级 (6, 10, 16, 24)，CSS 中存在 40+ 处硬编码像素值 (8px, 12px, 14px, 18px, 20px, 32px, 48px)。

扩展为：
```ts
export const spacing = {
  inner: 8,    // 紧凑内边距（Tag 内边距、图标间距）
  xs: 6,
  field: 12,   // 表单字段间距、卡片子区域间距
  sm: 10,
  surface: 14, // 面板/容器内边距
  md: 16,
  lg: 24,
  xl: 32,
  xxl: 48
} as const;
```

### 1.2 添加行高 token

**文件**: `frontend/src/designSystem.ts`

```ts
export const lineHeights = {
  tight: 1.15,    // 指标数字、区块标题
  normal: 1.35,   // 标题、标签
  body: 1.5,      // 正文
  caption: 1.45   // 辅助文字、元数据
} as const;
```

### 1.3 添加 CSS 变量

**文件**: `frontend/src/styles.css` :root 区块

```css
--space-inner: 8px;
--space-field: 12px;
--space-surface: 14px;
--space-xl: 32px;
--space-xxl: 48px;
--lh-tight: 1.15;
--lh-normal: 1.35;
--lh-body: 1.5;
--lh-caption: 1.45;
--surface-hover: color-mix(in srgb, var(--ink) 2.5%, var(--panel));
```

### 1.4 消除 styles.css 中的硬编码像素值

遍历 `styles.css`，将 ~40 处硬编码像素替换为对应 CSS 变量：
- `12px` → `var(--type-caption)` 或 `var(--space-field)`（视上下文）
- `13px` → `var(--type-meta)`
- `14px` → `var(--type-body)` 或 `var(--space-surface)`
- `16px` → `var(--type-title)` 或 `var(--space-md)`
- `32px` → `var(--space-xl)`
- `48px` → `var(--space-xxl)`
- 其他 `8px` → `var(--space-inner)`

---

## Phase 2: 重复组件整合

### 2.1 提取业务标签工具 → `frontend/src/components/shared/businessTags.tsx`

**问题**: 3 处 `failureKindTag` 实现，2 处 `RunnerExecutionTag`，2 处 `runnerSummary`

**新文件 API**:
```tsx
// failureKindTag: 统一三种实现，接受 emptyNode 参数
export function failureKindTag(value: string | null | undefined, emptyNode?: ReactNode): ReactNode

// RunnerExecutionTag: 合并两处相同组件
export function RunnerExecutionTag({ run }: { run: Run }): JSX.Element

// runnerSummary: 移入 utils.ts（纯函数，非组件）
```

**清理清单**:

| 文件 | 删除 |
|------|------|
| `pages/OverviewPage.tsx` | 本地 `failureKindTag` |
| `pages/RunsPage.tsx` | 本地 `RunnerExecutionTag`、`runnerSummary`、`failureKindTag` |
| `components/RunResultPanel.tsx` | 本地 `RunnerExecutionTag`、`runnerSummary`、`failureKindTag` |

`runnerSummary` 移入 `frontend/src/utils.ts`，与 `runnerExecutionMeta` 并列。

### 2.2 提取 MetaField 组件 → `frontend/src/components/shared/MetaField.tsx`

**问题**: 4 处类似的 label-value 展示组件：
- `MetaItem` (RunResultPanel) — 裸 div
- `CheckMeta` (ChecksPage) — 带边框卡片样式
- `HistoryMeta` (RunsPage) — 扁平 div
- `PreviewFact` (SettingsPage) — 带色调支持

**API**:
```tsx
MetaField({
  label: string,
  value: ReactNode,
  variant?: "plain" | "card" | "preview",
  tone?: "default" | "ok" | "muted"
}): JSX.Element
```

CSS 中将 `check-card-meta-item`、`history-card-meta-item`、`alert-preview-fact` 合并为 `.meta-field` 类族。

---

## Phase 3: 视觉精细化

### 3.1 表格质量提升

**文件**: `frontend/src/designSystem.ts` Table 组件覆盖

```ts
Table: {
  borderColor: palette.border,
  headerBg: palette.surfaceMuted,
  headerColor: palette.textMuted,
  headerSplitColor: "transparent",      // 移除列分隔线
  rowHoverBg: palette.primarySoft,       // 替换裸 hex "#f3f7ff"
  cellPaddingBlock: 12,                  // 行纵向间距
  cellPaddingBlockSM: 8
}
```

**文件**: `frontend/src/styles.css`

- 添加 `.cell-numeric` 类用于数值/日期列右对齐 + `font-variant-numeric: tabular-nums`
- 表格空状态 SVG 使用 `color: var(--muted)`
- 确保 `borderBlockColor` 与 `--line` 一致

### 3.2 卡片与面板质感

**文件**: `frontend/src/styles.css`

可点击卡片（check-card、history-card）添加 hover 反馈：
```css
.check-card:hover,
.history-card:hover {
  border-color: var(--line-strong);
  transition: border-color var(--duration-fast) var(--ease-standard);
}
```

无阴影、无 transform — 仅边框变深，符合 DESIGN.md 的 "flat at rest" 原则。

设置面板图标单元格柔化：
```css
.settings-panel-icon {
  background: color-mix(in srgb, var(--accent) 8%, var(--panel-strong));
  color: var(--accent);
}
```

### 3.3 状态指示器精细化

**文件**: `frontend/src/designSystem.ts`

在 `semanticTones` 中补充状态点 (status dot) 色值，确保 `runtime-dot` 等状态点覆盖所有状态 (ok/failed/running/pending/skipped)。

**文件**: `frontend/src/styles.css`

检查 `.status-badge` 类：若使用 `border-radius: 999px`（药丸形），改为 `border-radius: var(--radius-tight)`（紧凑矩形），与 DESIGN.md 的 "compact rectangle with 6px radius" 一致。

### 3.4 微交互增强

**文件**: `frontend/src/styles.css`

- 可点击链接 hover 添加柔和下划线：`text-decoration-color: color-mix(in srgb, var(--accent) 40%, transparent)`
- 按钮焦点态添加平滑过渡：`transition: background-color var(--duration-fast), border-color var(--duration-fast)`
- Spin 组件颜色统一：`.ant-spin .ant-spin-dot-item { color: var(--accent) }`

### 3.5 补充 AntD 组件主题覆盖

**文件**: `frontend/src/designSystem.ts`

当前覆盖了 12 个组件，缺少以下覆盖：

```ts
Descriptions: {
  labelBg: palette.surfaceMuted,
  titleColor: palette.text
},
Segmented: {
  itemSelectedBg: palette.surface,
  trackBg: palette.surfaceMuted
},
Pagination: {
  itemSize: 32,
  itemBg: "transparent"
},
Collapse: {
  headerBg: palette.surfaceMuted,
  contentBg: palette.surface
},
Empty: {
  colorTextDescription: palette.textMuted
},
Skeleton: {
  colorFill: palette.surfaceMuted
},
Form: {
  labelColor: palette.textMuted,
  labelFontSize: 13,
  itemMarginBottom: 18
}
```

---

## Phase 4: 排版与表单品质

### 4.1 排版层级统一

**文件**: `frontend/src/styles.css`

统一各级标题的 CSS 规则：

| 层级 | font-size | font-weight | line-height |
|------|-----------|-------------|-------------|
| 页面标题 | `var(--type-page)` | 600 | `var(--lh-tight)` |
| 区块标题 | `var(--type-section)` | 600 | `var(--lh-normal)` |
| 面板标题 | `var(--type-title)` | 600 | `var(--lh-normal)` |
| 正文 | `var(--type-body)` | 400 | `var(--lh-body)` |
| 辅助文字 | `var(--type-caption)` / `var(--type-meta)` | 400 | `var(--lh-caption)` |

消除 `.settings-panel-header h3`、`.overview-command h2` 等处的硬编码字号，改用 token 变量。

caption/meta 文字添加 `letter-spacing: 0.01em` 提升小字号可读性。

### 4.2 表单质量

**文件**: `frontend/src/styles.css`

- 添加 `.form-section` CSS 模式：相关字段分组，用 `border-top: 1px solid var(--line)` + 区块标题分隔
- 验证错误文字统一为 caption 字号：`.ant-form-item-explain-error { font-size: var(--type-caption) }`

### 4.3 空状态与加载态标准化

**文件**: `frontend/src/styles.css`

```css
.list-empty-state {
  padding: var(--space-xl) var(--space-md);
  text-align: center;
}
.list-empty-state .ant-empty-description {
  color: var(--muted);
  font-size: var(--type-body);
}
```

统一 Skeleton 配置：各处 `paragraph={{ rows: 4 }}` 的 `title.width` 统一为 `"72%"`。

---

## 实施顺序

```
Phase 1 (Token 基础)
  1.1 扩展 spacing token
  1.2 添加 lineHeight token
  1.3 添加 CSS 变量
  1.4 替换 styles.css 硬编码像素值
  → 运行 npm run build 验证

Phase 2 (组件整合)
  2.1 提取 businessTags (failureKindTag, RunnerExecutionTag, runnerSummary)
  2.2 提取 MetaField (MetaItem, CheckMeta, HistoryMeta, PreviewFact)
  → 运行 npm run build 验证

Phase 3 (视觉精细)
  3.1 表格质量 (designSystem.ts Table 覆盖 + CSS)
  3.2 卡片 hover 态 + 面板质感
  3.3 状态指示器
  3.4 微交互
  3.5 补充 AntD 组件覆盖
  → 运行 npm run build 验证

Phase 4 (排版与表单)
  4.1 排版层级统一
  4.2 表单质量
  4.3 空状态/加载态
  → 运行 npm run build 验证
```

---

## 关键文件清单

| 文件 | 改动类型 |
|------|----------|
| `frontend/src/designSystem.ts` | 扩展 token、添加组件覆盖 |
| `frontend/src/styles.css` | 新变量、消除硬编码、hover/micro-interaction CSS、排版统一 |
| `frontend/src/components/shared/businessTags.tsx` | **新建** — failureKindTag, RunnerExecutionTag |
| `frontend/src/components/shared/MetaField.tsx` | **新建** — 统一 label-value 展示 |
| `frontend/src/utils.ts` | 添加 runnerSummary |
| `frontend/src/pages/OverviewPage.tsx` | 删除本地重复，导入共享 |
| `frontend/src/pages/RunsPage.tsx` | 删除本地重复，导入共享 |
| `frontend/src/pages/ChecksPage.tsx` | 删除本地重复，导入共享 |
| `frontend/src/pages/SettingsPage.tsx` | 删除本地重复，导入共享 |
| `frontend/src/components/RunResultPanel.tsx` | 删除本地重复，导入共享 |

---

## 验证方式

1. **构建验证**: `cd frontend && npm run build` — 确保无编译/类型错误
2. **视觉回归**: 启动后端 + 前端，逐页检查：
   - OverviewPage: 指标卡、趋势表、运行时状态
   - ChecksPage: 列表视图、紧凑卡片视图、编辑抽屉
   - RunsPage: 历史表格、筛选器、分页、紧凑视图
   - RunDetailPage: 标签页、证据面板
   - SettingsPage: 表单分组、开关、上传
   - OperationsPage: 标签页切换、表格
3. **交互检查**: 卡片 hover 态、表格行 hover、链接 hover、按钮焦点态
4. **响应式检查**: 在 1180px 和 820px 断点处检查布局无回归
