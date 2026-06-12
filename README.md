# PulseGuard

[简体中文](./README.md) | [English](./README.en.md)

<p align="center">
  <img src="./assets/brand/pulseguard-brand-card.svg" alt="PulseGuard - 本地和局域网 UI/API 探活控制台" width="100%" />
</p>

PulseGuard（脉守）是一个面向本地和局域网的小型 UI/API 探活控制台。它适合团队在内网环境里持续检查后台页面、登录前置流程、健康接口、批处理心跳、证书和基础网络可达性，并把运行历史、失败证据、告警策略和只读状态统一放在一个单实例控制台中管理。

PulseGuard 不是 SaaS、公开状态页、完整 E2E 测试管理平台或 incident/on-call 系统。当前边界是单实例、本地或 LAN 使用，默认 SQLite 持久化。

## 核心能力

- UI/API 探活任务：支持定时执行、手动执行、草稿调试、结构化断言和高级 Python 脚本。
- UI 前置脚本：扫描、草稿调试和正式运行都会先执行 `setup_script`，用于准备登录态、页面前提和业务上下文。
- 规则维护：支持 UI selector 稳定性提示、规则失效检测、API 响应字段预览和一键生成基础断言。
- 批量操作：按类型、标签和启用状态批量执行、启停、调频，并用命中数量防止误操作。
- 运行记录：已保存任务的定时、手动、批量和重跑均属于正式执行，会影响健康状态、成功率与告警；只有编辑器配置试运行不影响状态且不触发告警。
- 可信健康状态：支持健康、疑似故障、故障、疑似恢复、未知、观测陈旧、停用，Runner 异常不会误报为目标故障。
- 证据保留：失败时保存错误摘要、截图、Trace 和 Response Body；成功 API 响应默认只保留摘要。
- 执行节点追踪：记录本机和子节点名称、地址、网络区域、浏览器版本，并支持启停、认证心跳、可用状态和状态列表。
- 失败归因：区分被探测目标失败和 Runner 执行环境失败，便于判断是业务/断言问题还是探针环境问题。
- 告警策略：支持全局、标签级、任务级告警策略，覆盖冷却、恢复通知和通知渠道。
- 运维审计：记录任务、设置、批量操作、配置导入和版本恢复等关键操作。
- 任务版本：保存任务变更快照，支持查看和恢复历史版本。
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

## UI 浏览器生命周期

UI 任务支持 `chromium`、`firefox`、`webkit` 三类 Playwright browser type。系统设置里可以分别配置：

- `enabled_browser_types`：允许任务选择和执行的 browser type。
- `prewarmed_browser_types`：后端启动或设置变更时自动预热的 browser type，必须是已启用类型，可以多选或为空。
- `browser_pool_sizes`：每个 browser type 独立的空 `BrowserContext` 储备数量，单类默认 5。

每个预热的 browser type 会保留 1 个 Playwright browser 进程，并按该 type 的 pool size 预创建空 `BrowserContext`。UI 任务会独占租用 1 个 context/page；任务结束只关闭 context，不关闭 browser，资源池随后补齐空 context。Web 与 H5 尺寸通过 context options 区分，同一个 browser 进程下可以并发运行不同 viewport 的任务。

`browser_type` 只对 UI 任务生效。任务执行时先解析执行节点，再在每个节点内解析 browser type；节点多选和 browser type 多选会按节点 × browser type 矩阵创建运行记录。只有“已启用且该节点已安装”的 browser type 会实际执行，缺失或未启用的组合会记录为 Runner 异常。启用新的 browser type 后，主节点会请求本机和可用子节点安装对应 Playwright browser，子节点也会在健康检查中上报当前已安装和可用的 browser type。

## 多运行节点

PulseGuard 默认保留并启用内置 `local` 节点。子节点是独立部署的执行服务，只负责暴露受 token 保护的健康检查和执行接口、执行主节点下发的任务、回传运行结果和证据文件；子节点不会主动注册到主节点、不会启动调度器、不会写主节点数据库，也不会发送告警。

创建子节点：

