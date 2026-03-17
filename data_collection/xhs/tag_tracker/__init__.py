"""Tag tracking package for XHS — API-based (pure HTTP, no browser UI automation)."""

from data_collection.xhs.tag_tracker.config import TagTrackConfig
from data_collection.xhs.tag_tracker.tracker import (
    run_daily_scheduler,
    run_interval_scheduler,
    run_tracking_once,
)

__all__ = [
    "TagTrackConfig",
    "run_tracking_once",
    "run_daily_scheduler",
    "run_interval_scheduler",
]
