"""Debug snapshot utility — captures browser state on unexpected errors.

Saves three artifacts per snapshot:
  1. Screenshot (.png)
  2. Page HTML (.html)
  3. State metadata (.json) — URL, cookies, error info, call chain

All snapshots go to ``data/debug/`` with timestamped filenames.
"""

from __future__ import annotations

import json
import logging
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEBUG_DIR = Path("data/debug")
_MAX_SNAPSHOTS = 50  # Auto-cleanup oldest if exceeded


def _snapshot_dir() -> Path:
    _DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    return _DEBUG_DIR


def _timestamp_prefix() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]


def _cleanup_old_snapshots() -> None:
    """Remove oldest snapshots if count exceeds _MAX_SNAPSHOTS."""
    try:
        files = sorted(_DEBUG_DIR.glob("snapshot_*"), key=lambda p: p.stat().st_mtime)
        # Group by prefix (3 files per snapshot)
        prefixes: list[str] = []
        seen: set[str] = set()
        for f in files:
            # Extract prefix: snapshot_20260319_205342_123
            parts = f.stem.split("_", 4)
            if len(parts) >= 4:
                prefix = "_".join(parts[:4])
                if prefix not in seen:
                    seen.add(prefix)
                    prefixes.append(prefix)
        if len(prefixes) > _MAX_SNAPSHOTS:
            to_remove = prefixes[: len(prefixes) - _MAX_SNAPSHOTS]
            for prefix in to_remove:
                for f in _DEBUG_DIR.glob(f"{prefix}*"):
                    f.unlink(missing_ok=True)
    except Exception:
        pass


def build_state_metadata(
    *,
    trigger: str,
    error: Exception | str | None = None,
    endpoint: str = "",
    phase: str = "",
    extra: dict[str, Any] | None = None,
    page_url: str = "",
    cookies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the state metadata dict for a debug snapshot."""
    state: dict[str, Any] = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "monotonic": time.monotonic(),
        "trigger": trigger,
        "endpoint": endpoint,
        "phase": phase,
        "page_url": page_url,
    }

    if error is not None:
        if isinstance(error, Exception):
            state["error"] = {
                "type": type(error).__name__,
                "message": str(error),
                "code": getattr(error, "code", None),
                "payload": getattr(error, "payload", None),
            }
            state["traceback"] = traceback.format_exception(error)
        else:
            state["error"] = {"message": str(error)}

    # Call chain (abbreviated stack)
    state["call_chain"] = [
        f"{frame.filename}:{frame.lineno} in {frame.name}"
        for frame in traceback.extract_stack()[:-1]  # exclude this function
    ][-10:]  # last 10 frames

    if cookies is not None:
        # Redact cookie values but keep names and expiry
        state["cookies"] = [
            {
                "name": c.get("name"),
                "domain": c.get("domain"),
                "expires": c.get("expires"),
                "has_value": bool(c.get("value")),
            }
            for c in cookies
        ]

    if extra:
        state["extra"] = extra

    return state


async def save_snapshot(
    *,
    page: Any,
    trigger: str,
    error: Exception | str | None = None,
    endpoint: str = "",
    phase: str = "",
    extra: dict[str, Any] | None = None,
) -> Path | None:
    """Capture a debug snapshot: screenshot + HTML + state JSON.

    Args:
        page: Playwright page object (can be None — only state.json is saved).
        trigger: Short label for what triggered the snapshot (e.g. "captcha_461").
        error: The exception or error message.
        endpoint: API endpoint name (search/detail/comment).
        phase: Operation phase (before_search, scroll_loop, etc.).
        extra: Additional context dict.

    Returns:
        Path to the snapshot directory prefix, or None if snapshot failed.
    """
    try:
        out_dir = _snapshot_dir()
        prefix = f"snapshot_{_timestamp_prefix()}_{trigger}"
        base = out_dir / prefix

        page_url = ""
        cookies: list[dict[str, Any]] | None = None

        # 1. Screenshot
        if page is not None:
            try:
                page_url = getattr(page, "url", "") or ""
                await page.screenshot(path=str(base) + ".png", full_page=False)
            except Exception as ss_exc:
                logger.debug("[debug_snapshot] screenshot failed: %s", ss_exc)

            # 2. HTML
            try:
                html = await page.content()
                (base.parent / (prefix + ".html")).write_text(html, encoding="utf-8")
            except Exception as html_exc:
                logger.debug("[debug_snapshot] HTML capture failed: %s", html_exc)

            # 3. Cookies
            try:
                cookies = await page.context.cookies()
            except Exception:
                pass

        # 4. State JSON
        state = build_state_metadata(
            trigger=trigger,
            error=error,
            endpoint=endpoint,
            phase=phase,
            extra=extra,
            page_url=page_url,
            cookies=cookies,
        )
        state_path = base.parent / (prefix + ".json")
        state_path.write_text(
            json.dumps(state, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        logger.info("[debug_snapshot] saved: %s", base)
        _cleanup_old_snapshots()
        return base

    except Exception as exc:
        logger.warning("[debug_snapshot] snapshot failed: %s", exc)
        return None


def save_snapshot_sync(
    *,
    trigger: str,
    error: Exception | str | None = None,
    endpoint: str = "",
    phase: str = "",
    extra: dict[str, Any] | None = None,
) -> Path | None:
    """Synchronous snapshot (no page/screenshot, just state JSON)."""
    try:
        out_dir = _snapshot_dir()
        prefix = f"snapshot_{_timestamp_prefix()}_{trigger}"
        base = out_dir / prefix

        state = build_state_metadata(
            trigger=trigger,
            error=error,
            endpoint=endpoint,
            phase=phase,
            extra=extra,
        )
        state_path = base.parent / (prefix + ".json")
        state_path.write_text(
            json.dumps(state, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        logger.info("[debug_snapshot] saved: %s", state_path)
        _cleanup_old_snapshots()
        return base

    except Exception as exc:
        logger.warning("[debug_snapshot] snapshot failed: %s", exc)
        return None
