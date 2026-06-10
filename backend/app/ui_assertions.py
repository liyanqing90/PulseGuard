from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any

from .context import RunContext, RunFailure
from .ui_scan_script import UI_SCAN_SCRIPT
from .variables import mask_data, mask_text, resolve_data, resolve_text
from .viewport import browser_context_options, viewport_for_mode


UI_ASSERTION_TYPES = {
    "element_visible",
    "element_hidden",
    "element_not_empty",
    "page_not_blank",
    "text_present",
    "text_absent",
    "title_contains",
    "url_contains",
    "console_error_absent",
    "element_count",
}

SELECTOR_ASSERTION_TYPES = {"element_visible", "element_hidden", "element_not_empty", "element_count"}
TEXT_ASSERTION_TYPES = {"text_present", "text_absent", "title_contains", "url_contains"}
COUNT_OPERATORS = {"eq", "ne", "gt", "gte", "lt", "lte"}
SELECTOR_STABILITY_LEVELS = {"high", "medium", "low"}


async def inspect_ui_page(payload: dict[str, Any], settings: dict[str, Any], ctx: RunContext | None = None, setup_func: Any | None = None) -> dict[str, Any]:
    entry_url = resolve_text(payload.get("entry_url") or "", settings).strip()
    timeout_ms = int(payload.get("timeout_ms") or 15000)
    if not entry_url:
        raise ValueError("页面 URL 不能为空")
    viewport = viewport_for_mode(payload.get("viewport_mode"), settings, payload.get("viewport_width"), payload.get("viewport_height"))

    if ctx is not None:
        page = await ctx.new_page()
        if setup_func is not None:
            ctx.log("执行 UI 扫描前置脚本")
            await _run_phase_with_timeout(setup_func(ctx, page), timeout_ms, "扫描前置脚本执行超时")
            if _page_is_closed(page):
                raise RunFailure("前置脚本关闭了扫描页面")
            ctx.log("UI 扫描前置脚本完成")

        await _goto_ui_page(page, entry_url, timeout_ms, "页面扫描加载超时")
        await _prepare_full_page(page)

        candidates = await page.evaluate(UI_SCAN_SCRIPT)
        screenshot = await page.screenshot(type="jpeg", quality=72, full_page=True)
        return {
            "title": await page.title(),
            "url": mask_text(page.url, settings),
            "viewport": candidates.get("viewport") or viewport,
            "page_size": candidates.get("page_size") or candidates.get("viewport") or viewport,
            "candidates": mask_data(candidates.get("candidates") or [], settings),
            "screenshot": f"data:image/jpeg;base64,{base64.b64encode(screenshot).decode('ascii')}",
            "logs": mask_text("\n".join(ctx.logs), settings),
        }

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RunFailure("Playwright 未安装，请先安装后再扫描页面") from exc

    playwright = await async_playwright().start()
    browser = None
    context = None
    try:
        browser_type_name = str(settings.get("browser_type") or "chromium")
        browser_type = getattr(playwright, browser_type_name, None)
        if browser_type is None:
            raise ValueError(f"不支持的浏览器类型：{browser_type_name}")

        launch_options: dict[str, Any] = {"headless": bool(settings.get("browser_headless", True))}
        proxy_url = resolve_text(settings.get("browser_proxy") or "", settings).strip()
        if proxy_url:
            launch_options["proxy"] = {"server": proxy_url}

        browser = await browser_type.launch(**launch_options)
        context_options = browser_context_options(payload.get("viewport_mode"), viewport)
        context = await browser.new_context(**context_options)
        page = await context.new_page()
        page.set_default_timeout(timeout_ms)
        if setup_func is not None:
            if ctx is None:
                raise RunFailure("扫描前置脚本缺少运行上下文")
            ctx.log("执行 UI 扫描前置脚本")
            await _run_phase_with_timeout(setup_func(ctx, page), timeout_ms, "扫描前置脚本执行超时")
            if _page_is_closed(page):
                raise RunFailure("前置脚本关闭了扫描页面")
            ctx.log("UI 扫描前置脚本完成")

        await _goto_ui_page(page, entry_url, timeout_ms, "页面扫描加载超时")
        await _prepare_full_page(page)

        candidates = await page.evaluate(UI_SCAN_SCRIPT)
        screenshot = await page.screenshot(type="jpeg", quality=72, full_page=True)
        return {
            "title": await page.title(),
            "url": mask_text(page.url, settings),
            "viewport": candidates.get("viewport") or viewport,
            "page_size": candidates.get("page_size") or candidates.get("viewport") or viewport,
            "candidates": mask_data(candidates.get("candidates") or [], settings),
            "screenshot": f"data:image/jpeg;base64,{base64.b64encode(screenshot).decode('ascii')}",
            "logs": mask_text("\n".join(ctx.logs), settings) if ctx else "",
        }
    finally:
        if context:
            await context.close()
        if browser:
            await browser.close()
        await playwright.stop()


