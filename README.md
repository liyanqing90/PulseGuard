# PulseGuard

PulseGuard（脉守）是一个面向本地和局域网的小型 UI/API 探活控制台。它适合团队在内网环境里持续检查后台页面、登录前置流程、健康接口、批处理心跳、证书和基础网络可达性，并把运行历史、失败证据、告警策略和只读状态统一放在一个单实例控制台中管理。

PulseGuard 不是 SaaS、公开状态页、完整 E2E 测试管理平台或 incident/on-call 系统。当前边界是单实例、本地或 LAN 使用，默认 SQLite 持久化。

## 核心能力

- UI/API 探活任务：支持定时执行、手动执行、草稿调试、结构化断言和高级 Python 脚本。
- UI 前置脚本：扫描、草稿调试和正式运行都会先执行 `setup_script`，用于准备登录态、页面前提和业务上下文。
- 规则维护：支持 UI selector 稳定性提示、规则失效检测、API 响应字段预览和一键生成基础断言。
- 批量操作：按类型、标签和启用状态批量执行、启停、调频，并用命中数量防止误操作。
- 运行历史：保存状态、耗时、错误摘要、截图、Trace、Response Body、最近成功对比和失败摘要。
- Runner 追踪：记录本机 Runner 名称、地址、网络区域、浏览器版本，并支持 Runner 心跳和状态列表。
- 失败归因：区分被探测目标失败和 Runner 执行环境失败，便于判断是业务/断言问题还是探针环境问题。
- 告警策略：支持全局、标签级、任务级告警策略，覆盖冷却、恢复通知和通知渠道。
- 运维审计：记录任务、设置、批量操作、配置导入和版本恢复等关键操作。
- 任务版本：保存任务变更快照，支持查看和恢复历史版本。
- 内网状态页：展示脱敏后的任务状态、最近异常、运行指标和维护公告。
- 只读出口：提供只读快照、JSON 指标和 Prometheus 指标。
- 配置迁移：支持配置导出、脱敏导出、导入预检和应用导入，可把配置 JSON 纳入 Git 管理。
- CLI/CI：支持按任务 ID、类型或标签运行探活，并用 exit code 表达流水线结果。
- 扩展探活：通过模板和 `ctx` helper 支持被动心跳、TLS 到期、HTTP keyword/redirect/asset、TCP、DNS 等检查。

## 技术栈

- Backend: FastAPI, SQLite, Playwright Python, `uv`
- Frontend: React, TypeScript, Vite, Ant Design
- Runtime: Docker Compose 或本地开发进程
- Persistence: SQLite + 本地 `data/`、`reports/`

## 快速启动

推荐用 Docker Compose 运行完整生产构建：

```powershell
docker compose up --build -d
```

默认发布到 `0.0.0.0:8787`：

- 本机访问：`http://127.0.0.1:8787`
- 局域网访问：`http://<本机局域网 IP>:8787`

常用检查：

```powershell
docker compose ps
docker compose logs --tail 80 pulseguard
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8787/api/health
```

如只允许本机访问，可在 `.env` 中设置：

```env
PULSEGUARD_PUBLISH_HOST=127.0.0.1
PULSEGUARD_HOST=0.0.0.0
PULSEGUARD_PORT=8787
PULSEGUARD_PUBLISH_PORT=8787
PULSEGUARD_ALERT_DETAIL_BASE_URL=http://127.0.0.1:8787
```

## 本地开发

后端依赖使用 `uv`：

```powershell
uv sync
uv run python -m playwright install chromium
uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8787 --reload
```

前端依赖使用 npm：

```powershell
cd frontend
npm ci
npm run dev
```

前端默认开发地址是 `http://127.0.0.1:5173`。如需要指定端口和后端代理：

```powershell
cd frontend
$env:VITE_DEV_API_TARGET="http://127.0.0.1:8787"
npm run dev -- --host 127.0.0.1 --port 5175
```

## 验证命令

后端：

```powershell
uv run python -m unittest discover -s backend/tests -p 'test_*.py' -v
```

前端：

```powershell
cd frontend
npm run build
```

Docker：

```powershell
uv lock --check
docker compose build
docker compose up -d
```

## 脚本任务入口

高级脚本使用固定入口：

```python
async def check(ctx):
    response = await ctx.request()
    ctx.assert_status(response, 200)
```

UI 任务可以先用 `setup_script` 准备页面前提：

```python
async def setup(ctx):
    page = await ctx.new_page()
    await page.goto(ctx.entry_url)
    return page
```

结构化 UI/API 断言存在时，不强制编写高级脚本。复杂登录、多窗口或业务分支仍可使用脚本模式。

## 数据与安全边界

- 默认使用 SQLite，数据库文件位于 `data/`。
- 截图、Trace、Response Body 和归档摘要位于 `reports/`。
- 环境变量、Webhook、钉钉密钥、只读令牌、常见认证 Header 和 Cookie 会在公开设置、运行记录、只读出口和状态页中脱敏。
- 用户自定义 Python 探活脚本是可信本地工具能力，不是安全沙箱。
- 内网状态页只展示脱敏摘要，不暴露脚本、Headers、Webhook、环境变量、响应体、错误堆栈或 Runner 拓扑。
- 录制器不是当前主线；多步骤探活优先使用模板、前置脚本和结构化规则。

## 常用接口

- `GET /api/health`：健康检查
- `GET /api/status-page`：内网状态页数据
- `GET /api/metrics.json`：JSON 指标
- `GET /api/metrics`：Prometheus 指标
- `GET /api/read-only/snapshot`：只读快照，需要配置只读令牌
- `POST /api/runners/heartbeat`：Runner 心跳
- `POST /api/heartbeats/{key}`：被动心跳上报

## 目录结构

```text
backend/                 FastAPI 后端、存储、运行器、告警、测试
frontend/                React 前端、页面、业务组件、设计样式
data/                    SQLite 数据目录
reports/                 截图、Trace、Response Body 和归档摘要
docs/                    路线图和设计/功能文档
Dockerfile               生产镜像构建
docker-compose.yml       单实例部署
pyproject.toml           后端依赖定义
uv.lock                  后端依赖锁定
```

## 当前发展方向

近期重点是把 PulseGuard 做成稳定的内网探活工作台：

- 优先强化结构化规则、扫描候选、失败摘要和配置迁移。
- 保持 SQLite 单实例模型，除非部署形态升级到多实例、多用户或高容量历史分析。
- AI 辅助生成规则和 Playwright 用例导入属于后续增强，必须默认脱敏、用户确认后保存。
- 录制器仅作为远期观察项，不进入当前主线。