1. 在子节点服务器上用 worker 命令部署并启动服务，终端会输出当前子节点地址和认证 token。
2. 在主节点打开“系统设置 > 执行配置”。
3. 点击“新增子节点”，填写节点名称、子节点可被主节点访问的地址、网络区域和终端输出的认证 token。这个操作只在主节点保存节点记录，不会让子节点主动注册。
4. 点击“测试连接”确认主节点可以访问子节点 `/api/worker/health`。
5. 在任务详情或编辑抽屉中选择“多选并行”并勾选节点，或选择“轮询所有启用节点”。

结果展示：

- 多选并行时，同一次触发会为每个节点创建运行记录，并写入同一个 `run_group_id`；如果 UI 任务同时选择多个 browser type，会按节点和 browser type 的矩阵创建记录。
- 运行详情和运行抽屉会在“多节点执行结果”中展示同组所有节点、browser type、节点执行状态、运行状态、失败来源、耗时、错误摘要和证据文件入口；点击下方节点详情 Tab 可在当前详情内切换不同节点和 browser type 的完整结果。
- 多节点聚合只更新一次任务健康状态：任一可用节点出现目标失败/超时，本轮任务失败；全部可用节点成功才算成功；节点不可用只记录 `failure_kind=runner`，不计入目标失败。
- 运行记录页可按执行节点筛选；需要按一次触发查看全量节点结果时，可用 `run_group_id` 查询同组运行记录。

下面的子节点启动命令都在子节点服务器执行，不在主节点执行。主节点只负责在页面里手动添加该子节点的地址和 token。

子节点一行启动（源码方式，不需要前端）：

```powershell
uv run python -m backend.app.worker --host 0.0.0.0 --port 8788
```

需要命名或标记区域时再追加 `--name office-worker-1 --region office-lan`。启动后会打印：

```text
PulseGuard worker node is ready.
  name: office-worker-1
  address: set this in the main console, for example http://<child-node-ip>:8788
  region: office-lan
  token: pgrn_xxx
  token_source: ...
```

`address` 不需要由子节点自动决定。主节点页面添加子节点时，填写主节点实际能访问到的地址，例如 `http://<子节点 IP>:8788`。

如果没有显式传入 `--token` 或 `PULSEGUARD_WORKER_TOKEN`，worker 会把 token 保存到 `PULSEGUARD_WORKER_TOKEN_FILE`，默认是数据目录下的 `worker-token`，后续重启会复用同一个 token。

Docker 子节点不需要复制完整源码，也不建议默认在子节点从源码构建。推荐直接运行预构建 worker 镜像；这样启动时只拉取 worker 镜像，不会在子节点额外拉取 `uv` 镜像或执行 `uv sync`。

Windows PowerShell 直连 GitHub 可直接执行：

```powershell
mkdir pulseguard-worker -Force; cd pulseguard-worker
Invoke-WebRequest -UseBasicParsing "https://raw.githubusercontent.com/liyanqing90/PulseGuard/codex/github-publish/docker-compose.worker.yml" -OutFile docker-compose.worker.yml
$env:PULSEGUARD_WORKER_NAME = $env:COMPUTERNAME
$env:PULSEGUARD_WORKER_REGION = "default"
$env:PULSEGUARD_WORKER_IMAGE = "ghcr.io/liyanqing90/pulseguard-worker:codex-github-publish"
$env:COMPOSE_PROJECT_NAME = "pulseguard-worker"
docker compose -f docker-compose.worker.yml pull
docker compose -f docker-compose.worker.yml up -d
docker update --restart unless-stopped pulseguard-worker
docker logs --tail 80 pulseguard-worker
```

Linux shell 可用：