def normalize_ui_assertions(raw: str | None) -> list[dict[str, Any]]:
    try:
        items = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError("UI 校验项必须是合法 JSON") from exc
    if not isinstance(items, list):
        raise ValueError("UI 校验项必须是数组")

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 个 UI 校验项格式不正确")
        assertion_type = str(item.get("type") or "").strip()
        if assertion_type not in UI_ASSERTION_TYPES:
            raise ValueError(f"不支持的 UI 校验类型：{assertion_type or '空'}")

        assertion: dict[str, Any] = {
            "id": str(item.get("id") or f"ui-assertion-{index}"),
            "type": assertion_type,
            "enabled": bool(item.get("enabled", True)),
        }
        if assertion_type in SELECTOR_ASSERTION_TYPES:
            assertion["selector"] = _required_string(item.get("selector"), "选择器")
            _copy_selector_metadata(assertion, item)
        if assertion_type in TEXT_ASSERTION_TYPES:
            assertion["expected_text"] = _required_string(item.get("expected_text"), "预期文本")
        if assertion_type == "element_count":
            assertion["operator"] = _enum(item.get("operator", "eq"), COUNT_OPERATORS, "数量关系")
            assertion["expected_count"] = _bounded_int(item.get("expected_count", 1), 0, 100000, "预期数量")
        normalized.append(assertion)
    return normalized


def has_enabled_ui_assertions(raw: str | None) -> bool:
    return any(assertion.get("enabled", True) for assertion in normalize_ui_assertions(raw))


