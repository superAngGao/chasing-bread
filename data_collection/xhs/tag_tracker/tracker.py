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
from typing import Any

from data_collection.xhs.api_client import XhsApiClient
from data_collection.xhs.error_handler import ErrorType, XhsErrorHandler
from data_collection.xhs.mc_api._errors import XhsApiError
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
    to_int,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abort handling
# ---------------------------------------------------------------------------


class AccountStateAbort(RuntimeError):
    """Raised when auth or rate-limit makes the run unrecoverable."""

    def __init__(self, reason: dict[str, Any], error_type: ErrorType | None = None):
        self.reason = reason
        self.error_type = error_type
        super().__init__(f"account state abnormal: {reason}")


def _build_abort_info(
    *, phase: str, tag: str | None, err: XhsApiError, config: TagTrackConfig
) -> dict[str, Any]:
    return {
        "time": now_iso(),
        "phase": phase,
        "tag": tag,
        "endpoint": err.endpoint,
        "code": err.code,
        "msg": err.msg,
        "limiter": {
            "max_rps": config.max_rps,
            "comment_max_rps": config.comment_max_rps,
        },
    }


def _persist_abort_status(
    *,
    store: dict[str, Any],
    run_summary: dict[str, Any],
    config: TagTrackConfig,
    abort: dict[str, Any],
) -> None:
    """Write abort status to tracker file so recovery can check it."""
    store["updated_at"] = now_iso()
    store["last_abort"] = abort
    run_summary["aborted"] = True
    run_summary["abort_reason"] = abort
    runs = store.setdefault("runs", [])
    if isinstance(runs, list):
        runs.append(run_summary)
        if len(runs) > 3650:
            del runs[: len(runs) - 3650]
    config.out_path.parent.mkdir(parents=True, exist_ok=True)
    config.out_path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Comment extraction helpers
# ---------------------------------------------------------------------------


