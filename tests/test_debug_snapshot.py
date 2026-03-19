"""Tests for the debug snapshot utility."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from data_collection.utils.debug_snapshot import (
    build_state_metadata,
    save_snapshot,
    save_snapshot_sync,
)


class TestBuildStateMetadata:
    def test_basic(self):
        state = build_state_metadata(
            trigger="test_trigger",
            endpoint="search",
            phase="before_search",
        )
        assert state["trigger"] == "test_trigger"
        assert state["endpoint"] == "search"
        assert state["phase"] == "before_search"
        assert "timestamp" in state
        assert "call_chain" in state
        assert isinstance(state["call_chain"], list)

    def test_with_exception(self):
        try:
            raise ValueError("test error")
        except ValueError as exc:
            state = build_state_metadata(trigger="test", error=exc)

        assert state["error"]["type"] == "ValueError"
        assert state["error"]["message"] == "test error"
        assert "traceback" in state

    def test_with_xhs_api_error(self):
        from data_collection.xhs.mc_api._errors import XhsApiError

        exc = XhsApiError(
            endpoint="comment",
            code=461,
            msg="CAPTCHA",
            payload={"verify": True},
        )
        state = build_state_metadata(trigger="captcha", error=exc)
        assert state["error"]["code"] == 461
        assert state["error"]["payload"] == {"verify": True}

    def test_cookies_redacted(self):
        cookies = [
            {"name": "a1", "value": "secret123", "domain": ".xiaohongshu.com", "expires": 999},
            {"name": "id_token", "value": "topsecret", "domain": ".xiaohongshu.com"},
        ]
        state = build_state_metadata(trigger="test", cookies=cookies)
        for c in state["cookies"]:
            assert "value" not in c
            assert c["has_value"] is True
            assert "name" in c

    def test_with_extra(self):
        state = build_state_metadata(
            trigger="test",
            extra={"note_id": "abc123", "page": 3},
        )
        assert state["extra"]["note_id"] == "abc123"


class TestSaveSnapshotSync:
    def test_saves_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "data_collection.utils.debug_snapshot._DEBUG_DIR",
            tmp_path,
        )
        result = save_snapshot_sync(
            trigger="test_sync",
            error="something went wrong",
            endpoint="search",
        )
        assert result is not None
        json_files = list(tmp_path.glob("*.json"))
        assert len(json_files) == 1
        data = json.loads(json_files[0].read_text(encoding="utf-8"))
        assert data["trigger"] == "test_sync"
        assert data["error"]["message"] == "something went wrong"


class TestSaveSnapshot:
    @pytest.mark.asyncio
    async def test_saves_all_artifacts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "data_collection.utils.debug_snapshot._DEBUG_DIR",
            tmp_path,
        )
        page = AsyncMock()
        page.url = "https://www.xiaohongshu.com/explore"
        page.screenshot = AsyncMock()
        page.content = AsyncMock(return_value="<html><body>test</body></html>")
        page.context.cookies = AsyncMock(
            return_value=[
                {"name": "a1", "value": "x", "domain": ".xiaohongshu.com"},
            ]
        )

        result = await save_snapshot(
            page=page,
            trigger="test_async",
            error=ValueError("boom"),
            endpoint="detail",
            phase="scroll_loop",
        )
        assert result is not None

        # Check screenshot was attempted
        page.screenshot.assert_awaited_once()

        # Check HTML saved
        html_files = list(tmp_path.glob("*.html"))
        assert len(html_files) == 1
        assert "<html>" in html_files[0].read_text(encoding="utf-8")

        # Check JSON saved
        json_files = list(tmp_path.glob("*.json"))
        assert len(json_files) == 1
        data = json.loads(json_files[0].read_text(encoding="utf-8"))
        assert data["trigger"] == "test_async"
        assert data["page_url"] == "https://www.xiaohongshu.com/explore"
        assert data["error"]["type"] == "ValueError"
        assert len(data["cookies"]) == 1

    @pytest.mark.asyncio
    async def test_handles_page_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "data_collection.utils.debug_snapshot._DEBUG_DIR",
            tmp_path,
        )
        result = await save_snapshot(
            page=None,
            trigger="no_page",
            error="test",
        )
        assert result is not None
        # Only JSON should exist (no screenshot or HTML)
        json_files = list(tmp_path.glob("*.json"))
        assert len(json_files) == 1
        assert len(list(tmp_path.glob("*.png"))) == 0
        assert len(list(tmp_path.glob("*.html"))) == 0