```sh
mkdir -p pulseguard-worker && cd pulseguard-worker
curl -fsSL "https://raw.githubusercontent.com/liyanqing90/PulseGuard/codex/github-publish/docker-compose.worker.yml" -o docker-compose.worker.yml
export PULSEGUARD_WORKER_NAME="$(hostname)"
export PULSEGUARD_WORKER_REGION="default"
export PULSEGUARD_WORKER_IMAGE="ghcr.io/liyanqing90/pulseguard-worker:codex-github-publish"
export COMPOSE_PROJECT_NAME="pulseguard-worker"
docker compose -f docker-compose.worker.yml pull
docker compose -f docker-compose.worker.yml up -d
docker update --restart unless-stopped pulseguard-worker
docker logs --tail 80 pulseguard-worker
```

命令默认后台启动容器并设置 Docker 自启策略。启动后用 `docker logs --tail 80 pulseguard-worker` 查看认证 token；需要持续观察日志时再执行 `docker logs -f pulseguard-worker`。默认 `docker-compose.worker.yml` 不包含源码构建配置，不会隐式访问 GitHub。

worker 会在 `/api/worker/health` 上报版本、构建 SHA、当前镜像和是否启用平台更新。管理平台“执行节点”列表会展示这些信息。

如果希望管理平台可以主动向子节点推送更新，需要显式启用 updater profile。updater 会挂载宿主机 Docker socket，因此只允许更新当前 `pulseguard-worker` 服务，不支持任意命令：

```powershell
$env:COMPOSE_PROJECT_NAME = "pulseguard-worker"
$env:COMPOSE_PROFILES = "updater"
$env:PULSEGUARD_WORKER_UPDATER_URL = "http://pulseguard-worker-updater:8790"
$env:PULSEGUARD_WORKER_UPDATE_IMAGE = "ghcr.io/liyanqing90/pulseguard-worker:codex-github-publish"
docker compose -f docker-compose.worker.yml pull
docker compose -f docker-compose.worker.yml up -d
docker update --restart unless-stopped pulseguard-worker pulseguard-worker-updater
```

启用后，主节点“执行节点”列表会显示“支持平台更新”，可以点击“更新节点”。更新过程由子节点 updater 执行：拉取目标镜像、重建 worker、检查 `/api/worker/health`，失败时尝试回滚到旧镜像。

中国内地服务器访问 GitHub Raw 较慢或不稳定时，可以使用加速链接下载 compose 文件。这个加速链接只用于中国内地网络场景，并且只加速 compose 文件下载，不加速容器镜像拉取：

```powershell
mkdir pulseguard-worker -Force; cd pulseguard-worker
Invoke-WebRequest -UseBasicParsing "https://gh-proxy.org/https://raw.githubusercontent.com/liyanqing90/PulseGuard/codex/github-publish/docker-compose.worker.yml" -OutFile docker-compose.worker.yml
$env:PULSEGUARD_WORKER_NAME = $env:COMPUTERNAME
$env:PULSEGUARD_WORKER_REGION = "default"
$env:PULSEGUARD_WORKER_IMAGE = "ghcr.io/liyanqing90/pulseguard-worker:codex-github-publish"
$env:COMPOSE_PROJECT_NAME = "pulseguard-worker"
docker compose -f docker-compose.worker.yml pull
docker compose -f docker-compose.worker.yml up -d
docker update --restart unless-stopped pulseguard-worker
docker logs --tail 80 pulseguard-worker
```

如果中国内地服务器拉取 GHCR 镜像较慢，推荐先把 `ghcr.io/liyanqing90/pulseguard-worker:codex-github-publish` 同步到内网或国内镜像仓库，再把命令里的 `PULSEGUARD_WORKER_IMAGE` 替换成你的镜像地址。

如果子节点服务器不能访问 GitHub，建议在可访问的位置放一份定制的 `docker-compose.worker.yml`，让这个 compose 文件直接指向内网镜像。子节点服务器只需要下载这份 compose 文件再启动：

```sh
curl -fsSL "http://<可访问地址>/docker-compose.worker.yml" -o docker-compose.worker.yml
docker compose -f docker-compose.worker.yml up -d
docker update --restart unless-stopped pulseguard-worker
docker logs --tail 80 pulseguard-worker
```

只有在没有预构建镜像或内网镜像时，才建议使用源码构建备用路径。该路径会拉取 Playwright 基础镜像和 `uv` 镜像，国内网络下通常更慢：

