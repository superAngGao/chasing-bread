from __future__ import annotations

import pytest
from pathlib import Path


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """Provide a temporary data directory with raw/processed/logs subdirs."""
    for sub in ("raw", "processed", "logs"):
        (tmp_path / sub).mkdir()
    return tmp_path


@pytest.fixture
def sample_xhs_note() -> dict:
    """A minimal XHS note as returned by the search API."""
    return {
        "note_id": "abc123",
        "note_card": {
            "title": "巧克力蛋糕教程",
            "desc": "超简单的巧克力蛋糕做法",
            "user": {"user_id": "u001", "nickname": "小红薯"},
            "image_list": [
                {"url": "https://example.com/img1.jpg"},
                {"url": "https://example.com/img2.jpg"},
            ],
            "tag_list": [{"name": "蛋糕"}, {"name": "烘焙"}],
            "liked_count": "128",
            "collected_count": "56",
        },
    }
