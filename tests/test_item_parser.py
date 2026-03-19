from __future__ import annotations

from data_collection.xhs.item_parser import extract_item_id


class TestExtractItemId:
    def test_id_field(self):
        assert extract_item_id({"id": "note_001"}) == "note_001"

    def test_note_id_field(self):
        assert extract_item_id({"note_id": "note_002"}) == "note_002"

    def test_noteId_field(self):
        assert extract_item_id({"noteId": "note_003"}) == "note_003"

    def test_priority_order(self):
        """'id' should be checked before 'note_id'."""
        assert extract_item_id({"id": "first", "note_id": "second"}) == "first"

    def test_nested_noteCard(self):
        item = {"noteCard": {"id": "nested_001"}}
        assert extract_item_id(item) == "nested_001"

    def test_nested_note_card(self):
        item = {"note_card": {"note_id": "nested_002"}}
        assert extract_item_id(item) == "nested_002"

    def test_empty_dict(self):
        assert extract_item_id({}) == ""

    def test_non_dict_input(self):
        assert extract_item_id("not_a_dict") == ""
        assert extract_item_id(None) == ""
        assert extract_item_id(42) == ""

    def test_empty_string_id_skipped(self):
        """Empty string values should be skipped."""
        assert extract_item_id({"id": "", "note_id": "fallback"}) == "fallback"

    def test_non_string_id_skipped(self):
        """Non-string id values should be skipped."""
        assert extract_item_id({"id": 123, "note_id": "valid"}) == "valid"