async def inspect_ui_selector_rules(raw: str | None, page: Any, settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    resolved_settings = settings or {}
    assertions = [resolve_data(item, resolved_settings) for item in normalize_ui_assertions(raw)]
    results: list[dict[str, Any]] = []
    for assertion in assertions:
        assertion_type = assertion["type"]
        if assertion_type not in SELECTOR_ASSERTION_TYPES:
            continue
        result = {
            "id": assertion["id"],
            "type": assertion_type,
            "selector": assertion["selector"],
            "status": "ok",
            "count": None,
            "message": "",
        }
        if not assertion.get("enabled", True):
            result.update({"status": "disabled", "message": "规则已停用，未检测"})
            results.append(result)
            continue
        try:
            count = int(await page.locator(assertion["selector"]).count())
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            lowered = message.lower()
            status = "invalid_selector" if "selector" in lowered or "parse" in lowered or "unexpected" in lowered else "error"
            result.update({"status": status, "message": f"selector 无法解析：{message}" if status == "invalid_selector" else f"检测失败：{message}"})
            results.append(result)
            continue

        result["count"] = count
        if count == 0:
            result.update({"status": "missing", "message": "selector 当前未匹配到元素"})
        elif assertion_type != "element_count" and count > 1:
            result.update({"status": "multiple", "message": f"selector 当前匹配 {count} 个元素"})
        else:
            result["message"] = "selector 当前匹配正常"
        results.append(result)
    return results


async def inspect_ui_rule_selectors(payload: dict[str, Any], settings: dict[str, Any], ctx: RunContext | None = None, setup_func: Any | None = None) -> dict[str, Any]:
    entry_url = resolve_text(payload.get("entry_url") or "", settings).strip()
    timeout_ms = int(payload.get("timeout_ms") or 15000)
    if not entry_url:
        raise ValueError("页面 URL 不能为空")
    viewport = viewport_for_mode(payload.get("viewport_mode"), settings, payload.get("viewport_width"), payload.get("viewport_height"))

    if ctx is not None:
        page = await ctx.new_page()
        if setup_func is not None:
            ctx.log("执行 UI 规则检测前置脚本")
            await _run_phase_with_timeout(setup_func(ctx, page), timeout_ms, "规则检测前置脚本执行超时")
            if _page_is_closed(page):
                raise RunFailure("前置脚本关闭了规则检测页面")
            ctx.log("UI 规则检测前置脚本完成")

        await _goto_ui_page(page, entry_url, timeout_ms, "规则检测页面加载超时")
        await _prepare_full_page(page)
        results = await inspect_ui_selector_rules(payload.get("assertions_json"), page, settings)
        return {
            "title": await page.title(),
            "url": mask_text(page.url, settings),
            "results": mask_data(results, settings),
            "logs": mask_text("\n".join(ctx.logs), settings),
        }

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RunFailure("Playwright 未安装，请先安装后再检测规则") from exc

    playwright = await async_playwright().start()
    browser = None
    context = None
    try:
        browser_type_name = str(settings.get("browser_type") or "chromium")
        browser_type = getattr(playwright, browser_type_name, None)
        if browser_type is None:
            raise ValueError(f"不支持的浏览器类型：{browser_type_name}")

        launch_options: dict[str, Any] = {"headless": bool(settings.get("browser_headless", True))}
        proxy_url = resolve_text(settings.get("browser_proxy") or "", settings).strip()
        if proxy_url:
            launch_options["proxy"] = {"server": proxy_url}

        browser = await browser_type.launch(**launch_options)
        context_options = browser_context_options(payload.get("viewport_mode"), viewport)
        context = await browser.new_context(**context_options)
        page = await context.new_page()
        page.set_default_timeout(timeout_ms)
        if setup_func is not None:
            if ctx is None:
                raise RunFailure("规则检测前置脚本缺少运行上下文")
            ctx.log("执行 UI 规则检测前置脚本")
            await _run_phase_with_timeout(setup_func(ctx, page), timeout_ms, "规则检测前置脚本执行超时")
            if _page_is_closed(page):
                raise RunFailure("前置脚本关闭了规则检测页面")
            ctx.log("UI 规则检测前置脚本完成")

        await _goto_ui_page(page, entry_url, timeout_ms, "规则检测页面加载超时")
        await _prepare_full_page(page)
        results = await inspect_ui_selector_rules(payload.get("assertions_json"), page, settings)
        return {
            "title": await page.title(),
            "url": mask_text(page.url, settings),
            "results": mask_data(results, settings),
            "logs": mask_text("\n".join(ctx.logs), settings) if ctx else "",
        }
    finally:
        if context:
            await context.close()
        if browser:
            await browser.close()
        await playwright.stop()


async def run_structured_ui_check(ctx: RunContext, setup_func: Any | None = None) -> None:
    assertions = [
        resolve_data(item, ctx.settings)
        for item in normalize_ui_assertions(ctx.check.get("assertions_json"))
        if item.get("enabled", True)
    ]
    if not assertions:
        raise RunFailure("请至少启用一个 UI 校验项")

    page = await ctx.new_page()
    if setup_func is not None:
        ctx.log("执行 UI 前置脚本")
        await _run_phase_with_timeout(setup_func(ctx, page), ctx.timeout_ms, "前置脚本执行超时")
        if _page_is_closed(page):
            raise RunFailure("前置脚本关闭了校验页面")
        ctx.log("UI 前置脚本完成")

    page_load_started = time.perf_counter()
    await _goto_ui_page(page, ctx.entry_url, ctx.timeout_ms, "页面加载超时")
    page_load_ms = max(0, int((time.perf_counter() - page_load_started) * 1000))
    ctx.log(f"页面加载完成：{page_load_ms} ms")

    assertion_deadline = _deadline_from_now(ctx.timeout_ms)
    assertion_started = time.perf_counter()
    ctx.log(f"并发执行 UI 校验：{len(assertions)} 项，单项最长等待 {ctx.timeout_ms}ms")
    assertion_results = list(
        await asyncio.gather(
            *(_evaluate_assertion(assertion, page, ctx, assertion_deadline) for assertion in assertions)
        )
    )
    assertion_ms = max(0, int((time.perf_counter() - assertion_started) * 1000))

    page_title = await page.title()
    page_url = page.url
    ctx.response_snapshot = {
        "page": {
            "title": page_title,
            "url": page_url,
            "wait_until": "domcontentloaded",
            "viewport_mode": ctx.viewport_mode,
            "load_ms": page_load_ms,
        },
        "timings": {"page_load_ms": page_load_ms, "assertions_ms": assertion_ms, "assertion_timeout_ms": ctx.timeout_ms},
        "assertions": assertion_results,
    }

    failed = [item for item in assertion_results if item.get("status") != "ok"]
    if failed:
        raise RunFailure(f"UI 结构化校验失败：{failed[0].get('message') or failed[0].get('rule')}")


async def _evaluate_assertion(assertion: dict[str, Any], page: Any, ctx: RunContext, deadline: float | None = None) -> dict[str, Any]:
    assertion_type = assertion["type"]
    label = assertion_label(assertion)
    wait_ms = _assertion_wait_ms(ctx, deadline)

    try:
        if assertion_type == "element_visible":
            selector = assertion["selector"]
            try:
                await page.locator(selector).first.wait_for(state="visible", timeout=wait_ms)
            except Exception as exc:
                if _is_playwright_timeout(exc):
                    return await _selector_wait_failure(page, label, selector, "可见", wait_ms)
                raise
            return _result(label, selector, "ok", "可见", "", "可见", "元素可见")

        if assertion_type == "element_hidden":
            selector = assertion["selector"]
            try:
                await page.locator(selector).first.wait_for(state="hidden", timeout=wait_ms)
            except Exception as exc:
                if _is_playwright_timeout(exc):
                    count = await _safe_locator_count(page, selector)
                    actual = "仍可见" if count else "状态未确认"
                    return _result(
                        label,
                        selector,
                        "failed",
                        actual,
                        "",
                        "隐藏或不存在",
                        f"元素未在 {wait_ms}ms 内隐藏：{selector}",
                    )
                raise
            return _result(label, selector, "ok", "隐藏或不存在", "", "隐藏", "元素隐藏或不存在")

        if assertion_type == "element_not_empty":
            selector = assertion["selector"]
            locator = page.locator(selector).first
            try:
                await locator.wait_for(state="visible", timeout=wait_ms)
            except Exception as exc:
                if _is_playwright_timeout(exc):
                    return await _selector_wait_failure(page, label, selector, "有内容", wait_ms)
                raise
            info = await locator.evaluate(
                """
                (el) => {
                  const visible = (node) => {
                    const style = getComputedStyle(node);
                    const rect = node.getBoundingClientRect();
                    return style.visibility !== "hidden" && style.display !== "none" && Number(style.opacity) !== 0 && rect.width > 0 && rect.height > 0;
                  };
                  const hasMedia = Boolean(el.querySelector("img,svg,canvas,video,picture,iframe,input,textarea,select"));
                  const text = (el.innerText || el.textContent || "").trim().replace(/\\s+/g, " ");
                  const visibleChildCount = Array.from(el.children || []).filter(visible).length;
                  const rect = el.getBoundingClientRect();
                  return { text, hasMedia, visibleChildCount, width: rect.width, height: rect.height };
                }
                """
            )
            passed = bool(info.get("width") and info.get("height") and (info.get("text") or info.get("hasMedia") or info.get("visibleChildCount")))
            actual = info.get("text") or ("包含媒体/表单" if info.get("hasMedia") else f"{info.get('visibleChildCount') or 0} 个可见子元素")
            return _result(
                label,
                selector,
                "ok" if passed else "failed",
                actual,
                "不为空",
                "有内容",
                "组件不为空" if passed else f"校验失败：组件为空或没有可见内容：{selector}",
            )

        if assertion_type == "page_not_blank":
            info = await page.evaluate(
                """
                () => {
                  const visible = (node) => {
                    const style = getComputedStyle(node);
                    const rect = node.getBoundingClientRect();
                    return style.visibility !== "hidden" && style.display !== "none" && Number(style.opacity) !== 0 && rect.width > 1 && rect.height > 1;
                  };
                  const nodes = Array.from(document.body?.querySelectorAll("*") || []);
                  const visibleNodes = nodes.filter(visible);
                  const text = visibleNodes.map((node) => node.innerText || node.textContent || "").join(" ").trim().replace(/\\s+/g, " ");
                  const mediaCount = visibleNodes.filter((node) => node.matches("img,svg,canvas,video,picture,iframe")).length;
                  const interactiveCount = visibleNodes.filter((node) => node.matches("button,a,input,textarea,select,[role]")).length;
                  return {
                    textLength: text.length,
                    preview: text.slice(0, 120),
                    mediaCount,
                    interactiveCount,
                    visibleElementCount: visibleNodes.length
                  };
                }
                """
            )
            passed = bool(info.get("textLength") or info.get("mediaCount") or info.get("interactiveCount") or info.get("visibleElementCount"))
            actual = (
                f"文本 {info.get('textLength') or 0} 字，媒体 {info.get('mediaCount') or 0} 个，"
                f"交互 {info.get('interactiveCount') or 0} 个，可见节点 {info.get('visibleElementCount') or 0} 个"
            )
            return _result(label, "page", "ok" if passed else "failed", actual, "不为空", "页面有内容", "页面不空白" if passed else "页面为空白或无可见内容")

        if assertion_type == "text_present":
            text = assertion["expected_text"]
            try:
                await page.get_by_text(text).first.wait_for(state="visible", timeout=wait_ms)
            except Exception as exc:
                if _is_playwright_timeout(exc):
                    count = await page.get_by_text(text).count()
                    actual = "未找到" if count == 0 else f"匹配 {count} 个，未可见"
                    return _result(label, text, "failed", actual, "包含", text, f"校验失败：文本未出现：{text}")
                raise
            return _result(label, text, "ok", "出现", "包含", text, "文本出现")

        if assertion_type == "text_absent":
            text = assertion["expected_text"]
            try:
                await page.get_by_text(text).first.wait_for(state="hidden", timeout=wait_ms)
            except Exception as exc:
                if _is_playwright_timeout(exc):
                    return _result(label, text, "failed", "仍可见", "不包含", text, f"校验失败：文本仍然出现：{text}")
                raise
            return _result(label, text, "ok", "未出现", "不包含", text, "文本未出现")

        if assertion_type == "title_contains":
            title = await page.title()
            expected = assertion["expected_text"]
            passed = expected in title
            return _result(label, "title", "ok" if passed else "failed", title, "包含", expected, "标题包含预期文本" if passed else "标题不包含预期文本")

        if assertion_type == "url_contains":
            current_url = page.url
            expected = assertion["expected_text"]
            passed = expected in current_url
            return _result(label, "url", "ok" if passed else "failed", current_url, "包含", expected, "URL 包含预期文本" if passed else "URL 不包含预期文本")

        if assertion_type == "console_error_absent":
            errors = [item for item in ctx.console_messages if item.get("type") == "error"]
            passed = not errors
            actual = "无错误" if passed else "；".join(str(item.get("text") or "") for item in errors[:5])
            return _result(label, "console", "ok" if passed else "failed", actual, "不存在", "console error", "控制台无错误" if passed else "控制台存在错误")

        if assertion_type == "element_count":
            selector = assertion["selector"]
            actual_count = await page.locator(selector).count()
            expected_count = int(assertion["expected_count"])
            operator = assertion["operator"]
            passed = _compare_count(actual_count, operator, expected_count)
            return _result(
                label,
                selector,
                "ok" if passed else "failed",
                actual_count,
                _operator_label(operator),
                expected_count,
                "元素数量满足预期" if passed else f"元素数量不匹配：实际 {actual_count}，期望 {_operator_label(operator)} {expected_count}",
            )
    except Exception as exc:
        return _result(label, assertion.get("selector") or assertion.get("expected_text") or assertion_type, "failed", "执行失败", "", "", f"校验失败：{str(exc) or exc.__class__.__name__}")

    return _result(label, assertion_type, "failed", "-", "", "", "不支持的 UI 校验项")


def assertion_label(assertion: dict[str, Any]) -> str:
    assertion_type = assertion["type"]
    if assertion_type == "element_visible":
        return "元素可见"
    if assertion_type == "element_hidden":
        return "元素隐藏"
    if assertion_type == "element_not_empty":
        return "组件不为空"
    if assertion_type == "page_not_blank":
        return "页面不空白"
    if assertion_type == "text_present":
        return "文本出现"
    if assertion_type == "text_absent":
        return "文本不存在"
    if assertion_type == "title_contains":
        return "标题包含"
    if assertion_type == "url_contains":
        return "URL 包含"
    if assertion_type == "console_error_absent":
        return "控制台无错误"
    if assertion_type == "element_count":
        return "元素数量"
    return assertion_type


def _result(rule: str, path: str, status: str, actual: Any, operator: str, expected: Any, message: str) -> dict[str, Any]:
    return {
        "rule": rule,
        "path": path,
        "status": status,
        "actual": actual,
        "operator": operator,
        "expected": expected,
        "message": message,
    }


def _required_string(value: Any, label: str) -> str:
    if value is None or not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}不能为空")
    text = value.strip()
    if len(text) > 1000:
        raise ValueError(f"{label}过长")
    return text


