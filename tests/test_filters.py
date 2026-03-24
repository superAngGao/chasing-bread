"""Tests for Phase 2A image filtering pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from data_collection.pipelines.filters.base import FilterVerdict, ImageRecord
from data_collection.pipelines.filters.resolution import ResolutionFilter
from data_collection.pipelines.filters.blur import BlurFilter
from data_collection.pipelines.filters.aspect_ratio import AspectRatioFilter
from data_collection.pipelines.filters.negative_keyword import NegativeKeywordFilter
from data_collection.pipelines.filter import FilterPipeline, FilterReport, save_report
from data_collection.pipelines.export import export_metadata_jsonl


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def make_image(tmp_path: Path):
    """Factory fixture: create a test image with given size and content."""

    def _make(
        name: str = "test.jpg",
        width: int = 1024,
        height: int = 1024,
        mode: str = "RGB",
        noise: bool = True,
    ) -> Path:
        path = tmp_path / name
        if noise:
            arr = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
            img = Image.fromarray(arr, mode)
        else:
            # Uniform color — will be very blurry (low laplacian variance)
            img = Image.new(mode, (width, height), color=(128, 128, 128))
        img.save(path, format="JPEG")
        return path

    return _make


@pytest.fixture
def sample_metadata() -> dict:
    return {
        "id": "note001",
        "title": "抹茶蛋糕教程",
        "description": "简单好做的抹茶蛋糕",
    }


# ---------------------------------------------------------------------------
# ResolutionFilter
# ---------------------------------------------------------------------------


class TestResolutionFilter:
    def test_pass_large_image(self, make_image, sample_metadata):
        img = make_image(width=1024, height=768)
        f = ResolutionFilter(min_width=512, min_height=512)
        v = f.evaluate(img, sample_metadata)
        assert v.passed is True
        assert v.score == 1.0
        assert v.reason == ""

    def test_fail_small_image(self, make_image, sample_metadata):
        img = make_image(width=256, height=256)
        f = ResolutionFilter(min_width=512, min_height=512)
        v = f.evaluate(img, sample_metadata)
        assert v.passed is False
        assert v.score == pytest.approx(0.5)
        assert "256x256" in v.reason

    def test_fail_one_dimension_too_small(self, make_image, sample_metadata):
        img = make_image(width=1024, height=400)
        f = ResolutionFilter(min_width=512, min_height=512)
        v = f.evaluate(img, sample_metadata)
        assert v.passed is False
        assert "400" in v.reason

    def test_exact_minimum(self, make_image, sample_metadata):
        img = make_image(width=512, height=512)
        f = ResolutionFilter(min_width=512, min_height=512)
        v = f.evaluate(img, sample_metadata)
        assert v.passed is True

    def test_invalid_file(self, tmp_path, sample_metadata):
        bad = tmp_path / "bad.jpg"
        bad.write_text("not an image")
        f = ResolutionFilter()
        v = f.evaluate(bad, sample_metadata)
        assert v.passed is False
        assert "cannot open image" in v.reason

    def test_custom_thresholds(self, make_image, sample_metadata):
        img = make_image(width=200, height=200)
        f = ResolutionFilter(min_width=100, min_height=100)
        v = f.evaluate(img, sample_metadata)
        assert v.passed is True


# ---------------------------------------------------------------------------
# BlurFilter
# ---------------------------------------------------------------------------


class TestBlurFilter:
    def test_pass_sharp_image(self, make_image, sample_metadata):
        # Random noise has high frequency content — high laplacian variance
        img = make_image(width=256, height=256, noise=True)
        f = BlurFilter(min_laplacian_var=100.0)
        v = f.evaluate(img, sample_metadata)
        assert v.passed is True
        assert v.details["laplacian_var"] > 100.0

    def test_fail_blurry_image(self, make_image, sample_metadata):
        # Uniform image — zero variance
        img = make_image(width=256, height=256, noise=False)
        f = BlurFilter(min_laplacian_var=100.0)
        v = f.evaluate(img, sample_metadata)
        assert v.passed is False
        assert "laplacian_var" in v.reason

    def test_score_capped_at_one(self, make_image, sample_metadata):
        img = make_image(width=256, height=256, noise=True)
        f = BlurFilter(min_laplacian_var=1.0)
        v = f.evaluate(img, sample_metadata)
        assert v.score == 1.0

    def test_invalid_file(self, tmp_path, sample_metadata):
        bad = tmp_path / "bad.jpg"
        bad.write_text("not an image")
        f = BlurFilter()
        v = f.evaluate(bad, sample_metadata)
        assert v.passed is False


# ---------------------------------------------------------------------------
# AspectRatioFilter
# ---------------------------------------------------------------------------


class TestAspectRatioFilter:
    def test_pass_square(self, make_image, sample_metadata):
        img = make_image(width=512, height=512)
        f = AspectRatioFilter(max_ratio=3.0)
        v = f.evaluate(img, sample_metadata)
        assert v.passed is True
        assert v.details["ratio"] == 1.0

    def test_pass_moderate_ratio(self, make_image, sample_metadata):
        img = make_image(width=1024, height=512)
        f = AspectRatioFilter(max_ratio=3.0)
        v = f.evaluate(img, sample_metadata)
        assert v.passed is True
        assert v.details["ratio"] == 2.0

    def test_fail_extreme_ratio(self, make_image, sample_metadata):
        img = make_image(width=1600, height=400)
        f = AspectRatioFilter(max_ratio=3.0)
        v = f.evaluate(img, sample_metadata)
        assert v.passed is False
        assert v.details["ratio"] == 4.0

    def test_portrait_same_as_landscape(self, make_image, sample_metadata):
        img = make_image(width=400, height=1600)
        f = AspectRatioFilter(max_ratio=3.0)
        v = f.evaluate(img, sample_metadata)
        assert v.passed is False
        assert v.details["ratio"] == 4.0

    def test_invalid_file(self, tmp_path, sample_metadata):
        bad = tmp_path / "bad.jpg"
        bad.write_text("not an image")
        f = AspectRatioFilter()
        v = f.evaluate(bad, sample_metadata)
        assert v.passed is False


# ---------------------------------------------------------------------------
# NegativeKeywordFilter
# ---------------------------------------------------------------------------


class TestNegativeKeywordFilter:
    def test_pass_clean_text(self):
        f = NegativeKeywordFilter()
        v = f.evaluate(Path("dummy.jpg"), {"title": "抹茶蛋糕", "description": "好吃的蛋糕"})
        assert v.passed is True

    def test_fail_title_match(self):
        f = NegativeKeywordFilter()
        v = f.evaluate(Path("dummy.jpg"), {"title": "装修风格的蛋糕", "description": ""})
        assert v.passed is False
        assert "装修" in v.reason

    def test_fail_desc_match(self):
        f = NegativeKeywordFilter()
        v = f.evaluate(Path("dummy.jpg"), {"title": "", "description": "加盟热线"})
        assert v.passed is False
        assert "加盟" in v.reason

    def test_multiple_matches(self):
        f = NegativeKeywordFilter()
        v = f.evaluate(Path("dummy.jpg"), {"title": "穿搭妆容", "description": ""})
        assert v.passed is False
        assert len(v.details["matched_keywords"]) == 2

    def test_custom_keywords(self):
        f = NegativeKeywordFilter(keywords={"广告", "推广"})
        v = f.evaluate(Path("dummy.jpg"), {"title": "广告贴", "description": ""})
        assert v.passed is False
        assert "广告" in v.reason

    def test_missing_text_fields(self):
        f = NegativeKeywordFilter()
        v = f.evaluate(Path("dummy.jpg"), {})
        assert v.passed is True

    def test_none_text_fields(self):
        f = NegativeKeywordFilter()
        v = f.evaluate(Path("dummy.jpg"), {"title": None, "description": None})
        assert v.passed is True


# ---------------------------------------------------------------------------
# ImageRecord
# ---------------------------------------------------------------------------


class TestImageRecord:
    def test_populate_image_metadata(self, make_image):
        img = make_image(width=800, height=600)
        record = ImageRecord(
            image_path=img,
            source_note_id="n1",
            source_title="test",
            source_desc="",
        )
        record.populate_image_metadata()
        assert record.width == 800
        assert record.height == 600
        assert record.file_size > 0
        assert record.format == "JPEG"

    def test_compute_overall_all_pass(self):
        record = ImageRecord(
            image_path=Path("x.jpg"),
            source_note_id="n1",
            source_title="",
            source_desc="",
        )
        record.verdicts = {
            "a": FilterVerdict(passed=True, score=1.0, reason="", filter_name="a"),
            "b": FilterVerdict(passed=True, score=1.0, reason="", filter_name="b"),
        }
        record.compute_overall()
        assert record.overall_passed is True

    def test_compute_overall_one_fail(self):
        record = ImageRecord(
            image_path=Path("x.jpg"),
            source_note_id="n1",
            source_title="",
            source_desc="",
        )
        record.verdicts = {
            "a": FilterVerdict(passed=True, score=1.0, reason="", filter_name="a"),
            "b": FilterVerdict(passed=False, score=0.0, reason="bad", filter_name="b"),
        }
        record.compute_overall()
        assert record.overall_passed is False

    def test_manual_override_true(self):
        record = ImageRecord(
            image_path=Path("x.jpg"),
            source_note_id="n1",
            source_title="",
            source_desc="",
        )
        record.verdicts = {
            "a": FilterVerdict(passed=False, score=0.0, reason="fail", filter_name="a"),
        }
        record.manual_override = True
        record.compute_overall()
        assert record.overall_passed is True

    def test_manual_override_false(self):
        record = ImageRecord(
            image_path=Path("x.jpg"),
            source_note_id="n1",
            source_title="",
            source_desc="",
        )
        record.verdicts = {
            "a": FilterVerdict(passed=True, score=1.0, reason="", filter_name="a"),
        }
        record.manual_override = False
        record.compute_overall()
        assert record.overall_passed is False


# ---------------------------------------------------------------------------
# FilterPipeline
# ---------------------------------------------------------------------------


class TestFilterPipeline:
    def test_single_image_all_pass(self, make_image, sample_metadata):
        img = make_image(width=1024, height=1024, noise=True)
        pipeline = FilterPipeline(
            [
                ResolutionFilter(min_width=512, min_height=512),
                AspectRatioFilter(max_ratio=3.0),
                NegativeKeywordFilter(),
            ]
        )
        record = pipeline.run(img, sample_metadata)
        assert record.overall_passed is True
        assert len(record.verdicts) == 3

    def test_single_image_resolution_fail(self, make_image, sample_metadata):
        img = make_image(width=100, height=100, noise=True)
        pipeline = FilterPipeline(
            [
                ResolutionFilter(min_width=512, min_height=512),
                AspectRatioFilter(max_ratio=3.0),
            ]
        )
        record = pipeline.run(img, sample_metadata)
        assert record.overall_passed is False
        assert record.verdicts["resolution"].passed is False

    def test_fail_fast_skips_remaining(self, make_image, sample_metadata):
        img = make_image(width=100, height=100, noise=True)
        pipeline = FilterPipeline(
            [
                ResolutionFilter(min_width=512, min_height=512),
                AspectRatioFilter(max_ratio=3.0),
                BlurFilter(min_laplacian_var=100.0),
            ],
            fail_fast=True,
        )
        record = pipeline.run(img, sample_metadata)
        assert record.overall_passed is False
        # fail_fast should stop after resolution fails
        assert "resolution" in record.verdicts
        assert "blur" not in record.verdicts

    def test_run_batch(self, tmp_path, make_image):
        # Create images with note_id prefix naming convention
        make_image(name="note001_0.jpg", width=1024, height=1024, noise=True)
        make_image(name="note001_1.jpg", width=1024, height=1024, noise=True)
        make_image(name="note002_0.jpg", width=100, height=100, noise=True)

        items = [
            {"id": "note001", "title": "蛋糕", "description": ""},
            {"id": "note002", "title": "蛋糕", "description": ""},
        ]

        pipeline = FilterPipeline([ResolutionFilter(min_width=512, min_height=512)])
        report = pipeline.run_batch(items, tmp_path)

        assert report.total_images == 3
        assert report.passed == 2
        assert report.rejected == 1
        assert "resolution" in report.rejection_reasons

    def test_run_batch_skips_missing_id(self, tmp_path):
        items = [{"title": "no id"}]
        pipeline = FilterPipeline([ResolutionFilter()])
        report = pipeline.run_batch(items, tmp_path)
        assert report.total_images == 0

    def test_run_batch_skips_no_images(self, tmp_path):
        items = [{"id": "nonexistent"}]
        pipeline = FilterPipeline([ResolutionFilter()])
        report = pipeline.run_batch(items, tmp_path)
        assert report.total_images == 0


# ---------------------------------------------------------------------------
# save_report
# ---------------------------------------------------------------------------


class TestSaveReport:
    def test_save_and_load(self, tmp_path, make_image, sample_metadata):
        img = make_image(width=1024, height=1024, noise=True)
        pipeline = FilterPipeline([ResolutionFilter(min_width=512, min_height=512)])
        record = pipeline.run(img, sample_metadata)

        report = FilterReport(
            total_images=1,
            passed=1,
            rejected=0,
            records=[record],
        )
        out = tmp_path / "report.json"
        save_report(report, out)

        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["total_images"] == 1
        assert data["passed"] == 1
        assert len(data["records"]) == 1
        assert data["records"][0]["overall_passed"] is True


# ---------------------------------------------------------------------------
# export_metadata_jsonl
# ---------------------------------------------------------------------------


class TestExportMetadataJsonl:
    def _make_report(self, records: list[ImageRecord]) -> FilterReport:
        passed = sum(1 for r in records if r.overall_passed)
        return FilterReport(
            total_images=len(records),
            passed=passed,
            rejected=len(records) - passed,
            records=records,
        )

    def _make_record(self, name: str, passed: bool, scores: dict | None = None) -> ImageRecord:
        r = ImageRecord(
            image_path=Path(f"/img/{name}"),
            source_note_id=name.split(".")[0],
            source_title=f"title_{name}",
            source_desc=f"desc_{name}",
        )
        r.overall_passed = passed
        if scores:
            r.clip_category_scores = scores
        return r

    def test_export_passed_only(self, tmp_path):
        records = [
            self._make_record("a.jpg", True),
            self._make_record("b.jpg", False),
            self._make_record("c.jpg", True),
        ]
        report = self._make_report(records)
        out = tmp_path / "metadata.jsonl"
        export_metadata_jsonl(report, out, passed_only=True)

        lines = out.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        entry = json.loads(lines[0])
        assert entry["file_name"] == "a.jpg"

    def test_export_all(self, tmp_path):
        records = [
            self._make_record("a.jpg", True),
            self._make_record("b.jpg", False),
        ]
        report = self._make_report(records)
        out = tmp_path / "metadata.jsonl"
        export_metadata_jsonl(report, out, passed_only=False)

        lines = out.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_category_from_clip_scores(self, tmp_path):
        records = [
            self._make_record("a.jpg", True, scores={"cake": 0.9, "drink": 0.3}),
        ]
        report = self._make_report(records)
        out = tmp_path / "metadata.jsonl"
        export_metadata_jsonl(report, out)

        entry = json.loads(out.read_text(encoding="utf-8").strip())
        assert entry["category"] == "cake"
        assert entry["category_score"] == 0.9

    def test_no_clip_scores(self, tmp_path):
        records = [self._make_record("a.jpg", True)]
        report = self._make_report(records)
        out = tmp_path / "metadata.jsonl"
        export_metadata_jsonl(report, out)

        entry = json.loads(out.read_text(encoding="utf-8").strip())
        assert entry["category"] == ""
        assert entry["category_score"] == 0.0

    def test_empty_report(self, tmp_path):
        report = self._make_report([])
        out = tmp_path / "metadata.jsonl"
        export_metadata_jsonl(report, out)
        assert out.read_text(encoding="utf-8") == ""