```powershell
mkdir pulseguard-worker -Force; cd pulseguard-worker
Invoke-WebRequest -UseBasicParsing "https://raw.githubusercontent.com/liyanqing90/PulseGuard/codex/github-publish/docker-compose.worker.yml" -OutFile docker-compose.worker.yml
Invoke-WebRequest -UseBasicParsing "https://raw.githubusercontent.com/liyanqing90/PulseGuard/codex/github-publish/docker-compose.worker.build.yml" -OutFile docker-compose.worker.build.yml
$env:PULSEGUARD_WORKER_NAME = $env:COMPUTERNAME
$env:PULSEGUARD_WORKER_REGION = "default"
$env:PULSEGUARD_WORKER_BUILD_CONTEXT = "https://github.com/liyanqing90/PulseGuard.git#codex/github-publish"
$env:COMPOSE_PROJECT_NAME = "pulseguard-worker"
docker compose -f docker-compose.worker.yml -f docker-compose.worker.build.yml up --build -d
docker update --restart unless-stopped pulseguard-worker
docker logs --tail 80 pulseguard-worker
```

源码构建时如需使用内网或国内镜像仓库，可以在构建前覆盖基础镜像：

```powershell
$env:PULSEGUARD_UV_IMAGE = "registry.example.com/astral-sh/uv:0.9.30"
$env:PULSEGUARD_PLAYWRIGHT_IMAGE = "registry.example.com/playwright/python:v1.49.1-noble"
```

Token 存储与刷新：

- Docker 子节点默认把 token 存到容器内 `/app/data/worker-token`，`docker-compose.worker.yml` 已经把 `/app/data` 挂到 `pulseguard-worker-data` 卷，容器重建后 token 仍会保留。
- 查看当前 token：

```sh
docker compose -f docker-compose.worker.yml exec pulseguard-worker python -m app.worker --show-token
```

- 刷新 token 并重启 worker：

```sh
docker compose -f docker-compose.worker.yml exec pulseguard-worker python -m app.worker --rotate-token
docker compose -f docker-compose.worker.yml restart pulseguard-worker
```

- 如果 worker 容器当前没有运行，也可以直接用同一个数据卷刷新：

```sh
docker compose -f docker-compose.worker.yml run --rm pulseguard-worker python -m app.worker --rotate-token
```

- 源码方式刷新 token：

```powershell
uv run python -m backend.app.worker --rotate-token --token-file data/worker-token
```

刷新 token 后，必须回到主节点“系统设置 > 执行配置”，对该子节点执行“更新认证”，填入新 token，然后再点“测试连接”确认可用。

网络要求：

- 主节点必须能访问子节点的 `/api/worker/health` 和 `/api/worker/run`。
- 子节点接口使用 `Authorization: Bearer <token>` 认证。
- 子节点不需要配置主节点地址，也不会主动访问主节点；关联动作由主节点页面手动添加节点完成。
- 远程截图、Trace 和 Response Body 通过 JSON base64 回传主节点，单个文件超过大小上限会记录日志但不会伪造成功。
- 手动停用的节点不会触发不可用告警；启用节点健康检查失败或派发失败时，同一节点只告警一次，恢复可用后重置。

常见排障：

- 主节点“测试连接”失败：检查子节点地址是否从主节点可达，端口是否放行，worker 是否用 `0.0.0.0` 或正确网卡监听。
- 节点不可用：检查主节点保存的地址和 token 是否与子节点终端输出一致；token 更新后需要在平台“更新认证”里同步。
- 任务记录显示 Runner 异常：这类记录的 `failure_kind=runner`，不会按目标失败累计；优先查看节点可用状态和子节点日志。

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
.\scripts\deploy.ps1
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
- SQLite 支持在线备份和恢复，备份位于 `data/backups/`。
- 截图、Trace、Response Body 和归档摘要位于 `reports/`。
- 环境变量、Webhook、钉钉密钥、只读令牌、常见认证 Header 和 Cookie 会在公开设置、运行记录和只读出口中脱敏。
- 用户自定义 Python 探活脚本是可信本地工具能力，不是安全沙箱。
- 录制器不是当前主线；多步骤探活优先使用模板、前置脚本和结构化规则。