def _copy_selector_metadata(assertion: dict[str, Any], item: dict[str, Any]) -> None:
    selector_type = str(item.get("selector_type") or "").strip()
    selector_stability = str(item.get("selector_stability") or "").strip()
    selector_score = item.get("selector_score")
    if selector_type:
        assertion["selector_type"] = selector_type[:80]
    if selector_stability in SELECTOR_STABILITY_LEVELS:
        assertion["selector_stability"] = selector_stability
    if isinstance(selector_score, bool):
        return
    try:
        score = float(selector_score)
    except (TypeError, ValueError):
        return
    assertion["selector_score"] = int(score) if score.is_integer() else score


def _bounded_int(value: Any, minimum: int, maximum: int, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label}必须是数字")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}必须是数字") from exc
    if number < minimum or number > maximum:
        raise ValueError(f"{label}必须在 {minimum} 到 {maximum} 之间")
    return number


def _enum(value: Any, allowed: set[str], label: str) -> str:
    text = str(value or "").strip()
    if text not in allowed:
        raise ValueError(f"{label}不支持：{text}")
    return text


def _compare_count(actual: int, operator: str, expected: int) -> bool:
    if operator == "eq":
        return actual == expected
    if operator == "ne":
        return actual != expected
    if operator == "gt":
        return actual > expected
    if operator == "gte":
        return actual >= expected
    if operator == "lt":
        return actual < expected
    if operator == "lte":
        return actual <= expected
    return False


