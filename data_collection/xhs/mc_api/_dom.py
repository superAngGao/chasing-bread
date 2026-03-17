"""DOM interaction helpers for Playwright pages (popup clearing, scrolling, etc.)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from ._errors import XhsApiError, check_page_url

_ACTION_LAST_TS: dict[str, float] = {}
_ACTION_LOCK = asyncio.Lock()

DEFAULT_ACTION_INTERVAL_SEC = 0.25
SCROLL_ACTION_INTERVAL_SEC = 0.10

NOTE_DETAIL_CONTEXT_SELECTOR = ".note-scroller, .comments-container, .interaction-container"


async def throttle_action(action: str, min_interval_sec: float | None = None) -> None:
    interval = (
        DEFAULT_ACTION_INTERVAL_SEC
        if min_interval_sec is None
        else max(0.0, float(min_interval_sec))
    )
    if interval <= 0:
        return
    now = time.monotonic()
    async with _ACTION_LOCK:
        last_ts = _ACTION_LAST_TS.get(action, 0.0)
        wait_sec = (last_ts + interval) - now
        if wait_sec > 0:
            await asyncio.sleep(wait_sec)
            now = time.monotonic()
        _ACTION_LAST_TS[action] = now


async def smooth_wheel_scroll(
    *,
    page,
    delta_y: float,
    step_px: int = 180,
    pause_sec: float = 0.03,
) -> None:
    total = float(delta_y)
    if total == 0:
        return
    direction = 1 if total > 0 else -1
    remaining = abs(total)
    step_px = max(40, int(step_px))
    pause_sec = max(0.0, float(pause_sec))
    while remaining > 0:
        step = min(step_px, remaining)
        await throttle_action("scroll", SCROLL_ACTION_INTERVAL_SEC)
        await page.mouse.wheel(0, direction * step)
        remaining -= step
        if pause_sec > 0:
            await asyncio.sleep(pause_sec)


async def ensure_logged_in_or_raise(*, page, endpoint: str, phase: str) -> None:
    try:
        state = await page.evaluate(
            """() => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (style.display === "none" || style.visibility === "hidden") return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const verifyRoot = document.querySelector(".captcha-modal-content, .captcha-modal");
                const verifyText = (verifyRoot?.textContent || "");
                const verifyVisible = !!verifyRoot && isVisible(verifyRoot);
                const verifyHit = verifyVisible && (
                    verifyText.includes("请通过验证") ||
                    verifyText.includes("扫码验证身份") ||
                    verifyText.includes("二维码1分钟失效")
                );
                const authRoot = document.querySelector(
                    ".login-container, .login-modal, .auth-container, [class*='login-modal'], [class*='auth-container']"
                );
                const authVisible = !!authRoot && isVisible(authRoot);
                const inputVisible = Array.from(document.querySelectorAll("input"))
                    .some((el) => isVisible(el));
                const loginRequired = authVisible && inputVisible;
                return { verifyHit, loginRequired };
            }"""
        )
    except Exception:
        state = {}

    verify_hit = bool((state or {}).get("verifyHit"))
    login_required_ui = bool((state or {}).get("loginRequired"))

    cookie_login_ok = False
    try:
        cookies = await page.context.cookies()
        cookie_map = {c.get("name"): c for c in cookies if isinstance(c.get("name"), str)}
        a1 = cookie_map.get("a1")
        id_token = cookie_map.get("id_token")
        cookie_login_ok = bool(a1 and a1.get("value") and id_token and id_token.get("value"))
    except Exception:
        pass

    if verify_hit:
        raise XhsApiError(
            endpoint=endpoint,
            code=300012,
            msg="请通过验证",
            payload={"phase": phase, "url": getattr(page, "url", ""), "verify_modal": True},
        )
    if login_required_ui and not cookie_login_ok:
        raise XhsApiError(
            endpoint=endpoint,
            code=-101,
            msg="无登录信息",
            payload={"phase": phase, "url": getattr(page, "url", ""), "login_ui": True},
        )


async def try_clear_page_popup(page) -> bool:
    if page is None:
        return False
    try:
        clicked_svg = await page.evaluate(
            """() => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (style.display === "none" || style.visibility === "hidden") return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const use = document.querySelector("svg use[href='#close'], svg use[*|href='#close']");
                const clickable = use ? (use.parentElement || use) : null;
                if (clickable && isVisible(clickable)) {
                    clickable.dispatchEvent(new MouseEvent("click", { bubbles: true }));
                    return true;
                }
                return false;
            }"""
        )
        if clicked_svg:
            return True
    except Exception:
        pass
    try:
        css_close = page.locator(".icon-btn-close, .close-icon, [class*='login-close']").first
        if await css_close.is_visible(timeout=300):
            await css_close.click(timeout=400)
            return True
    except Exception:
        try:
            clicked_css = await page.evaluate(
                """() => {
                    const isVisible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        if (style.display === "none" || style.visibility === "hidden") return false;
                        const rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    };
                    const btn = document.querySelector(".icon-btn-close, .close-icon, [class*='login-close']");
                    if (btn && isVisible(btn)) {
                        btn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
                        return true;
                    }
                    return false;
                }"""
            )
            if clicked_css:
                return True
        except Exception:
            pass
    return False


async def extract_note_content_from_dom(page, *, expected_url: str = "") -> dict[str, Any]:
    if expected_url:
        check_page_url(page, expected=expected_url, context="extract_note_content_from_dom")
    return await page.evaluate(
        """() => {
            const clean = (v) => typeof v !== "string" ? "" : v.replace(/\\s+/g, " ").trim();
            const pickText = (selectors) => {
                for (const sel of selectors) {
                    const node = document.querySelector(sel);
                    const text = clean(node ? (node.textContent || "") : "");
                    if (text) return text;
                }
                return "";
            };
            return {
                title: pickText(["h1", ".note-content .title", "[class*='note-title']"]) || null,
                author: pickText(["[class*='author'] [class*='name']", "[class*='nickname']", "a[href*='/user/profile/']"]) || null,
                content: pickText([".note-content .desc", ".note-content .note-text", "[class*='note-content'] [class*='desc']"]) || null,
            };
        }"""
    )