def _extract_top_commenters(comments: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    """Extract top-N commenters with full comment info."""
    out: list[dict[str, Any]] = []
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        user_info = comment.get("user_info")
        if not isinstance(user_info, dict):
            user_info = comment.get("user") if isinstance(comment.get("user"), dict) else {}
        out.append(
            {
                "user_id": user_info.get("user_id")
                or user_info.get("userid")
                or user_info.get("id"),
                "nickname": user_info.get("nickname") or user_info.get("nick_name"),
                "comment_id": comment.get("id"),
                "comment_time": comment.get("create_time_text") or comment.get("create_time"),
                "comment_like_count": to_int(comment.get("like_count")),
                "reply_count": to_int(
                    comment.get("sub_comment_count")
                    or comment.get("sub_comment_num")
                    or comment.get("reply_count")
                ),
                "is_author_liked": bool(
                    comment.get("is_author_like") or comment.get("author_liked")
                ),
                "is_pinned": bool(
                    comment.get("is_selected") or comment.get("is_top") or comment.get("is_pinned")
                ),
                "comment_content": comment.get("content") or comment.get("text"),
            }
        )
        if len(out) >= top_n:
            break
    return out


def _build_top_commenters_simple(
    comments: list[dict[str, Any]], top_n: int
) -> list[dict[str, Any]]:
    """Fallback: simple frequency-based commenter list."""
    counter: Counter[str] = Counter()
    for c in comments:
        user_info = c.get("user_info") or {}
        nickname = user_info.get("nickname") or user_info.get("nick_name") or ""
        if isinstance(nickname, str) and nickname.strip():
            counter[nickname.strip()] += 1
    return [{"nickname": name, "count": count} for name, count in counter.most_common(top_n)]


def _is_publish_time_older_than_days(
    publish_iso: str | None, *, now_dt: datetime, days: int
) -> bool:
    if days < 0 or not publish_iso:
        return False
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", publish_iso):
        return False
    try:
        publish_dt = datetime.strptime(publish_iso, "%Y-%m-%d")
    except ValueError:
        return False
    return (now_dt - publish_dt) > timedelta(days=days)


# ---------------------------------------------------------------------------
# Core tracking logic
# ---------------------------------------------------------------------------


async def _run_tracking_async(config: TagTrackConfig) -> dict[str, Any]:
    """Run a single tracking pass for all tags using pure HTTP API."""
    if not config.tags:
        raise ValueError("at least one tag is required")

    now_dt = datetime.now()
    now_str = now_iso()
    error_handler = XhsErrorHandler(logger)

    run_summary: dict[str, Any] = {
        "crawled_at": now_str,
        "tags": {},
        "auto_added_tags": [],
        "notes_discovered": 0,
        "notes_updated": 0,
        "notes_skipped_old": 0,
        "errors": [],
    }

    store = load_tracker(config.out_path)
    notes_map: dict[str, Any] = store["notes"]

    throttle_config = RequestThrottleConfig(
        global_max_rps=config.max_rps,
        comment_max_rps=config.comment_max_rps,
        request_jitter_sec=config.request_jitter_sec,
        comment_jitter_sec=config.comment_jitter_sec,
        comment_failure_streak_threshold=config.comment_failure_streak_threshold,
        comment_failure_cooldown_base_sec=config.comment_failure_cooldown_sec,
    )

    # Build deduplicated tag queue (supports auto-expand)
    queued_lower: set[str] = set()
    tag_queue: list[str] = []
    for seed_tag in config.tags:
        key = seed_tag.strip().lower()
        if not key:
            continue
        if key in queued_lower:
            continue
        queued_lower.add(key)
        tag_queue.append(seed_tag.strip())

    logger.info("[tag_tracker] initial tag queue: %s", ",".join(tag_queue))
    auto_added_count = 0
    comment_failure_streak = 0
    comment_cooldown_until_ts = 0.0
    comment_cooldown_level = 0

    async with XhsApiClient(
        throttle_config=throttle_config,
        login_timeout_sec=config.login_timeout_sec,
        post_login_wait_sec=config.post_login_wait_sec,
        session_profile_dir=config.session_profile_dir,
        force_qrcode=config.force_qrcode,
        nologin=config.nologin,
        debug=config.debug,
    ) as api:
        idx = 0
        while idx < len(tag_queue):
            tag = tag_queue[idx]
            idx += 1
            logger.info(
                "[tag_tracker] processing tag=%s queue_pos=%s/%s",
                tag,
                idx,
                len(tag_queue),
            )

            new_added = 0
            updated = 0
            skipped_old = 0
            seen_ids: set[str] = set()
            note_tag_hits: dict[str, int] = {}
            search_items: list[dict[str, Any]] = []

            # ---- 1) Search pages ----
            for page_no in range(1, config.pages_per_tag + 1):
                try:
                    data = await api.search_notes(tag, page=page_no, page_size=config.page_size)
                except XhsApiError as err:
                    err_type = error_handler.classify(err)
                    if err_type in (ErrorType.RATE_LIMIT, ErrorType.AUTH_INVALID):
                        abort = _build_abort_info(phase="search", tag=tag, err=err, config=config)
                        logger.error("[tag_tracker] account state abnormal: %s", abort)
                        _persist_abort_status(
                            store=store,
                            run_summary=run_summary,
                            config=config,
                            abort=abort,
                        )
                        raise AccountStateAbort(abort, error_type=err_type) from err
                    logger.error("[tag_tracker] search error tag=%s page=%s: %s", tag, page_no, err)
                    run_summary["errors"].append({"tag": tag, "page": page_no, "error": str(err)})
                    break
                except Exception as exc:
                    logger.error("[tag_tracker] search error tag=%s page=%s: %s", tag, page_no, exc)
                    run_summary["errors"].append({"tag": tag, "page": page_no, "error": str(exc)})
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
                    config.pages_per_tag,
                    len(note_items),
                )
                if not data.get("has_more", False):
                    break

            # ---- 2) Process each discovered note ----
            for item in search_items:
                note_id = extract_note_id(item)
                if not note_id or note_id in seen_ids:
                    continue
                seen_ids.add(note_id)

                xsec_token = extract_xsec_token(item)
                run_summary["notes_discovered"] += 1

                # Collect note tags for auto-expand
                note_tags = extract_note_tags(item)
                for nt in note_tags:
                    k = nt.strip().lower()
                    if k:
                        note_tag_hits[k] = note_tag_hits.get(k, 0) + 1

                # Check age
                pub_raw, pub_date_str = extract_publish_time(item)
                is_old = _is_publish_time_older_than_days(
                    pub_date_str,
                    now_dt=now_dt,
                    days=config.skip_detail_older_than_days,
                )

                # Check new item cap
                is_new = note_id not in notes_map
                if is_new and new_added >= config.max_new_items_per_tag:
                    continue

                # Initialize/update note record
                note_rec = notes_map.setdefault(
                    note_id,
                    {
                        "note_id": note_id,
                        "first_seen_at": now_str,
                        "tags_seen": [],
                    },
                )
                note_rec["last_seen_at"] = now_str
                if tag not in note_rec.get("tags_seen", []):
                    note_rec.setdefault("tags_seen", []).append(tag)
                if not note_rec.get("publish_time") and pub_date_str:
                    note_rec["publish_time"] = pub_date_str
                note_rec["last_xsec_token"] = xsec_token or note_rec.get("last_xsec_token")

                # Extract card-level data
                card_content = extract_content_fields(item)
                card_metrics = extract_metrics(item)
                card_tags = note_tags

                # Fill in missing top-level fields
                if not note_rec.get("title") and card_content.get("title"):
                    note_rec["title"] = card_content["title"]
                if not note_rec.get("author") and card_content.get("author"):
                    note_rec["author"] = card_content["author"]

                if is_old:
                    snapshot = {
                        "crawled_at": now_str,
                        "source": "api_search_card",
                        "tag": tag,
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
                        max_history_per_note=config.max_history_per_note,
                    )
                    if changed:
                        updated += 1
                    skipped_old += 1
                    run_summary["notes_skipped_old"] += 1
                    continue

                # ---- 3) Fetch note detail ----
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
                        # Also collect tags from detail
                        for nt in detail_tags:
                            k = nt.strip().lower()
                            if k:
                                note_tag_hits[k] = note_tag_hits.get(k, 0) + 1
                except XhsApiError as err:
                    err_type = error_handler.classify(err)
                    if err_type in (ErrorType.RATE_LIMIT, ErrorType.AUTH_INVALID):
                        abort = _build_abort_info(phase="detail", tag=tag, err=err, config=config)
                        _persist_abort_status(
                            store=store,
                            run_summary=run_summary,
                            config=config,
                            abort=abort,
                        )
                        raise AccountStateAbort(abort, error_type=err_type) from err
                    logger.warning("[tag_tracker] detail error note=%s: %s", note_id, err)
                except Exception as exc:
                    logger.warning("[tag_tracker] detail error note=%s: %s", note_id, exc)

                # ---- 4) Fetch comments with cooldown ----
                comments: list[dict[str, Any]] = []
                top_commenters: list[dict[str, Any]] = []

                # Check cooldown
                cooldown_left = comment_cooldown_until_ts - time.monotonic()
                if cooldown_left > 0:
                    logger.warning(
                        "[tag_tracker] comment cooldown active level=%s remaining=%.0fs",
                        comment_cooldown_level,
                        cooldown_left,
                    )
                    await asyncio.sleep(cooldown_left)
                    comment_cooldown_until_ts = 0.0

                try:
                    comments = await api.get_all_comments(
                        note_id,
                        xsec_token,
                        max_count=config.max_comments_per_note,
                    )
                    top_commenters = _extract_top_commenters(
                        comments, config.top_commenters_per_note
                    )

                    # Track comment failure streak
                    expected = detail_metrics.get("comment_count", 0)
                    if expected > 0 and not top_commenters:
                        comment_failure_streak += 1
                    else:
                        comment_failure_streak = 0
                        comment_cooldown_level = 0

                    if comment_failure_streak >= config.comment_failure_streak_threshold:
                        comment_cooldown_level += 1
                        cooldown_sec = min(
                            config.comment_failure_cooldown_sec
                            * (2 ** (comment_cooldown_level - 1)),
                            30 * 60,
                        )
                        comment_cooldown_until_ts = time.monotonic() + cooldown_sec
                        logger.warning(
                            "[tag_tracker] comment failure streak=%s, cooldown level=%s duration=%.0fs",
                            comment_failure_streak,
                            comment_cooldown_level,
                            cooldown_sec,
                        )
                        comment_failure_streak = 0

                except XhsApiError as err:
                    err_type = error_handler.classify(err)
                    if err_type in (ErrorType.RATE_LIMIT, ErrorType.AUTH_INVALID):
                        abort = _build_abort_info(phase="comment", tag=tag, err=err, config=config)
                        _persist_abort_status(
                            store=store,
                            run_summary=run_summary,
                            config=config,
                            abort=abort,
                        )
                        raise AccountStateAbort(abort, error_type=err_type) from err
                    logger.warning("[tag_tracker] comments error note=%s: %s", note_id, err)
                except Exception as exc:
                    logger.warning("[tag_tracker] comments error note=%s: %s", note_id, exc)

                # ---- 5) Build and append snapshot ----
                snapshot = {
                    "crawled_at": now_str,
                    "source": "api_detail",
                    "tag": tag,
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
                    max_history_per_note=config.max_history_per_note,
                )
                if changed:
                    updated += 1
                if is_new:
                    new_added += 1

            # ---- 6) Refresh cached notes ----
            refreshed_cached = 0
            stable_rounds = 0
            if config.refresh_cached and search_items:
                max_rounds = config.stable_max_rounds
                logger.info(
                    "[tag_tracker] tag=%s refresh cached start max_rounds=%s candidates=%s",
                    tag,
                    max_rounds,
                    sum(
                        1
                        for nid, n in notes_map.items()
                        if nid not in seen_ids
                        and isinstance(n, dict)
                        and isinstance(n.get("tags_seen"), list)
                        and tag in n["tags_seen"]
                    ),
                )
                for round_idx in range(max_rounds):
                    changed_in_round = 0
                    refreshed_in_round = 0
                    for note_id, note_rec in notes_map.items():
                        if note_id in seen_ids:
                            continue
                        if not isinstance(note_rec, dict):
                            continue
                        tags_seen = note_rec.get("tags_seen")
                        if not isinstance(tags_seen, list) or tag not in tags_seen:
                            continue

                        note_rec["last_seen_at"] = now_str
                        xsec_token = note_rec.get("last_xsec_token")
                        if not isinstance(xsec_token, str) or not xsec_token:
                            continue

                        # Use latest metrics if available
                        latest = (
                            note_rec.get("latest")
                            if isinstance(note_rec.get("latest"), dict)
                            else {}
                        )
                        metrics = latest.get("metrics") if isinstance(latest, dict) else {}
                        if not isinstance(metrics, dict):
                            metrics = {}

                        snapshot = {
                            "crawled_at": now_str,
                            "source": "api_refresh",
                            "tag": tag,
                            "metrics": metrics,
                            "note_content": {
                                "title": note_rec.get("title"),
                                "author": note_rec.get("author"),
                                "content": note_rec.get("content"),
                            },
                            "note_tags": note_rec.get("note_tags", [])
                            if isinstance(note_rec.get("note_tags"), list)
                            else [],
                            "publish_time_raw": note_rec.get("publish_time_raw"),
                            "top_commenters": [],
                            "total_comments_collected": 0,
                        }
                        changed = append_snapshot(
                            note_rec=note_rec,
                            snapshot=snapshot,
                            max_history_per_note=config.max_history_per_note,
                        )
                        refreshed_in_round += 1
                        if changed:
                            changed_in_round += 1
                            updated += 1

                    refreshed_cached += refreshed_in_round
                    stable_rounds = round_idx + 1
                    logger.info(
                        "[tag_tracker] tag=%s refresh round=%s refreshed=%s changed=%s",
                        tag,
                        round_idx + 1,
                        refreshed_in_round,
                        changed_in_round,
                    )
                    if changed_in_round == 0:
                        logger.info(
                            "[tag_tracker] tag=%s reached stable state at round=%s",
                            tag,
                            round_idx + 1,
                        )
                        break
                    if config.stable_round_delay_sec > 0 and round_idx + 1 < max_rounds:
                        await asyncio.sleep(config.stable_round_delay_sec)

            # ---- 7) Auto-expand tags ----
            fetched_count = len(seen_ids)
            if (
                config.auto_expand_tags
                and fetched_count > 0
                and auto_added_count < config.max_auto_expand_tags
            ):
                existing = {x.lower() for x in tag_queue}
                for hit_tag_lower, count in sorted(
                    note_tag_hits.items(), key=lambda x: x[1], reverse=True
                ):
                    if auto_added_count >= config.max_auto_expand_tags:
                        break
                    if hit_tag_lower in existing:
                        continue
                    hit_rate = count / fetched_count
                    if hit_rate < config.auto_expand_hit_rate_threshold:
                        continue
                    tag_queue.append(hit_tag_lower)
                    existing.add(hit_tag_lower)
                    auto_added_count += 1
                    run_summary["auto_added_tags"].append(
                        {"tag": hit_tag_lower, "from_tag": tag, "hit_rate": round(hit_rate, 4)}
                    )
                    logger.info(
                        "[tag_tracker] auto-added tag=%s from=%s hit_rate=%.2f",
                        hit_tag_lower,
                        tag,
                        hit_rate,
                    )

            # Store tag hit stats
            if isinstance(store.get("tag_hit_stats"), dict):
                tag_hit_stats = store["tag_hit_stats"]
            else:
                tag_hit_stats = {}
                store["tag_hit_stats"] = tag_hit_stats
            for hit_tag_lower, count in note_tag_hits.items():
                rec = tag_hit_stats.get(hit_tag_lower)
                if not isinstance(rec, dict):
                    rec = {
                        "tag": hit_tag_lower,
                        "hit_count": 0,
                        "total_seen": 0,
                        "last_hit_rate": 0.0,
                    }
                    tag_hit_stats[hit_tag_lower] = rec
                rec["hit_count"] = int(rec.get("hit_count", 0)) + count
                rec["total_seen"] = int(rec.get("total_seen", 0)) + fetched_count
                total_seen = int(rec.get("total_seen", 0))
                rec["last_hit_rate"] = (
                    (int(rec.get("hit_count", 0)) / total_seen) if total_seen > 0 else 0.0
                )

            run_summary["tags"][tag] = {
                "fetched": len(search_items),
                "new_added": new_added,
                "updated": updated,
                "skipped_old": skipped_old,
                "refreshed_cached": refreshed_cached,
                "stable_rounds": stable_rounds,
            }
            run_summary["notes_updated"] += updated
            run_summary["notes_skipped_old"] += skipped_old

            logger.info(
                "[tag_tracker] tag=%s done fetched=%s new=%s updated=%s old=%s refreshed=%s",
                tag,
                len(search_items),
                new_added,
                updated,
                skipped_old,
                refreshed_cached,
            )

    # Save tracker
    store["updated_at"] = now_str
    run_record = {
        "crawled_at": now_str,
        "mode": "api",
        "tags": list(run_summary.get("tags", {}).keys()),
        "auto_added_tags": run_summary.get("auto_added_tags", []),
        "notes_discovered": run_summary["notes_discovered"],
        "notes_updated": run_summary["notes_updated"],
    }
    runs = store.setdefault("runs", [])
    if isinstance(runs, list):
        runs.append(run_record)
        if len(runs) > 3650:
            del runs[: len(runs) - 3650]

    config.out_path.parent.mkdir(parents=True, exist_ok=True)
    config.out_path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "[tag_tracker] saved tracker to %s total_notes=%s tags=%s auto_added=%s",
        config.out_path,
        len(notes_map),
        ",".join(run_summary.get("tags", {}).keys()),
        len(run_summary.get("auto_added_tags", [])),
    )

    run_summary["finished_at"] = now_iso()
    return run_summary