def _operator_label(operator: str) -> str:
    return {
        "eq": "=",
        "ne": "!=",
        "gt": ">",
        "gte": ">=",
        "lt": "<",
        "lte": "<=",
    }.get(operator, operator)


async def _goto_ui_page(page: Any, url: str, timeout_ms: int, timeout_label: str) -> None:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception as exc:
        if _is_playwright_timeout(exc):
            raise asyncio.TimeoutError(f"{timeout_label}：{timeout_ms}ms") from exc
        raise


def _page_is_closed(page: Any) -> bool:
    is_closed = getattr(page, "is_closed", None)
    return bool(is_closed()) if callable(is_closed) else False


async def _run_phase_with_timeout(awaitable: Any, timeout_ms: int, timeout_label: str) -> Any:
    timeout = _timeout_seconds(timeout_ms)
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise asyncio.TimeoutError(f"{timeout_label}：{_configured_timeout_ms(timeout_ms)}ms") from exc


def _configured_timeout_ms(timeout_ms: int | None) -> int:
    return max(1, int(timeout_ms or 15000))


def _timeout_seconds(timeout_ms: int | None) -> float:
    return max(0.001, _configured_timeout_ms(timeout_ms) / 1000)


def _deadline_from_now(timeout_ms: int | None) -> float:
    return time.monotonic() + _timeout_seconds(timeout_ms)


