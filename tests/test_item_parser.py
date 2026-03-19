"""Tests for item/note parsing utilities and deduplication correctness."""

from __future__ import annotations

from data_collection.xhs.item_parser import extract_item_id
from data_collection.xhs.tag_tracker.helpers import (
    extract_metrics,
    extract_note_id,
    extract_xsec_token,
    is_note_item,
)


class TestExtractItemId:
    def test_top_level_id(self):
        assert extract_item_id({"id": "abc123"}) == "abc123"

    def test_note_card_id(self):
        item = {"note_card": {"id": "abc123"}}
        assert extract_item_id(item) == "abc123"

    def test_prefers_top_level(self):
        item = {"id": "top", "note_card": {"id": "nested"}}
        assert extract_item_id(item) == "top"

    def test_note_id_variant(self):
        assert extract_item_id({"note_id": "abc"}) == "abc"

    def test_noteId_camel_case(self):
        assert extract_item_id({"noteId": "abc"}) == "abc"

    def test_empty_item(self):
        assert extract_item_id({}) == ""

    def test_non_dict(self):
        assert extract_item_id("not a dict") == ""
        assert extract_item_id(None) == ""


class TestExtractNoteIdDelegation:
    """Verify tag_tracker.helpers.extract_note_id delegates to item_parser.extract_item_id."""

    def test_same_result_top_level(self):
        item = {"id": "abc123"}
        assert extract_note_id(item) == extract_item_id(item)

    def test_same_result_nested(self):
        item = {"note_card": {"id": "abc123"}}
        assert extract_note_id(item) == extract_item_id(item)

    def test_same_result_empty(self):
        assert extract_note_id({}) == extract_item_id({})


class TestExtractXsecToken:
    def test_top_level(self):
        assert extract_xsec_token({"xsec_token": "tok123"}) == "tok123"

    def test_nested(self):
        item = {"note_card": {"xsec_token": "tok123"}}
        assert extract_xsec_token(item) == "tok123"

    def test_missing(self):
        assert extract_xsec_token({}) == ""


class TestIsNoteItem:
    def test_model_type_note(self):
        assert is_note_item({"model_type": "note"})

    def test_model_type_other(self):
        assert not is_note_item({"model_type": "ad"})

    def test_has_note_card(self):
        assert is_note_item({"note_card": {"id": "abc"}})

    def test_empty(self):
        assert not is_note_item({})


class TestExtractMetrics:
    def test_basic(self):
        item = {
            "note_card": {
                "interact_info": {
                    "liked_count": "1234",
                    "comment_count": 56,
                    "collected_count": "789",
                    "shared_count": 0,
                }
            }
        }
        metrics = extract_metrics(item)
        assert metrics["like_count"] == 1234
        assert metrics["comment_count"] == 56
        assert metrics["collected_count"] == 789
        assert metrics["shared_count"] == 0

    def test_missing_interact_info(self):
        metrics = extract_metrics({"note_card": {}})
        assert all(v == 0 for v in metrics.values())
