# PulseGuard Latest Version Video Script

## Format

- Duration: 44 seconds
- Aspect: 16:9, 1920x1080
- Language: Chinese on-screen copy
- Tone: calm, technical, operational
- Visual system: PulseGuard "Operations Ledger"; cool neutral canvas, restrained control blue, flat bordered panels, tabular numeric data
- Non-goals: no SaaS marketing tone, no generic AI dashboard, no gradients, no glassmorphism, no fake hero illustration

## Narrative

PulseGuard is no longer just a task list. The latest version presents a local/LAN operations console for UI/API probes: structured checks, failure evidence, runner attribution, alert policy, audit, read-only status, metrics, config migration, and CLI/CI.

## Scenes

### 1. Opening: Local Probe Console

Time: 0.0s-5.0s

On-screen:
- PulseGuard
- 内网 UI/API 探活工作台
- 本地 / 局域网 · SQLite · FastAPI · React

Voiceover/caption:
PulseGuard 面向本地和局域网，把 UI 与 API 探活放进一个稳定的运维控制台。

Visual:
A quiet operations dashboard layout fades in: sidebar, task table, status strip, and small metric tiles.

### 2. Task Authoring: Structured First

Time: 5.0s-11.0s

On-screen:
- 结构化规则优先
- UI 扫描候选 · API 字段预览 · 前置脚本
- 复杂流程再使用 Python 脚本

Voiceover/caption:
创建任务时优先使用结构化断言。UI 可以扫描元素，API 可以从响应字段生成规则；登录和多步骤流程再交给前置脚本。

Visual:
Two panels slide into a workbench: UI element selector on the left, API JSON field tree on the right. Rule chips attach to each panel.

### 3. Failure Evidence: Preserve the Scene

Time: 11.0s-18.0s

On-screen:
- 失败不是一条错误
- 截图 · Trace · Response Body
- 对比最近成功运行，生成脱敏摘要

Voiceover/caption:
失败结果保留现场证据：截图、Trace、响应体，并和最近成功运行对比，让定位从猜测变成可复盘。

Visual:
A run detail panel expands. Evidence cards appear with screenshot, trace, response, comparison fields, and a short failure summary.

### 4. Execution Plane: Queue and Runner Awareness

Time: 18.0s-25.0s

On-screen:
- 执行面有边界
- 全局并发 · UI 浏览器并发 · 队列容量
- Runner 名称、地址、区域、浏览器版本

Voiceover/caption:
Runner 不会无限拉起浏览器。全局并发、UI 并发和队列容量一起保护执行面，每次运行都记录执行位置和浏览器环境。

Visual:
A queue lane animates tasks into limited runner slots. Excess tasks become skipped/queued state chips, not uncontrolled Chrome processes.

### 5. Alert and Governance

Time: 25.0s-32.0s

On-screen:
- 告警按边界收敛
- 全局策略 · 标签策略 · 任务策略
- 冷却、恢复通知、通知渠道

Voiceover/caption:
告警策略按全局、标签和任务分层覆盖，支持冷却和恢复通知；密钥、Webhook 与运行详情默认脱敏。

Visual:
Policy rows stack from global to tag to task. A notification preview shows status only, with secrets masked.

### 6. Operations Surface

Time: 32.0s-38.0s

On-screen:
- 运维面板
- 审计事件 · 任务版本 · 归档摘要
- 配置导出、预检、导入

Voiceover/caption:
运维页集中审计、任务版本恢复和归档摘要。配置可以脱敏导出、导入预检，再纳入 Git 管理。

Visual:
Audit table, version timeline, archive metrics, and config import preview align into one ledger-style grid.

### 7. Read-only and CI Outputs

Time: 38.0s-44.0s

On-screen:
- 面向内网，也面向流水线
- 状态页 · JSON 指标 · Prometheus · CLI/CI
- PulseGuard：稳定、可复盘、可迁移

Voiceover/caption:
对内提供只读状态页和指标出口，对流水线提供 CLI 入口。PulseGuard 保持单实例边界，但把探活工作做完整。

Visual:
Four endpoint cards connect to status page, metrics, Prometheus, and CLI. Final lockup returns to PulseGuard wordmark.

