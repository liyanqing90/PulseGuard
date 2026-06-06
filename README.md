# PulseGuard

PulseGuard（脉守）是一个本地运行的 UI/API 探活控制台。它通过 Python `async def check(ctx)` 脚本定义探活规则，支持任务管理、手动执行、定时执行、执行历史、失败留证和 Webhook 告警。

## 本地开发

后端：

```powershell
cd backend
python -m venv ..\.venv
..\.venv\Scripts\python -m pip install -r requirements.txt
..\.venv\Scripts\python -m playwright install chromium
..\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8787 --reload
```

前端：

```powershell
cd frontend
npm install
npm run dev
```

开发访问地址：`http://localhost:5173`。后端 API 默认监听 `http://127.0.0.1:8787`。

## 质量检查

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend\tests -p "test_*.py" -v
cd frontend
npm run build
```

## Docker Compose

```powershell
docker compose up --build
```

默认发布到 `0.0.0.0:8787`，本机访问 `http://localhost:8787`，局域网设备访问 `http://<本机局域网 IP>:8787`。

如只允许本机访问，在 `.env` 中设置：

```env
PULSEGUARD_PUBLISH_HOST=127.0.0.1
PULSEGUARD_HOST=0.0.0.0
PULSEGUARD_PORT=8787
PULSEGUARD_PUBLISH_PORT=8787
PULSEGUARD_ALERT_DETAIL_BASE_URL=http://<本机局域网 IP>:8787
```

## 运行边界

- Docker Compose 默认发布到局域网地址；需要仅本机访问时，将 `PULSEGUARD_PUBLISH_HOST` 改为 `127.0.0.1`。
- 用户脚本固定入口为 `async def check(ctx)`。
- 执行器限制单任务超时、全局并发和同一任务重复并发。
- UI 探活依赖 Playwright Chromium；本地运行前需要安装浏览器。
- Webhook 告警默认关闭，开启后支持飞书、企业微信和钉钉；钉钉支持加签密钥，密钥仅用于服务端签名，不会在设置接口明文回显。
- 设置页支持 Webhook 本地预检，可在不发送外网请求的情况下查看脱敏目标、钉钉加签状态和实际消息载荷。
- 数据保留设置会同时作用于执行历史、截图、Trace 和 Response Body 产物；系统每日自动清理过期数据。
- API 探活脚本可以使用 `await ctx.request()` 按表单中的 Method / Headers / Body / URL 发送请求；需要更多控制时仍可直接使用 `ctx.http.get/post/put/delete/request`。
