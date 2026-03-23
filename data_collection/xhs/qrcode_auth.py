"""QR-code auth helpers for XHS Playwright sessions."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from data_collection.xhs.browser_fingerprint import (
    apply_stealth_to_context,
    get_context_options,
    get_persistent_context_options,
    get_stealth_js,
)

DEFAULT_PROFILE_DIRNAME = ".xhs_chromium_profile"
logger = logging.getLogger(__name__)
LOGIN_REDIRECT_WAIT_SEC = 5.0
LOGIN_HEARTBEAT_SEC = 10.0
ALLOW_TEMP_PROFILE_FALLBACK = os.getenv("XHS_ALLOW_TEMP_PROFILE_FALLBACK", "0") == "1"


@dataclass(slots=True)
class QrcodeAuthSession:
    playwright: Any
    browser: Any | None
    context: Any
    page: Any
    cookie_header: str
    a1: str

    async def close(self) -> None:
        # Save cookies as backup before closing
        try:
            state_path = Path(DEFAULT_PROFILE_DIRNAME) / "storage_state.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            await self.context.storage_state(path=str(state_path.resolve()))
            logger.debug("[xhs_qrcode] saved storage state to %s", state_path)
        except Exception as exc:
            logger.debug("[xhs_qrcode] could not save storage state: %s", exc)
        await self.context.close()
        if self.browser is not None:
            await self.browser.close()
        await self.playwright.stop()


def _cookies_to_header(cookies: list[dict[str, Any]]) -> str:
    pairs = []
    for c in cookies:
        name = c.get("name")
        value = c.get("value")
        if isinstance(name, str) and isinstance(value, str):
            pairs.append((name, value))
    pairs.sort(key=lambda x: x[0])
    return "; ".join([f"{name}={value}" for name, value in pairs])


def _extract_cookie_value(cookie_header: str, key: str) -> str:
    for part in cookie_header.split(";"):
        part = part.strip()
        if not part:
            continue
        if part.startswith(f"{key}="):
            return part.split("=", 1)[1]
    return ""


def _is_cookie_expired(cookie: dict[str, Any]) -> bool:
    expires = cookie.get("expires")
    if not isinstance(expires, (int, float)):
        return False
    if expires <= 0:
        return False
    return expires <= time.time() + 30


def _is_logged_in_from_cookies(cookies: list[dict[str, Any]]) -> bool:
    cookie_map: dict[str, dict[str, Any]] = {}
    for c in cookies:
        name = c.get("name")
        if isinstance(name, str):
            cookie_map[name] = c
    a1 = cookie_map.get("a1")
    id_token = cookie_map.get("id_token")
    if not a1 or not id_token:
        return False
    if not a1.get("value") or not id_token.get("value"):
        return False
    if _is_cookie_expired(id_token):
        return False
    return True


async def _logged_out_ui_signals(page) -> dict[str, bool]:
    try:
        return await page.evaluate(
            """() => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (style.display === "none" || style.visibility === "hidden") return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };

                const visibleInputs = Array.from(document.querySelectorAll("input"))
                    .filter((el) => !el.disabled && isVisible(el));
                const hasPasswordInput = visibleInputs.some((el) => {
                    const t = (el.getAttribute("type") || "").toLowerCase();
                    return t === "password";
                });
                const hasAuthLikeInput = visibleInputs.some((el) => {
                    const t = (el.getAttribute("type") || "").toLowerCase();
                    const n = (el.getAttribute("name") || "").toLowerCase();
                    const id = (el.id || "").toLowerCase();
                    const p = (el.getAttribute("placeholder") || "").toLowerCase();
                    const joined = `${t} ${n} ${id} ${p}`;
                    return /(phone|email|sms|code|otp|captcha|verify)/.test(joined);
                });

                const authSelector = [
                    "[class*='login']",
                    "[class*='signin']",
                    "[class*='signup']",
                    "[class*='auth']",
                    "[id*='login']",
                    "[id*='signin']",
                    "[id*='signup']",
                    "[id*='auth']",
                    "[data-testid*='login']",
                    "[data-testid*='signin']",
                    "[aria-label*='login' i]",
                    "[aria-label*='sign in' i]",
                    "form[action*='login' i]",
                    "form[action*='signin' i]",
                    "[role='dialog']",
                ].join(",");

                const hasVisibleAuthContainer = Array.from(document.querySelectorAll(authSelector))
                    .some((el) => isVisible(el));

                const hasVisibleQr = Array.from(document.querySelectorAll("img,canvas"))
                    .some((el) => {
                        if (!isVisible(el)) return false;
                        const cls = `${el.className || ""}`.toLowerCase();
                        const alt = `${el.getAttribute("alt") || ""}`.toLowerCase();
                        const src = `${el.getAttribute("src") || ""}`.toLowerCase();
                        const hint = `${cls} ${alt} ${src}`;
                        return hint.includes("qr") || hint.includes("qrcode");
                    });

                const loggedOut = hasVisibleAuthContainer && (hasPasswordInput || hasAuthLikeInput || hasVisibleQr);
                return {
                    loggedOut,
                    hasVisibleAuthContainer,
                    hasPasswordInput,
                    hasAuthLikeInput,
                    hasVisibleQr,
                };
            }"""
        )
    except Exception:
        return {
            "loggedOut": False,
            "hasVisibleAuthContainer": False,
            "hasPasswordInput": False,
            "hasAuthLikeInput": False,
            "hasVisibleQr": False,
        }


async def _looks_logged_out_page(page) -> bool:
    ui = await _logged_out_ui_signals(page)
    return bool(ui.get("loggedOut"))


async def _looks_logged_in_page(page) -> bool:
    try:
        return await page.evaluate(
            """() => {
                const selectors = [
                    "a[href*='/user/profile/']",
                    "a[href*='/user/']",
                    "a[href*='xiaohongshu.com/user/']",
                ];
                const isVisible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (style.display === "none" || style.visibility === "hidden") return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                return selectors.some((selector) =>
                    Array.from(document.querySelectorAll(selector)).some((el) => isVisible(el))
                );
            }"""
        )
    except Exception:
        return False


async def _trigger_login_prompt(page, *, debug: bool) -> None:
    try:
        clicked = await page.evaluate(
            """() => {
                const candidates = Array.from(document.querySelectorAll("button,a,div[role='button']"));
                for (const el of candidates) {
                    const text = (el.textContent || "").trim().toLowerCase();
                    if (!text) continue;
                    if (
                        text.includes("登录") ||
                        text.includes("登录/注册") ||
                        text.includes("登录注册") ||
                        text.includes("sign in") ||
                        text.includes("login")
                    ) {
                        el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
                        return true;
                    }
                }
                return false;
            }"""
        )
        if clicked:
            logger.info("[xhs_qrcode] triggered login prompt by clicking login entry.")
            return
    except Exception:
        pass
    if debug:
        logger.info("[xhs_qrcode] login entry click not found; keep current page and wait.")


def _extract_cookie_from_list(cookies: list[dict[str, Any]], name: str) -> str:
    for c in cookies:
        if c.get("name") == name and isinstance(c.get("value"), str):
            return c["value"]
    return ""


async def _launch_persistent_context_with_fallback(
    playwright,
    *,
    profile_dir: Path,
    debug: bool,
):
    last_exc: Exception | None = None
    logger.info("[xhs_qrcode] launching chromium persistent context...")
    ctx_opts = get_persistent_context_options(headless=False)
    for attempt in range(1, 4):
        try:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                **ctx_opts,
            )
            logger.info("[xhs_qrcode] chromium context ready profile_dir=%s", profile_dir)
            return context, profile_dir
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "[xhs_qrcode] primary profile launch attempt=%s/3 failed profile_dir=%s err=%s",
                attempt,
                profile_dir,
                exc,
            )
            if attempt < 3:
                await asyncio.sleep(1.2)

    if not ALLOW_TEMP_PROFILE_FALLBACK:
        raise RuntimeError(
            "primary profile launch failed after retries; "
            "temp-profile fallback disabled to avoid opening an extra login window. "
            "Close other Chromium instances using this profile and retry, "
            "or set XHS_ALLOW_TEMP_PROFILE_FALLBACK=1 to enable fallback."
        ) from last_exc

    temp_dir = Path(tempfile.mkdtemp(prefix="xhs_profile_fallback_"))
    logger.warning(
        "[xhs_qrcode] primary profile launch exhausted profile_dir=%s last_err=%s; fallback to temp profile=%s",
        profile_dir,
        last_exc,
        temp_dir,
    )
    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(temp_dir),
        **ctx_opts,
    )
    logger.info("[xhs_qrcode] chromium context ready profile_dir=%s", temp_dir)
    if debug:
        logger.info(
            "[xhs_qrcode] using fallback temp profile for this run; QR scan may be required."
        )
    return context, temp_dir


async def open_qrcode_session(
    *,
    start_url: str,
    timeout_sec: int,
    profile_dir: Path | None = None,
    force_qrcode: bool = False,
    debug: bool = False,
    nologin: bool = False,
) -> QrcodeAuthSession:
    """Open a headed browser, wait for user QR login (or nologin mode), and return cookie session."""
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        raise RuntimeError("playwright is required: uv add playwright") from exc

    logger.info("[xhs_qrcode] starting playwright...")
    p = await async_playwright().start()

    if nologin:
        if debug:
            logger.info("[xhs_qrcode] launching in nologin (incognito) mode")
        ctx_opts = get_context_options(headless=False)
        launch_args = ctx_opts.pop("args", [])
        ctx_opts.pop("headless", None)  # headless is a launch param, not context param
        browser = await p.chromium.launch(headless=False, args=launch_args)
        context = await browser.new_context(**ctx_opts)
        await apply_stealth_to_context(context)
        page = await context.new_page()

        try:
            await page.goto(start_url, wait_until="domcontentloaded")
        except Exception:
            pass

        try:
            close_selectors = [
                ".close-icon",
                ".icon-btn-close",
                "div.close",
                ".login-close",
                "[class*='close-icon']",
                "[class*='icon-btn-close']",
                "img.close",
                "svg.close",
                "svg use[href='#close']",
                "svg use[*|href='#close']",
                "xpath=//*[local-name()='svg']/*[local-name()='use' and contains(@href, '#close')]/..",
                ".icon-close",
            ]

            blocking_containers = [
                ".login-container",
                ".login-modal",
                ".reds-modal",
                ".qrcode",
                "div[class*='login-container']",
                "div[class*='login-modal']",
            ]

            for attempt in range(6):
                await asyncio.sleep(2.0)
                found_any = False

                for sel in close_selectors:
                    try:
                        locator = page.locator(sel)
                        count = await locator.count()
                        if count > 0:
                            for i in range(count):
                                if await locator.nth(i).is_visible():
                                    await locator.nth(i).click(timeout=500)
                                    found_any = True
                    except Exception:
                        pass

                for container_sel in blocking_containers:
                    try:
                        container = page.locator(container_sel).first
                        if await container.is_visible(timeout=500):
                            for btn_sel in close_selectors:
                                btn = container.locator(btn_sel).first
                                if await btn.is_visible():
                                    await btn.click(timeout=500)
                                    found_any = True
                                    break
                    except Exception:
                        pass

                if not found_any:
                    if attempt < 2:
                        continue
                    else:
                        break
                else:
                    await asyncio.sleep(3.0)

        except Exception:
            pass

        cookies = await context.cookies("https://www.xiaohongshu.com")
        cookie_header = _cookies_to_header(cookies)
        a1 = _extract_cookie_value(cookie_header, "a1") or "anonymous"

        return QrcodeAuthSession(
            playwright=p,
            browser=browser,
            context=context,
            page=page,
            cookie_header=cookie_header,
            a1=a1,
        )

    if profile_dir is None:
        profile_dir = Path.cwd() / DEFAULT_PROFILE_DIRNAME
    profile_dir = profile_dir.resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)
    context, profile_dir = await _launch_persistent_context_with_fallback(
        p, profile_dir=profile_dir, debug=debug
    )
    # Stealth at context level: applies to all future navigations
    await apply_stealth_to_context(context)
    page = next(
        (
            p_
            for p_ in reversed(context.pages)
            if (p_.url or "").startswith("https://www.xiaohongshu.com")
        ),
        None,
    )
    if page is None:
        page = context.pages[-1] if context.pages else await context.new_page()
    # Patch the current document if it was already loaded from profile
    _stealth_js = get_stealth_js()
    if _stealth_js.strip():
        try:
            await page.evaluate(_stealth_js)
        except Exception:
            pass
    pages_before = len(context.pages)
    for p_ in list(context.pages):
        if p_ is page:
            continue
        try:
            await p_.close()
        except Exception:
            continue
    if debug:
        logger.info(
            "[xhs_qrcode] context pages normalized before=%s after=%s active_url=%s",
            pages_before,
            len(context.pages),
            getattr(page, "url", ""),
        )
        page.on("framenavigated", lambda frame: logger.info(f"[xhs_qrcode][nav] {frame.url}"))

    try:
        current_url = page.url or ""
        is_xhs_page = current_url.startswith("https://www.xiaohongshu.com")
        if not is_xhs_page:
            await page.goto(start_url, wait_until="domcontentloaded")
        if force_qrcode:
            await context.clear_cookies()
            await page.goto(start_url, wait_until="domcontentloaded")
        if not force_qrcode:
            cookies = await context.cookies("https://www.xiaohongshu.com")

            # Debug: show what cookies we found in the profile
            xhs_names = [c.get("name") for c in cookies]
            a1_cookie = next((c for c in cookies if c.get("name") == "a1"), None)
            id_token_cookie = next((c for c in cookies if c.get("name") == "id_token"), None)
            logger.info(
                "[xhs_qrcode] profile cookies: count=%d names=%s a1=%s id_token=%s",
                len(cookies),
                xhs_names[:10],
                bool(a1_cookie and a1_cookie.get("value")),
                bool(id_token_cookie and id_token_cookie.get("value")),
            )
            if id_token_cookie:
                logger.info(
                    "[xhs_qrcode] id_token expires=%s expired=%s",
                    id_token_cookie.get("expires"),
                    _is_cookie_expired(id_token_cookie),
                )

            # If cookies are empty, try restoring from backup storage_state.json
            if not _is_logged_in_from_cookies(cookies):
                state_path = profile_dir / "storage_state.json"
                if state_path.is_file():
                    logger.info(
                        "[xhs_qrcode] no valid cookies in profile, restoring from %s",
                        state_path,
                    )
                    try:
                        import json as _json

                        state_data = _json.loads(state_path.read_text(encoding="utf-8"))
                        saved_cookies = state_data.get("cookies", [])
                        if saved_cookies:
                            await context.add_cookies(saved_cookies)
                            await page.reload(wait_until="domcontentloaded")
                            cookies = await context.cookies("https://www.xiaohongshu.com")
                            logger.info(
                                "[xhs_qrcode] restored %d cookies from backup",
                                len(saved_cookies),
                            )
                    except Exception as restore_exc:
                        logger.warning("[xhs_qrcode] cookie restore failed: %s", restore_exc)

            cookie_header = _cookies_to_header(cookies)
            if _is_logged_in_from_cookies(cookies):
                a1 = _extract_cookie_value(cookie_header, "a1")
                return QrcodeAuthSession(
                    playwright=p,
                    browser=None,
                    context=context,
                    page=page,
                    cookie_header=cookie_header,
                    a1=a1,
                )

        deadline = time.monotonic() + timeout_sec
        wait_started = time.monotonic()
        next_heartbeat = time.monotonic() + LOGIN_HEARTBEAT_SEC
        login_prompt_triggered = False
        while time.monotonic() < deadline:
            try:
                cookies = await context.cookies("https://www.xiaohongshu.com")
            except Exception as exc:
                raise RuntimeError(
                    "browser context closed while waiting for login; "
                    "please keep browser window open and retry"
                ) from exc
            cookie_header = _cookies_to_header(cookies)
            if _is_logged_in_from_cookies(cookies):
                await asyncio.sleep(LOGIN_REDIRECT_WAIT_SEC)
                cookies = await context.cookies("https://www.xiaohongshu.com")
                cookie_header = _cookies_to_header(cookies)
                a1 = _extract_cookie_value(cookie_header, "a1")
                return QrcodeAuthSession(
                    playwright=p,
                    browser=None,
                    context=context,
                    page=page,
                    cookie_header=cookie_header,
                    a1=a1,
                )
            if (
                not login_prompt_triggered
                and (time.monotonic() - wait_started) >= 20.0
                and not _is_logged_in_from_cookies(cookies)
            ):
                await _trigger_login_prompt(page, debug=debug)
                login_prompt_triggered = True
            now = time.monotonic()
            if now >= next_heartbeat:
                remain = max(0, int(deadline - now))
                logger.info(
                    "[xhs_qrcode] waiting for login confirmation... remaining=%ss",
                    remain,
                )
                next_heartbeat = now + LOGIN_HEARTBEAT_SEC
            await asyncio.sleep(1)
    except Exception:
        await context.close()
        await p.stop()
        raise

    await context.close()
    await p.stop()
    raise RuntimeError("QR code login timed out. Please scan and finish login, then retry.")
