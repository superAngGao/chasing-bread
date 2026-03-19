"""Consistent browser fingerprint configuration for anti-detection.

Centralizes User-Agent, sec-ch-ua, viewport, locale, timezone, and
stealth script injection so that every browser session presents a
consistent, stable identity.

IMPORTANT: The fingerprint must stay STABLE across restarts so that
persistent profiles retain cookies.  Do NOT change UA platform/OS
without clearing the chromium profile — XHS will invalidate sessions
if the environment fingerprint shifts.
"""

from __future__ import annotations

import platform
import random
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Chrome version must be consistent across UA, sec-ch-ua, and HTTP headers.
# Update all three together when bumping.
# ---------------------------------------------------------------------------
CHROME_MAJOR = 137
CHROME_FULL = f"{CHROME_MAJOR}.0.0.0"

# Detect real OS for a stable UA that matches the actual Chromium binary.
# Switching between Windows/macOS UA resets XHS sessions.
_SYSTEM = platform.system()
if _SYSTEM == "Darwin":
    _UA_PLATFORM = "Macintosh; Intel Mac OS X 10_15_7"
    SEC_CH_UA_PLATFORM = '"macOS"'
elif _SYSTEM == "Linux":
    _UA_PLATFORM = "X11; Linux x86_64"
    SEC_CH_UA_PLATFORM = '"Linux"'
else:  # Windows
    _UA_PLATFORM = "Windows NT 10.0; Win64; x64"
    SEC_CH_UA_PLATFORM = '"Windows"'

USER_AGENT = (
    f"Mozilla/5.0 ({_UA_PLATFORM}) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    f"Chrome/{CHROME_FULL} Safari/537.36"
)

SEC_CH_UA = (
    f'"Chromium";v="{CHROME_MAJOR}", "Google Chrome";v="{CHROME_MAJOR}", "Not-A.Brand";v="24"'
)
SEC_CH_UA_MOBILE = "?0"

VIEWPORT = {"width": 1280, "height": 800}
LOCALE = "zh-CN"
TIMEZONE = "Asia/Shanghai"

# Path to MediaCrawler's bundled stealth script
_STEALTH_JS_PATH = (
    Path(__file__).resolve().parents[2] / "vendor" / "MediaCrawler" / "libs" / "stealth.min.js"
)

# Extra JS patches applied after stealth.min.js
_EXTRA_STEALTH_JS = """\
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5]
});
Object.defineProperty(navigator, 'languages', {
    get: () => ['zh-CN', 'zh', 'en']
});
window.chrome = window.chrome || {};
window.chrome.runtime = window.chrome.runtime || {};
"""


def get_stealth_js() -> str:
    """Return the full stealth init script (stealth.min.js + extra patches)."""
    parts: list[str] = []
    if _STEALTH_JS_PATH.is_file():
        parts.append(_STEALTH_JS_PATH.read_text(encoding="utf-8"))
    parts.append(_EXTRA_STEALTH_JS)
    return "\n".join(parts)


def get_launch_args() -> list[str]:
    """Chromium launch args for anti-detection."""
    return [
        "--disable-blink-features=AutomationControlled",
    ]


def get_persistent_context_options(*, headless: bool = False) -> dict[str, Any]:
    """Options for ``launch_persistent_context``.

    MINIMAL options to avoid breaking cookie persistence.
    Do NOT add geolocation, permissions, or platform-changing settings
    here — those interfere with profile stability.
    """
    return {
        "headless": headless,
        "viewport": VIEWPORT,
        "locale": LOCALE,
        "timezone_id": TIMEZONE,
        "args": get_launch_args(),
    }


def get_context_options(*, headless: bool = False) -> dict[str, Any]:
    """Full options for ephemeral contexts (``browser.new_context``).

    Includes all fingerprint settings. Safe because ephemeral contexts
    don't persist cookies across runs.
    """
    return {
        "headless": headless,
        "user_agent": USER_AGENT,
        "viewport": VIEWPORT,
        "locale": LOCALE,
        "timezone_id": TIMEZONE,
        "args": get_launch_args(),
        "extra_http_headers": {
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "sec-ch-ua": SEC_CH_UA,
            "sec-ch-ua-mobile": SEC_CH_UA_MOBILE,
            "sec-ch-ua-platform": SEC_CH_UA_PLATFORM,
        },
    }


def get_http_headers(cookie_header: str) -> dict[str, str]:
    """Build HTTP headers for direct API requests (httpx), matching the browser fingerprint."""
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "cache-control": "no-cache",
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://www.xiaohongshu.com",
        "pragma": "no-cache",
        "referer": "https://www.xiaohongshu.com/",
        "sec-ch-ua": SEC_CH_UA,
        "sec-ch-ua-mobile": SEC_CH_UA_MOBILE,
        "sec-ch-ua-platform": SEC_CH_UA_PLATFORM,
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": USER_AGENT,
        "Cookie": cookie_header,
    }


async def apply_stealth(page: Any) -> None:
    """Inject stealth scripts into a Playwright page."""
    js = get_stealth_js()
    if js.strip():
        await page.add_init_script(js)


async def warmup_session(page: Any, *, scrolls: int = 3) -> None:
    """Simulate human-like browsing to warm up the session before API calls.

    Scrolls the page a few times with random delays to build trust signals.
    """
    import asyncio

    for _ in range(scrolls):
        scroll_y = random.randint(300, 700)
        await page.mouse.wheel(0, scroll_y)
        await asyncio.sleep(random.gauss(1.5, 0.4))
    # Scroll back up partially
    await page.mouse.wheel(0, -random.randint(100, 300))
    await asyncio.sleep(random.gauss(1.0, 0.3))
