from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

TRACKER_SCHEMA_VERSION = 1


@dataclass(slots=True)
class TagTrackConfig:
    tags: list[str]
    out_path: Path
    pages_per_tag: int = 3
    page_size: int = 20
    max_comments_per_note: int = 100
    top_commenters_per_note: int = 10
    max_history_per_note: int = 180
    skip_detail_older_than_days: int = 30

    # Rate limiting
    max_rps: float = 0.4
    comment_max_rps: float = 0.2
    request_jitter_sec: float = 0.25
    comment_failure_streak_threshold: int = 5
    comment_failure_cooldown_sec: float = 120.0

    # Session
    login_timeout_sec: int = 180
    post_login_wait_sec: float = 2.0
    session_profile_dir: Path | None = None
    force_qrcode: bool = False
    nologin: bool = False
    debug: bool = False