## 常用接口

- `GET /api/health`：健康检查
- `GET /api/metrics.json`：JSON 指标
- `GET /api/metrics`：Prometheus 指标
- `GET /api/read-only/snapshot`：只读快照，需要配置只读令牌
- `GET /api/runners` / `POST /api/runners`：执行节点列表和创建
- `POST /api/runners/{runner_id}/update` / `GET /api/runners/{runner_id}/update-status`：主节点向子节点推送受控镜像更新和查询更新状态
- `POST /api/runners/heartbeat`：旧版 Runner 主动心跳兼容接口，新子节点默认不需要配置
- `GET /api/worker/health` / `POST /api/worker/run`：子节点健康检查和执行入口
- `POST /api/worker/browser-types/install`：主节点请求子节点安装已启用的 Playwright browser type
- `POST /api/worker/update` / `GET /api/worker/update-status`：子节点受控更新入口，需要启用 updater profile
- `GET /api/runs?runner_id=...`：按执行节点筛选运行记录
- `GET /api/runs?run_group_id=...`：按一次多节点触发分组查看所有节点运行结果
- `GET /api/runs-page?run_group_id=...`：分页查看同组运行结果
- `GET /api/runs/{id}`：查看基于执行快照的运行详情；UI 运行只附带当次快照中的基础请求信息（URL、页面模式、超时），API 运行保留 request/response snapshots，不再重新加载当前任务定义
- `POST /api/heartbeats/{key}`：被动心跳上报

## 目录结构

```text
backend/                 FastAPI 后端、存储、运行器、告警、测试
frontend/                React 前端、页面、业务组件、设计样式
data/                    SQLite 数据目录
reports/                 截图、Trace、Response Body 和归档摘要
docs/                    路线图和设计/功能文档
Dockerfile               主节点生产镜像构建
Dockerfile.worker        子节点独立 worker 镜像构建
Dockerfile.worker-updater 子节点 updater 镜像构建
docker-compose.yml       主节点单实例部署
docker-compose.worker.yml 子节点 worker 部署
pyproject.toml           后端依赖定义
uv.lock                  后端依赖锁定
```

## 当前发展方向

近期重点是把 PulseGuard 做成稳定的内网探活工作台：

- 优先强化结构化规则、扫描候选、失败摘要和配置迁移。
- 保持 SQLite 单实例模型，除非部署形态升级到多实例、多用户或高容量历史分析。
- 冻结 AI 规则生成、Playwright 用例导入、录制器和测试报告矩阵；持续打磨远程节点调度、证据回传和可用性告警。
- 持续强化观测可信度、异常收敛、告警可靠性、证据保留和单实例长期运行能力。

## 品牌资产

PulseGuard 的基础品牌资产位于 `assets/brand/`：

- `pulseguard-mark.svg`：浅底项目图标，适合 favicon、应用侧栏和小尺寸场景。
- `pulseguard-brand-card.svg`：README 和项目介绍使用的横版品牌展示图。
- `pulseguard-brand-card.en.svg`：英文 README 和英文项目介绍使用的横版品牌展示图。
- `pulseguard-logo-concept.png`：使用 imagegen 生成的浅底概念参考，正式主标识以 SVG 文件为准。

品牌图形使用项目设计系统里的浅色面板、控制蓝和状态绿，不使用深色 icon 背景、渐变或玻璃拟态。

## 开源协议

PulseGuard 使用 [Apache License 2.0](./LICENSE) 开源。你可以商用、修改和再分发，但必须按协议要求保留版权、许可证和项目署名信息。

再分发或基于本项目修改发布时，请保留：

- [LICENSE](./LICENSE)
- [NOTICE](./NOTICE)
- 项目名称 `PulseGuard`
- 原始仓库链接 `https://github.com/liyanqing90/PulseGuard`
