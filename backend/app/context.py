from __future__ import annotations

import json
from typing import Any

import httpx
from jsonschema import ValidationError, validate

from .artifacts import ArtifactStore
from .viewport import browser_context_options, normalize_viewport_mode, viewport_for_mode


class RunFailure(Exception):
    """Expected failure raised by a user script or ctx assertion."""


class PulseHttpClient:
    def __init__(self, ctx: "RunContext") -> None:
        self.ctx = ctx
        self._client = httpx.AsyncClient(timeout=ctx.timeout_ms / 1000, follow_redirects=True)
        self.last_response: httpx.Response | None = None

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.ctx.request_snapshot = {
            "method": method.upper(),
            "url": url,
            "headers": dict(kwargs.get("headers") or {}),
            "body": self._snapshot_body(kwargs),
        }
        response = await self._client.request(method, url, **kwargs)
        self.last_response = response
        self.ctx.response_snapshot = self.ctx.response_snapshot_from(response)
        return response

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("PUT", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("DELETE", url, **kwargs)

    async def close(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _snapshot_body(kwargs: dict[str, Any]) -> Any:
        if "json" in kwargs:
            return kwargs["json"]
        if "data" in kwargs:
            return kwargs["data"]
        if "content" in kwargs:
            content = kwargs["content"]
            if isinstance(content, bytes):
                return content.decode("utf-8", errors="replace")
            return content
        return None


class RunContext:
    def __init__(self, check: dict[str, Any], run_id: int, settings: dict[str, Any], artifacts: ArtifactStore) -> None:
        self.check = check
        self.run_id = run_id
        self.settings = settings
        self.artifacts = artifacts
        self.entry_url = check.get("entry_url") or ""
        self.viewport_mode = normalize_viewport_mode(check.get("viewport_mode"))
        self.method = (check.get("method") or "GET").upper()
        self.headers = self._parse_headers(check.get("headers_json") or "{}")
        self.body = check.get("body") or ""
        self.timeout_ms = int(check.get("timeout_ms") or 15000)
        self.logs: list[str] = []
        self.console_messages: list[dict[str, str]] = []
        self.schema_errors: list[str] = []
        self.screenshot_path: str | None = None
        self.trace_path: str | None = None
        self.response_path: str | None = None
        self.request_snapshot: dict[str, Any] | None = None
        self.response_snapshot: dict[str, Any] | None = None
        self.http = PulseHttpClient(self)

        self._playwright: Any = None
        self._browser: Any = None
        self._browser_context: Any = None
        self._trace_started = False
        self._pages: list[Any] = []

    async def request(self, **kwargs: Any) -> httpx.Response:
        request_kwargs = dict(kwargs)
        headers = {**self.headers, **dict(request_kwargs.pop("headers", {}) or {})}

        if not {"json", "data", "content"}.intersection(request_kwargs):
            request_kwargs.update(self._configured_body_kwargs())
        if headers:
            request_kwargs["headers"] = headers

        return await self.http.request(self.method, self.entry_url, **request_kwargs)

    async def new_page(self) -> Any:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RunFailure("Playwright 未安装，请先安装后再执行 UI 探活") from exc

        if self._playwright is None:
            self._playwright = await async_playwright().start()
            browser_type_name = str(self.settings.get("browser_type") or "chromium")
            browser_type = getattr(self._playwright, browser_type_name, None)
            if browser_type is None:
                raise RunFailure(f"不支持的浏览器类型：{browser_type_name}")

            proxy_url = str(self.settings.get("browser_proxy") or "").strip()
            launch_options: dict[str, Any] = {
                "headless": bool(self.settings.get("browser_headless", True)),
            }
            if proxy_url:
                launch_options["proxy"] = {"server": proxy_url}

            self._browser = await browser_type.launch(**launch_options)
            self._browser_context = await self._browser.new_context(**self._browser_context_options())
            await self._browser_context.tracing.start(screenshots=True, snapshots=True, sources=True)
            self._trace_started = True

        page = await self._browser_context.new_page()
        page.set_default_timeout(self.timeout_ms)
        page.on("console", lambda message: self._capture_console(message))
        page.on("requestfailed", lambda request: self.log(f"Network failed: {request.url}"))
        self._pages.append(page)
        return page

    async def expect_visible(self, page: Any, selector: str) -> None:
        try:
            await page.locator(selector).first.wait_for(state="visible", timeout=self.timeout_ms)
        except Exception as exc:
            raise RunFailure(f"元素未出现：{selector}") from exc

    async def expect_hidden(self, page: Any, selector: str) -> None:
        try:
            await page.locator(selector).first.wait_for(state="hidden", timeout=self.timeout_ms)
        except Exception as exc:
            raise RunFailure(f"元素仍然可见：{selector}") from exc

    async def expect_text(self, page: Any, text: str) -> None:
        try:
            await page.get_by_text(text).first.wait_for(state="visible", timeout=self.timeout_ms)
        except Exception as exc:
            raise RunFailure(f"文本未出现：{text}") from exc

    async def screenshot(self, page: Any | None = None, name: str | None = None) -> str:
        target_page = page or (self._pages[-1] if self._pages else None)
        if target_page is None:
            raise RunFailure("当前没有可截图的页面")
        path, relative = self.artifacts.screenshot_target(self.run_id, name or "manual")
        await target_page.screenshot(path=str(path), full_page=True)
        self.screenshot_path = relative
        return relative

    def save_response(self, response: httpx.Response | None = None) -> str:
        target = response or self.http.last_response
        if target is None:
            raise RunFailure("当前没有可保存的响应体")
        payload = self.response_snapshot_from(target, include_body=True)
        self.response_snapshot = payload
        self.response_path = self.artifacts.save_response(self.run_id, payload)
        return self.response_path

    def assert_status(self, response: httpx.Response, expected: int) -> None:
        if response.status_code != expected:
            raise RunFailure(f"HTTP 状态码不匹配：期望 {expected}，实际 {response.status_code}")

    def assert_json_schema(self, data: Any, schema: dict[str, Any]) -> None:
        try:
            validate(instance=data, schema=schema)
        except ValidationError as exc:
            path = ".".join(str(item) for item in exc.path) or "$"
            message = f"JSON Schema 校验失败：{path} {exc.message}"
            self.schema_errors.append(message)
            raise RunFailure(message) from exc

    def fail(self, message: str) -> None:
        raise RunFailure(message)

    def log(self, message: Any) -> None:
        self.logs.append(str(message))

    async def close(self, failed: bool) -> None:
        if failed and self.check.get("type") == "ui" and self._pages and not self.screenshot_path:
            try:
                await self.screenshot(self._pages[-1], "failure")
            except Exception as exc:
                self.log(f"截图保存失败：{exc}")

        if self._browser_context and self._trace_started:
            try:
                if failed:
                    trace_file, relative = self.artifacts.trace_target(self.run_id)
                    await self._browser_context.tracing.stop(path=str(trace_file))
                    self.trace_path = relative
                else:
                    await self._browser_context.tracing.stop()
            except Exception as exc:
                self.log(f"Trace 保存失败：{exc}")
            finally:
                self._trace_started = False

        if failed and self.check.get("type") == "api" and self.http.last_response is not None and not self.response_path:
            try:
                self.save_response(self.http.last_response)
            except Exception as exc:
                self.log(f"响应体保存失败：{exc}")

        if self._browser_context:
            await self._browser_context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        await self.http.close()

    def response_snapshot_from(self, response: httpx.Response, include_body: bool = False) -> dict[str, Any]:
        body_text = response.text
        if not include_body and len(body_text) > 5000:
            body_text = body_text[:5000] + "\n... 响应体已截断，完整内容见产物。"
        return {
            "status_code": response.status_code,
            "url": str(response.url),
            "headers": dict(response.headers),
            "body": body_text,
        }

    def _capture_console(self, message: Any) -> None:
        message_type = str(getattr(message, "type", "") or "")
        message_text = str(getattr(message, "text", "") or "")
        if message_type in {"error", "warning"}:
            self.console_messages.append({"type": message_type, "text": message_text})
            self.log(f"Console {message_type}: {message_text}")

    def _viewport(self) -> dict[str, int]:
        return viewport_for_mode(self.viewport_mode, self.settings)

    def _browser_context_options(self) -> dict[str, Any]:
        return browser_context_options(self.viewport_mode, self._viewport())

    @staticmethod
    def _parse_headers(raw: str) -> dict[str, str]:
        try:
            parsed = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        return {str(key): str(value) for key, value in parsed.items()}

    def _configured_body_kwargs(self) -> dict[str, Any]:
        body = self.body.strip()
        if not body:
            return {}
        try:
            return {"json": json.loads(body)}
        except json.JSONDecodeError:
            return {"content": self.body}