def _assertion_wait_ms(ctx: RunContext, deadline: float | None = None) -> int:
    configured = max(1, int(ctx.timeout_ms or 15000))
    if deadline is None:
        return configured
    remaining = int((deadline - time.monotonic()) * 1000)
    return max(1, min(configured, remaining))


def _is_playwright_timeout(exc: Exception) -> bool:
    return exc.__class__.__name__ == "TimeoutError" and "playwright" in exc.__class__.__module__


async def _selector_wait_failure(page: Any, label: str, selector: str, expected: str, wait_ms: int) -> dict[str, Any]:
    count = await _safe_locator_count(page, selector)
    if count == 0:
        actual = "未找到"
        message = f"未找到元素：{selector}"
    else:
        actual = f"匹配 {count} 个，未可见"
        message = f"元素未在 {wait_ms}ms 内变为{expected}：{selector}"
    return _result(label, selector, "failed", actual, "", expected, message)


async def _safe_locator_count(page: Any, selector: str) -> int:
    try:
        return int(await page.locator(selector).count())
    except Exception:
        return 0


async def _prepare_full_page(page: Any) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    await page.wait_for_timeout(300)
    previous_height = 0
    stable_rounds = 0
    for _ in range(8):
        height = await page.evaluate(
            "() => Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight || 0, window.innerHeight)"
        )
        await page.evaluate("(height) => window.scrollTo(0, height)", height)
        await page.wait_for_timeout(260)
        next_height = await page.evaluate(
            "() => Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight || 0, window.innerHeight)"
        )
        if int(next_height) <= int(previous_height or height):
            stable_rounds += 1
        else:
            stable_rounds = 0
        previous_height = int(next_height)
        if stable_rounds >= 2:
            break
    await page.evaluate("() => window.scrollTo(0, 0)")
    await page.wait_for_timeout(200)
