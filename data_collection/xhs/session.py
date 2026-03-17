"""Reusable XHS authenticated browser session helpers."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypeVar

from data_collection.xhs.qrcode_auth import QrcodeAuthSession, open_qrcode_session

HOME_URL = "https://www.xiaohongshu.com/"
logger = logging.getLogger(__name__)
_AUTH_RETRY_CODES = {-100, -101, -104}
T = TypeVar("T")


async def _wait_for_signing_ready(*, page, timeout_sec: float, debug: bool) -> bool:
    deadline = time.monotonic() + max(timeout_sec, 1.0)
    stable_hits = 0
    while time.monotonic() < deadline:
        try:
            ready = await page.evaluate(
                """() => {
                    const docReady = document.readyState === "interactive" || document.readyState === "complete";
                    const signerReady = typeof window.mnsv2 === "function";
                    return docReady && signerReady;
                }"""
            )
        except Exception:
            ready = False

        if ready:
            stable_hits += 1
            if stable_hits >= 2:
                if debug:
                    logger.info("[xhs_session] signing runtime ready.")
                return True
        else:
            stable_hits = 0
        await asyncio.sleep(0.4)

    if debug:
        logger.info(f"[xhs_session] signing runtime wait timeout after {timeout_sec:.1f}s.")
    return False


async def open_xhs_api_session(
    *,
    login_timeout_sec: int,
    post_login_wait_sec: float,
    session_profile_dir: Path | None,
    force_qrcode: bool,
    debug: bool,
    start_url: str = HOME_URL,
    nologin: bool = False,
) -> QrcodeAuthSession:
    """Open authenticated XHS session and wait until signing runtime is ready."""
    if post_login_wait_sec < 0:
        raise ValueError("post_login_wait_sec must be >= 0")

    session = await open_qrcode_session(
        start_url=start_url,
        timeout_sec=login_timeout_sec,
        profile_dir=session_profile_dir,
        force_qrcode=force_qrcode,
        debug=debug,
        nologin=nologin,
    )
    try:
        page = session.page
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=15_000)
        except Exception:
            if debug:
                logger.info(
                    "[xhs_session] domcontentloaded wait timeout; continue with signing checks."
                )

        await _wait_for_signing_ready(page=page, timeout_sec=20.0, debug=debug)
        if post_login_wait_sec > 0:
            await asyncio.sleep(post_login_wait_sec)
        return session
    except Exception:
        await session.close()
        raise


async def hold_and_close_session(
    session: QrcodeAuthSession,
    *,
    hold: bool = False,
    reason: str = "",
) -> None:
    if hold:
        msg = reason.strip() or "debug hold requested"
        logger.warning(
            "[xhs_session] hold browser before close: %s. Press Enter to close browser.",
            msg,
        )
        try:
            await asyncio.to_thread(input)
        except Exception:
            pass
    await session.close()


def get_exception_code(exc: Exception) -> int | None:
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    return None


def should_force_qrcode_retry(exc: Exception, *, force_qrcode: bool) -> bool:
    if force_qrcode:
        return False
    code = get_exception_code(exc)
    return code in _AUTH_RETRY_CODES


async def run_with_xhs_session(
    *,
    login_timeout_sec: int,
    post_login_wait_sec: float,
    session_profile_dir: Path | None,
    force_qrcode: bool,
    debug: bool,
    worker: Callable[[QrcodeAuthSession], Awaitable[T]],
    hold_browser_on_error: bool = False,
    nologin: bool = False,
) -> T:
    async def _run_once(force_flag: bool, hold_on_error: bool) -> T:
        session = await open_xhs_api_session(
            login_timeout_sec=login_timeout_sec,
            post_login_wait_sec=post_login_wait_sec,
            session_profile_dir=session_profile_dir,
            force_qrcode=force_flag,
            debug=debug,
            nologin=nologin,
        )
        should_hold = False
        hold_reason = ""
        try:
            return await worker(session)
        except Exception as exc:
            if hold_on_error and not should_force_qrcode_retry(exc, force_qrcode=force_flag):
                should_hold = True
                hold_reason = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            await hold_and_close_session(session, hold=should_hold, reason=hold_reason)

    try:
        return await _run_once(force_qrcode, hold_browser_on_error)
    except Exception as exc:
        if should_force_qrcode_retry(exc, force_qrcode=force_qrcode):
            logger.warning(
                "[xhs_session] auth/session rejected (code=%s), retry once with forced QR login",
                get_exception_code(exc),
            )
            return await _run_once(True, hold_browser_on_error)
        raise
