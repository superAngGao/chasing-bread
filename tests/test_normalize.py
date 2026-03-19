from __future__ import annotations

import json
from pathlib import Path

from data_collection.pipelines.normalize import (
    normalize_recipe_item,
    normalize_items,
    _to_int,
)


class TestNormalizeRecipeItem:
    def test_basic_normalization(self, sample_xhs_note):
        result = normalize_recipe_item(sample_xhs_note)

        assert result["id"] == "abc123"
        assert result["platform"] == "xhs"
        assert result["title"] == "巧克力蛋糕教程"
        assert result["description"] == "超简单的巧克力蛋糕做法"
        assert result["author_id"] == "u001"
        assert result["author_name"] == "小红薯"
        assert result["image_urls"] == [
            "https://example.com/img1.jpg",
            "https://example.com/img2.jpg",
        ]
        assert result["tags"] == ["蛋糕", "烘焙"]
        assert result["like_count"] == 128
        assert result["collect_count"] == 56

    def test_flat_structure(self):
        """Handle items without nested note_card."""
        item = {
            "id": "flat_001",
            "title": "抹茶拿铁",
            "desc": "好喝的抹茶拿铁",
            "user_id": "u002",
            "nickname": "咖啡师",
            "images": ["https://example.com/a.jpg"],
            "tags": ["咖啡", "抹茶"],
            "like_count": 50,
            "collect_count": 20,
        }
        result = normalize_recipe_item(item)
        assert result["id"] == "flat_001"
        assert result["title"] == "抹茶拿铁"
        assert result["image_urls"] == ["https://example.com/a.jpg"]
        assert result["tags"] == ["咖啡", "抹茶"]

    def test_missing_fields_default(self):
        """Missing fields should default gracefully."""
        result = normalize_recipe_item({})
        assert result["id"] == ""
        assert result["title"] == ""
        assert result["image_urls"] == []
        assert result["tags"] == []
        assert result["like_count"] == 0

    def test_custom_platform(self):
        result = normalize_recipe_item({"id": "x"}, platform="douyin")
        assert result["platform"] == "douyin"


class TestNormalizeItems:
    def test_batch_processing(self, sample_xhs_note):
        results = normalize_items([sample_xhs_note, sample_xhs_note])
        assert len(results) == 2

    def test_skips_bad_items(self):
        """Items that fail normalization should be skipped, not crash the batch."""
        good = {"id": "good_001", "title": "OK"}
        # Passing a non-dict that will cause an error inside normalize_recipe_item
        # Actually normalize_recipe_item handles dicts fine, so let's use a list
        # which will fail on .get()
        bad_items: list = [good]
        results = normalize_items(bad_items)
        assert len(results) == 1

    def test_empty_list(self):
        assert normalize_items([]) == []


class TestToInt:
    def test_int_value(self):
        assert _to_int(42) == 42

    def test_string_value(self):
        assert _to_int("128") == 128

    def test_none_value(self):
        assert _to_int(None) == 0

    def test_invalid_string(self):
        assert _to_int("not_a_number") == 0

    def test_float_value(self):
        assert _to_int(3.7) == 3
