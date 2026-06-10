from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

from .variables import resolve_text


class ResourcePoolError(Exception):
    """Expected failure while preparing shared runner resources."""


@dataclass(frozen=True)
class BrowserLaunchConfig:
    browser_type: str
    headless: bool
    proxy_url: str

    @classmethod
    def from_settings(cls, settings: dict[str, Any]) -> "BrowserLaunchConfig":
        return cls(
            browser_type=str(settings.get("browser_type") or "chromium"),
            headless=bool(settings.get("browser_headless", True)),
            proxy_url=resolve_text(settings.get("browser_proxy") or "", settings).strip(),
        )


@dataclass(eq=False)
class BrowserLease:
    browser: Any
    version: str
    config: BrowserLaunchConfig


class HttpClientPool:
    def __init__(self, size: int) -> None:
        self._target_size = max(1, int(size))
        self._clients: set[httpx.AsyncClient] = set()
        self._available: asyncio.Queue[httpx.AsyncClient] = asyncio.Queue()
        self._lock = asyncio.Lock()
        self._closing = False

    async def start(self) -> None:
        async with self._lock:
            self._closing = False
            await self._fill_locked()

    async def resize(self, size: int) -> None:
        to_close: list[httpx.AsyncClient] = []
        async with self._lock:
            self._target_size = max(1, int(size))
            self._closing = False
            await self._fill_locked()
            to_close.extend(self._drain_idle_locked(remove_all=False))
        await _close_http_clients(to_close)

    @asynccontextmanager
    async def client(self) -> AsyncIterator[httpx.AsyncClient]:
        await self.start()
        client = await self._available.get()
        close_client = False
        try:
            yield client
        finally:
            async with self._lock:
                close_client = self._closing or client.is_closed or len(self._clients) > self._target_size
                if close_client:
                    self._clients.discard(client)
                else:
                    self._available.put_nowait(client)
            if close_client:
                await client.aclose()
            if not self._closing:
                await self.start()

    async def shutdown(self) -> None:
        async with self._lock:
            self._closing = True
            to_close = self._drain_idle_locked(remove_all=True)
        await _close_http_clients(to_close)

    def snapshot(self) -> dict[str, int]:
        ready = self._available.qsize()
        total = len(self._clients)
        return {
            "limit": self._target_size,
            "ready": ready,
            "in_use": max(0, total - ready),
            "total": total,
        }

    async def _fill_locked(self) -> None:
        while not self._closing and len(self._clients) < self._target_size:
            client = httpx.AsyncClient(follow_redirects=True)
            self._clients.add(client)
            self._available.put_nowait(client)

    def _drain_idle_locked(self, *, remove_all: bool) -> list[httpx.AsyncClient]:
        to_close: list[httpx.AsyncClient] = []
        while not self._available.empty() and (remove_all or len(self._clients) > self._target_size):
            client = self._available.get_nowait()
            self._clients.discard(client)
            to_close.append(client)
        return to_close