def run_tracking_once(cfg: TagTrackConfig) -> dict[str, Any]:
    """Synchronous wrapper for a single tracking pass."""
    return asyncio.run(_run_tracking_async(cfg))


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


def _should_retry_with_forced_qrcode(error_type: ErrorType | None) -> bool:
    return error_type == ErrorType.AUTH_INVALID


def _run_once_with_forced_qrcode(config: TagTrackConfig) -> dict[str, Any]:
    import dataclasses

    retry_cfg = dataclasses.replace(config, force_qrcode=True)
    logger.warning("[tag_tracker] retrying with forced QR login...")
    return run_tracking_once(retry_cfg)


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
        except AccountStateAbort as exc:
            logger.error("[tag_tracker] run aborted: %s", exc.reason)
            if _should_retry_with_forced_qrcode(exc.error_type):
                try:
                    summary = _run_once_with_forced_qrcode(cfg)
                    logger.info(
                        "[tag_tracker] re-auth run completed: %s",
                        json.dumps(summary, ensure_ascii=False),
                    )
                    _heartbeat_sleep(interval_sec, heartbeat_sec)
                    continue
                except Exception as retry_exc:
                    logger.exception("[tag_tracker] re-auth failed: %s", retry_exc)

            # Progressive backoff: 2m, 5m, 10m
            backoff_minutes = [2, 5, 10]
            for attempt, wait_min in enumerate(backoff_minutes, 1):
                wait_sec = wait_min * 60
                logger.warning(
                    "[tag_tracker] backoff attempt %s/%s, waiting %sm",
                    attempt,
                    len(backoff_minutes),
                    wait_min,
                )
                _heartbeat_sleep(float(wait_sec), heartbeat_sec)
                try:
                    summary = run_tracking_once(cfg)
                    logger.info(
                        "[tag_tracker] retry success: %s", json.dumps(summary, ensure_ascii=False)
                    )
                    break
                except AccountStateAbort:
                    logger.error("[tag_tracker] retry %s failed", attempt)
                except Exception:
                    logger.exception("[tag_tracker] retry %s failed", attempt)
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
    except AccountStateAbort as exc:
        logger.error("[tag_tracker] startup aborted: %s", exc.reason)
        if _should_retry_with_forced_qrcode(exc.error_type):
            try:
                _run_once_with_forced_qrcode(cfg)
            except Exception:
                logger.exception("[tag_tracker] startup re-auth failed")
                return
        else:
            return
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
        except AccountStateAbort as exc:
            logger.error("[tag_tracker] daily run aborted: %s", exc.reason)
            if _should_retry_with_forced_qrcode(exc.error_type):
                try:
                    _run_once_with_forced_qrcode(cfg)
                except Exception:
                    logger.exception("[tag_tracker] re-auth failed")
        except KeyboardInterrupt:
            raise
        except Exception:
            logger.exception("[tag_tracker] daily run failed")
