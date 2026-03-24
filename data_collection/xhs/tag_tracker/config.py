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
    max_new_items_per_tag: int = 20

    # Rate limiting
    max_rps: float = 0.4
    comment_max_rps: float = 0.1  # 1 request per 10s — comment endpoint is heavily protected
    request_jitter_sec: float = 0.25
    comment_jitter_sec: float = 3.0  # Gaussian jitter mean for comments (adds 2-5s)
    comment_failure_streak_threshold: int = 3  # fewer failures before cooldown
    comment_failure_cooldown_sec: float = 300.0  # 5 min base cooldown

    # Auto-expand tags
    auto_expand_tags: bool = True
    auto_expand_hit_rate_threshold: float = 0.3
    max_auto_expand_tags: int = 10

    # Refresh cached notes
    refresh_cached: bool = True
    stable_max_rounds: int = 3
    stable_round_delay_sec: float = 1.0

    # Session
    login_timeout_sec: int = 180
    post_login_wait_sec: float = 2.0
    session_profile_dir: Path | None = None
    force_qrcode: bool = False
    nologin: bool = False
    debug: bool = False