class BrowserPool:
    def __init__(self, size: int) -> None:
        self._target_size = max(1, int(size))
        self._leases: set[BrowserLease] = set()
        self._available: asyncio.Queue[BrowserLease] = asyncio.Queue()
        self._lock = asyncio.Lock()
        self._closing = False
        self._config: BrowserLaunchConfig | None = None
        self._playwright: Any = None
        self._last_error = ""

    async def start(self, settings: dict[str, Any]) -> None:
        await self.resize(self._target_size, settings)

    async def resize(self, size: int, settings: dict[str, Any]) -> None:
        config = self._config_from_settings(settings)
        async with self._lock:
            self._target_size = max(1, int(size))
            self._closing = False
            self._config = config
            to_close = self._drain_idle_locked(config=config, remove_all=False)
        await self._close_leases(to_close)
        async with self._lock:
            if self._closing or self._config != config:
                return
            await self._fill_locked(config)

    async def acquire(self, settings: dict[str, Any]) -> BrowserLease:
        config = self._config_from_settings(settings)
        try:
            await self.resize(self._target_size, settings)
        except ResourcePoolError:
            if self._available.empty():
                raise
        lease = await self._available.get()
        if lease.config != config:
            await self.release(lease, healthy=False)
            raise ResourcePoolError(self._last_error or "浏览器池没有可用实例")
        return lease

    async def release(self, lease: BrowserLease, *, healthy: bool = True) -> None:
        to_close: list[BrowserLease] = []
        refill_settings: dict[str, Any] | None = None
        async with self._lock:
            stale = (
                self._closing
                or not healthy
                or lease.config != self._config
                or not self._browser_connected(lease.browser)
                or len(self._leases) > self._target_size
            )
            if stale:
                self._leases.discard(lease)
                to_close.append(lease)
            else:
                self._available.put_nowait(lease)
            if not self._closing and self._config is not None and len(self._leases) < self._target_size:
                refill_settings = settings_from_config(self._config)
        await self._close_leases(to_close)
        if refill_settings is not None:
            try:
                await self.resize(self._target_size, refill_settings)
            except ResourcePoolError:
                pass
        await self._stop_playwright_if_idle()

    async def shutdown(self) -> None:
        async with self._lock:
            self._closing = True
            to_close = self._drain_idle_locked(config=self._config, remove_all=True)
        await self._close_leases(to_close)
        await self._stop_playwright_if_idle()

    def snapshot(self) -> dict[str, Any]:
        ready = self._available.qsize()
        total = len(self._leases)
        return {
            "limit": self._target_size,
            "ready": ready,
            "in_use": max(0, total - ready),
            "total": total,
            "error": self._last_error,
        }

    async def _fill_locked(self, config: BrowserLaunchConfig) -> None:
        while not self._closing and len(self._leases) < self._target_size:
            lease = await self._launch_locked(config)
            self._leases.add(lease)
            self._available.put_nowait(lease)
        self._last_error = ""

    async def _launch_locked(self, config: BrowserLaunchConfig) -> BrowserLease:
        try:
            playwright = await self._ensure_playwright_locked()
            browser_type = getattr(playwright, config.browser_type, None)
            if browser_type is None:
                raise ResourcePoolError(f"不支持的浏览器类型：{config.browser_type}")
            launch_options: dict[str, Any] = {"headless": config.headless}
            if config.proxy_url:
                launch_options["proxy"] = {"server": config.proxy_url}
            browser = await browser_type.launch(**launch_options)
            raw_version = getattr(browser, "version", "")
            if callable(raw_version):
                raw_version = raw_version()
            version = " ".join(part for part in (config.browser_type, str(raw_version or "").strip()) if part)
            return BrowserLease(browser=browser, version=version, config=config)
        except ResourcePoolError as exc:
            self._last_error = str(exc)
            raise
        except ImportError as exc:
            self._last_error = "Playwright 未安装，请先安装后再执行 UI 探活"
            raise ResourcePoolError(self._last_error) from exc
        except Exception as exc:
            self._last_error = f"浏览器环境启动失败：{exc}"
            raise ResourcePoolError(self._last_error) from exc

    async def _ensure_playwright_locked(self) -> Any:
        if self._playwright is None:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
        return self._playwright

    def _drain_idle_locked(self, *, config: BrowserLaunchConfig | None, remove_all: bool) -> list[BrowserLease]:
        to_close: list[BrowserLease] = []
        keep: list[BrowserLease] = []
        while not self._available.empty():
            lease = self._available.get_nowait()
            should_close = remove_all or lease.config != config or len(self._leases) - len(to_close) > self._target_size
            if should_close:
                self._leases.discard(lease)
                to_close.append(lease)
            else:
                keep.append(lease)
        for lease in keep:
            self._available.put_nowait(lease)
        return to_close

    async def _close_leases(self, leases: list[BrowserLease]) -> None:
        for lease in leases:
            try:
                await lease.browser.close()
            except Exception:
                pass

    async def _stop_playwright_if_idle(self) -> None:
        playwright = None
        async with self._lock:
            if self._closing and not self._leases and self._playwright is not None:
                playwright = self._playwright
                self._playwright = None
                self._config = None
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception:
                pass

    @staticmethod
    def _browser_connected(browser: Any) -> bool:
        is_connected = getattr(browser, "is_connected", None)
        return bool(is_connected()) if callable(is_connected) else True

    def _config_from_settings(self, settings: dict[str, Any]) -> BrowserLaunchConfig:
        try:
            return BrowserLaunchConfig.from_settings(settings)
        except Exception as exc:
            self._last_error = f"浏览器环境配置无效：{exc}"
            raise ResourcePoolError(self._last_error) from exc


class ProbeResourcePool:
    def __init__(self, api_pool_size: int, browser_pool_size: int) -> None:
        self.http_clients = HttpClientPool(api_pool_size)
        self.browsers = BrowserPool(browser_pool_size)

    async def start(self, settings: dict[str, Any], *, api_pool_size: int, browser_pool_size: int) -> None:
        await self.http_clients.resize(api_pool_size)
        try:
            await self.browsers.resize(browser_pool_size, settings)
        except ResourcePoolError:
            pass

    async def reload(self, settings: dict[str, Any], *, api_pool_size: int, browser_pool_size: int) -> None:
        await self.start(settings, api_pool_size=api_pool_size, browser_pool_size=browser_pool_size)

    async def shutdown(self) -> None:
        await self.http_clients.shutdown()
        await self.browsers.shutdown()

    @asynccontextmanager
    async def http_client(self) -> AsyncIterator[httpx.AsyncClient]:
        async with self.http_clients.client() as client:
            yield client

    async def acquire_browser(self, settings: dict[str, Any]) -> BrowserLease:
        return await self.browsers.acquire(settings)

    async def release_browser(self, lease: BrowserLease, *, healthy: bool = True) -> None:
        await self.browsers.release(lease, healthy=healthy)

    def snapshot(self) -> dict[str, Any]:
        return {
            "api": self.http_clients.snapshot(),
            "browser": self.browsers.snapshot(),
        }


async def _close_http_clients(clients: list[httpx.AsyncClient]) -> None:
    for client in clients:
        await client.aclose()


def settings_from_config(config: BrowserLaunchConfig | None) -> dict[str, Any]:
    if config is None:
        return {}
    return {
        "browser_type": config.browser_type,
        "browser_headless": config.headless,
        "browser_proxy": config.proxy_url,
    }
