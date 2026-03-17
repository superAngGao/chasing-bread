"""Error types for the XHS MediaCrawler API layer."""

from __future__ import annotations

import re
from typing import Any


class XhsApiError(RuntimeError):
    def __init__(self, *, endpoint: str, code: int | None, msg: str | None, payload: Any):
        self.endpoint = endpoint
        self.code = code
        self.msg = msg or "unknown"
        self.payload = payload
        super().__init__(f"{endpoint} failed: code={self.code}, msg={self.msg}")


class PageNavigatedError(RuntimeError):
    """Raised when the browser page navigated away from the expected URL."""

    def __init__(self, expected: str, actual: str, context: str = ""):
        self.expected = expected
        self.actual = actual
        self.context = context
        super().__init__(
            f"page navigated away during {context}: "
            f"expected URL containing '{expected}', got '{actual}'"
        )


def is_account_state_error(code: int | None, msg: str | None) -> bool:
    if code in {-104, -100, -101, 461, 300011, 300012, 300013}:
        return True
    text = (msg or "").lower()
    keywords = (
        "无登录",
        "登录",
        "账号",
        "异常",
        "权限",
        "风控",
        "risk",
        "forbidden",
        "unauthorized",
        "verifytype",
    )
    return any(k in text for k in keywords)


def check_page_url(page, *, expected: str, context: str = "") -> None:
    current_url = getattr(page, "url", "") or ""
    if expected and expected not in current_url:
        if _looks_like_rate_limit_redirect(current_url):
            raise XhsApiError(
                endpoint=context or "unknown",
                code=300013,
                msg="页面在操作中被刷新或重定向",
                payload={"expected": expected, "actual": current_url, "context": context},
            )
        raise PageNavigatedError(expected, current_url, context)


def _looks_like_rate_limit_redirect(url: str | None) -> bool:
    if not url:
        return False
    u = url.rstrip("/")
    if u in {"https://www.xiaohongshu.com/explore", "https://www.xiaohongshu.com"}:
        return True
    lower = url.lower()
    if "website-login/error" in lower:
        if (
            "error_code=300013" in lower
            or "error_msg=%e8%ae%bf%e9%97%ae%e9%a2%91%e7%b9%81" in lower
            or "httpstatus=461" in lower
            or "verif" in lower
            or "300013" in lower
        ):
            return True
    return False


def _extract_code_from_error_text(text: str) -> int | None:
    text = text or ""
    if "登录已过期" in text:
        return -100
    if "无登录信息" in text:
        return -101
    if "没有权限访问" in text:
        return -104
    m = re.search(r"\b(-?\d{2,6})\b", text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def to_api_error(endpoint: str, exc: Exception) -> XhsApiError:
    msg = str(exc) or exc.__class__.__name__
    try:
        from tenacity import RetryError  # type: ignore
    except Exception:
        RetryError = None  # type: ignore

    if RetryError is not None and isinstance(exc, RetryError):
        inner_exc = None
        try:
            inner_exc = exc.last_attempt.exception()
        except Exception:
            inner_exc = None
        if inner_exc is not None:
            msg = str(inner_exc) or msg

    code = None
    if " 461" in msg or "status code 461" in msg:
        code = 461
    else:
        code = _extract_code_from_error_text(msg)
    return XhsApiError(endpoint=endpoint, code=code, msg=msg, payload={"error": repr(exc)})
