"""API-based XHS tag tracker — search -> detail -> comments via pure HTTP.

Ported from XHS_Scraper/example/api_tag_tracker.py. Uses XhsApiClient for all
data collection (browser page is only kept for cryptographic signing).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from data_collection.xhs.api_client import XhsApiClient
from data_collection.xhs.request_utils import RequestThrottleConfig
from data_collection.xhs.tag_tracker.config import TagTrackConfig
from data_collection.xhs.tag_tracker.helpers import (
    append_snapshot,
    extract_content_fields,
    extract_metrics,
    extract_note_id,
    extract_note_tags,
    extract_publish_time,
    extract_xsec_token,
    is_note_item,
    load_tracker,
    now_iso,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core tracking logic
# ---------------------------------------------------------------------------


def _build_top_commenters(comments: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    """Extract top-N commenters from a flat comment list."""
    counter: Counter[str] = Counter()
    for c in comments:
        user_info = c.get("user_info") or {}
        nickname = user_info.get("nickname") or user_info.get("nick_name") or ""
        if isinstance(nickname, str) and nickname.strip():
            counter[nickname.strip()] += 1
    return [{"nickname": name, "count": count} for name, count in counter.most_common(top_n)]


async def _run_tracking_async(
    *,
    tags: list[str],
    out_path: Path,
    pages_per_tag: int,
    page_size: int,
    max_comments_per_note: int,
    top_commenters_per_note: int,
    max_history_per_note: int,
    skip_detail_older_than_days: int,
    throttle_config: RequestThrottleConfig,
    login_timeout_sec: int,
    post_login_wait_sec: float,
    session_profile_dir: Path | None,
    force_qrcode: bool,
    nologin: bool,
    debug: bool,
) -> dict[str, Any]:
    """Run a single tracking pass for all tags using pure HTTP API."""

    summary: dict[str, Any] = {
        "started_at": now_iso(),
        "tags": tags,
        "notes_discovered": 0,
        "notes_updated": 0,
        "notes_skipped_old": 0,
        "errors": [],
    }

    store = load_tracker(out_path)
    notes_map: dict[str, Any] = store["notes"]
    cutoff_date = datetime.now().date() - timedelta(days=skip_detail_older_than_days)

    async with XhsApiClient(
        throttle_config=throttle_config,
        login_timeout_sec=login_timeout_sec,
        post_login_wait_sec=post_login_wait_sec,
        session_profile_dir=session_profile_dir,
        force_qrcode=force_qrcode,
        nologin=nologin,
        debug=debug,
    ) as api:
        for tag in tags:
            logger.info("[tag_tracker] === processing tag: %s ===", tag)
            search_items: list[dict[str, Any]] = []

            # 1) Search pages
            for page_no in range(1, pages_per_tag + 1):
                try:
                    data = await api.search_notes(tag, page=page_no, page_size=page_size)
                except Exception as exc:
                    logger.error("[tag_tracker] search error tag=%s page=%s: %s", tag, page_no, exc)
                    summary["errors"].append({"tag": tag, "page": page_no, "error": str(exc)})
                    break

                items = data.get("items")
                if not isinstance(items, list):
                    break
                note_items = [x for x in items if isinstance(x, dict) and is_note_item(x)]
                search_items.extend(note_items)
                logger.info(
                    "[tag_tracker] search tag=%s page=%s/%s items=%s",
                    tag,
                    page_no,
                    pages_per_tag,
                    len(note_items),
                )
                if not data.get("has_more", False):
                    break

            # 2) Process each discovered note
            for item in search_items:
                note_id = extract_note_id(item)
                if not note_id:
                    continue
                xsec_token = extract_xsec_token(item)
                summary["notes_discovered"] += 1

                # Check age from search card data
                pub_raw, pub_date_str = extract_publish_time(item)
                is_old = False
                if pub_date_str:
                    try:
                        pub_date = datetime.strptime(pub_date_str, "%Y-%m-%d").date()
                        is_old = pub_date < cutoff_date
                    except ValueError:
                        pass

                # Initialize note record
                note_rec = notes_map.setdefault(
                    note_id,
                    {
                        "note_id": note_id,
                        "first_seen_at": now_iso(),
                        "tags_seen": [],
                    },
                )
                note_rec["last_seen_at"] = now_iso()
                if tag not in note_rec.get("tags_seen", []):
                    note_rec.setdefault("tags_seen", []).append(tag)

                # Extract card-level data
                card_content = extract_content_fields(item)
                card_metrics = extract_metrics(item)
                card_tags = extract_note_tags(item)

                if is_old:
                    # Card-only snapshot for old notes
                    snapshot = {
                        "crawled_at": now_iso(),
                        "source": "api_search_card",
                        "metrics": card_metrics,
                        "note_content": card_content,
                        "note_tags": card_tags,
                        "publish_time_raw": pub_raw,
                        "top_commenters": [],
                        "total_comments_collected": 0,
                    }
                    changed = append_snapshot(
                        note_rec=note_rec,
                        snapshot=snapshot,
                        max_history_per_note=max_history_per_note,
                    )
                    if changed:
                        summary["notes_updated"] += 1
                    summary["notes_skipped_old"] += 1
                    continue

                # 3) Fetch note detail
                detail_content = card_content
                detail_metrics = card_metrics
                detail_tags = card_tags
                try:
                    detail = await api.get_note_detail(note_id, xsec_token)
                    if detail:
                        detail_item = {"note_card": detail}
                        detail_content = extract_content_fields(detail_item)
                        detail_metrics = extract_metrics(detail_item)
                        detail_tags = extract_note_tags(detail_item)
                except Exception as exc:
                    logger.warning("[tag_tracker] detail error note=%s: %s", note_id, exc)

                # 4) Fetch comments
                comments: list[dict[str, Any]] = []
                top_commenters: list[dict[str, Any]] = []
                try:
                    comments = await api.get_all_comments(
                        note_id,
                        xsec_token,
                        max_count=max_comments_per_note,
                    )
                    top_commenters = _build_top_commenters(comments, top_commenters_per_note)
                except Exception as exc:
                    logger.warning("[tag_tracker] comments error note=%s: %s", note_id, exc)

                # 5) Build and append snapshot
                snapshot = {
                    "crawled_at": now_iso(),
                    "source": "api_detail",
                    "metrics": detail_metrics,
                    "note_content": detail_content,
                    "note_tags": detail_tags,
                    "publish_time_raw": pub_raw,
                    "top_commenters": top_commenters,
                    "total_comments_collected": len(comments),
                }
                changed = append_snapshot(
                    note_rec=note_rec,
                    snapshot=snapshot,
                    max_history_per_note=max_history_per_note,
                )
                if changed:
                    summary["notes_updated"] += 1

            logger.info(
                "[tag_tracker] tag=%s done, discovered=%s",
                tag,
                len(search_items),
            )

    # Save tracker
    store["updated_at"] = now_iso()
    run_record = {
        "crawled_at": now_iso(),
        "mode": "api",
        "tags": tags,
        "notes_discovered": summary["notes_discovered"],
        "notes_updated": summary["notes_updated"],
    }
    store["runs"].append(run_record)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("[tag_tracker] saved tracker to %s", out_path)

    summary["finished_at"] = now_iso()
    return summary


def run_tracking_once(cfg: TagTrackConfig) -> dict[str, Any]:
    """Synchronous wrapper for a single tracking pass."""
    throttle_config = RequestThrottleConfig(
        global_max_rps=cfg.max_rps,
        comment_max_rps=cfg.comment_max_rps,
        request_jitter_sec=cfg.request_jitter_sec,
        comment_failure_streak_threshold=cfg.comment_failure_streak_threshold,
        comment_failure_cooldown_base_sec=cfg.comment_failure_cooldown_sec,
    )
    return asyncio.run(
        _run_tracking_async(
            tags=cfg.tags,
            out_path=cfg.out_path,
            pages_per_tag=cfg.pages_per_tag,
            page_size=cfg.page_size,
            max_comments_per_note=cfg.max_comments_per_note,
            top_commenters_per_note=cfg.top_commenters_per_note,
            max_history_per_note=cfg.max_history_per_note,
            skip_detail_older_than_days=cfg.skip_detail_older_than_days,
            throttle_config=throttle_config,
            login_timeout_sec=cfg.login_timeout_sec,
            post_login_wait_sec=cfg.post_login_wait_sec,
            session_profile_dir=cfg.session_profile_dir,
            force_qrcode=cfg.force_qrcode,
            nologin=cfg.nologin,
            debug=cfg.debug,
        )
    )


# ---------------------------------------------------------------------------
# Scheduler helpers
# ---------------------------------------------------------------------------


def _heartbeat_sleep(total_sec: float, heartbeat_sec: float) -> None:
    """Sleep for *total_sec* with periodic heartbeat log messages."""
    deadline = time.monotonic() + total_sec
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        chunk = min(remaining, heartbeat_sec)
        logger.info("[tag_tracker] next run in %.0fs", remaining)
        time.sleep(chunk)


def run_interval_scheduler(
    cfg: TagTrackConfig,
    interval_minutes: float = 30.0,
    heartbeat_sec: float = 60.0,
) -> None:
    """Repeat tracking every ``interval_minutes``."""
    interval_sec = interval_minutes * 60.0
    logger.info(
        "[tag_tracker] interval scheduler started, interval=%s min, tags=%s",
        interval_minutes,
        cfg.tags,
    )
    while True:
        try:
            summary = run_tracking_once(cfg)
            logger.info(
                "[tag_tracker] run completed: %s",
                json.dumps(summary, ensure_ascii=False),
            )
        except KeyboardInterrupt:
            raise
        except Exception:
            logger.exception("[tag_tracker] run failed")
        _heartbeat_sleep(interval_sec, heartbeat_sec)


def run_daily_scheduler(
    cfg: TagTrackConfig,
    run_at: str,
    heartbeat_sec: float = 60.0,
) -> None:
    """Run tracking once daily at ``run_at`` (HH:MM)."""
    m = re.match(r"^(\d{2}):(\d{2})$", run_at.strip())
    if not m:
        raise ValueError("run_at must be HH:MM")
    hour, minute = int(m.group(1)), int(m.group(2))

    logger.info(
        "[tag_tracker] daily scheduler started, run_at=%s, tags=%s",
        run_at,
        cfg.tags,
    )

    # Immediate startup run
    try:
        summary = run_tracking_once(cfg)
        logger.info(
            "[tag_tracker] startup run completed: %s", json.dumps(summary, ensure_ascii=False)
        )
    except Exception:
        logger.exception("[tag_tracker] startup run failed")

    while True:
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        wait_sec = (target - now).total_seconds()
        logger.info("[tag_tracker] next daily run at %s (in %.0fs)", target.isoformat(), wait_sec)
        _heartbeat_sleep(wait_sec, heartbeat_sec)
        try:
            summary = run_tracking_once(cfg)
            logger.info(
                "[tag_tracker] daily run completed: %s", json.dumps(summary, ensure_ascii=False)
            )
        except KeyboardInterrupt:
            raise
        except Exception:
            logger.exception("[tag_tracker] daily run failed")
