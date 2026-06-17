from __future__ import annotations

from typing import Any


H5_VIEWPORT = {"width": 390, "height": 844}
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


def normalize_viewport_mode(value: Any) -> str:
    return "h5" if str(value or "").strip().lower() == "h5" else "web"


def viewport_for_mode(
    mode: Any,
    settings: dict[str, Any],
    width: int | None = None,
    height: int | None = None,
) -> dict[str, int]:
    if width and height:
        return {"width": int(width), "height": int(height)}
    if normalize_viewport_mode(mode) == "h5":
        return dict(H5_VIEWPORT)
    return browser_viewport(settings)


def browser_context_options(mode: Any, viewport: dict[str, int]) -> dict[str, Any]:
    options: dict[str, Any] = {"viewport": viewport}
    if normalize_viewport_mode(mode) == "h5":
        options.update(
            {
                "is_mobile": True,
                "has_touch": True,
                "user_agent": MOBILE_USER_AGENT,
            }
        )
    return options


def browser_viewport(settings: dict[str, Any]) -> dict[str, int]:
    raw = str(settings.get("browser_viewport") or "1440x900").lower()
    try:
        width, height = raw.split("x", 1)
        return {"width": int(width), "height": int(height)}
    except ValueError:
        return {"width": 1440, "height": 900}
