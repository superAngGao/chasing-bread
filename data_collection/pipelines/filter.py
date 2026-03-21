"""Filter pipeline orchestrator — runs filters on image batches."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .filters.base import FilterVerdict, ImageFilter, ImageRecord

logger = logging.getLogger(__name__)


@dataclass
class FilterReport:
    """Aggregated statistics from a batch run."""

    total_images: int = 0
    passed: int = 0
    rejected: int = 0
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    records: list[ImageRecord] = field(default_factory=list)


class FilterPipeline:
    def __init__(self, filters: list[ImageFilter], *, fail_fast: bool = False) -> None:
        self.filters = filters
        self.fail_fast = fail_fast

    def run(self, image_path: Path, metadata: dict[str, Any]) -> ImageRecord:
        """Run all filters on a single image, return a fully populated ImageRecord."""
        record = ImageRecord(
            image_path=image_path,
            source_note_id=metadata.get("id", ""),
            source_title=metadata.get("title", ""),
            source_desc=metadata.get("description", ""),
        )

        # Populate image metadata (safe — if file is broken, filters will catch it)
        try:
            record.populate_image_metadata()
        except Exception:
            pass

        for filt in self.filters:
            verdict = filt.evaluate(image_path, metadata)
            record.verdicts[filt.name] = verdict

            # Propagate reusable assets from verdict details
            _propagate_assets(record, verdict)

            if self.fail_fast and not verdict.passed:
                break

        record.compute_overall()
        return record

    def run_batch(
        self,
        items: list[dict[str, Any]],
        image_dir: Path,
    ) -> FilterReport:
        """Process a batch of normalized items with their downloaded images.

        Each item is expected to have an ``id`` field. Images are discovered
        by globbing ``image_dir`` for files matching ``{id}_*``.
        """
        report = FilterReport()

        for item in items:
            note_id = item.get("id", "")
            if not note_id:
                continue
            image_paths = sorted(image_dir.glob(f"{note_id}_*"))
            if not image_paths:
                continue

            for img_path in image_paths:
                report.total_images += 1
                record = self.run(img_path, item)
                report.records.append(record)

                if record.overall_passed:
                    report.passed += 1
                else:
                    report.rejected += 1
                    for name, v in record.verdicts.items():
                        if not v.passed:
                            report.rejection_reasons[name] = (
                                report.rejection_reasons.get(name, 0) + 1
                            )

        logger.info(
            "[filter] batch done: %d total, %d passed, %d rejected",
            report.total_images,
            report.passed,
            report.rejected,
        )
        return report


def _propagate_assets(record: ImageRecord, verdict: FilterVerdict) -> None:
    """Copy reusable data from verdict details into the ImageRecord."""
    details = verdict.details

    if "phash" in details:
        record.phash = details["phash"]
    if "duplicate_of" in details:
        record.duplicate_of = details["duplicate_of"]
    if "category_scores" in details:
        record.clip_category_scores = details["category_scores"]
    if "clip_embedding_path" in details:
        record.clip_embedding_path = details["clip_embedding_path"]


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _verdict_to_dict(v: FilterVerdict) -> dict[str, Any]:
    return {
        "passed": v.passed,
        "score": v.score,
        "reason": v.reason,
        "filter_name": v.filter_name,
        "details": v.details,
    }


def record_to_dict(record: ImageRecord) -> dict[str, Any]:
    return {
        "image_path": str(record.image_path),
        "source_note_id": record.source_note_id,
        "source_title": record.source_title,
        "source_desc": record.source_desc,
        "width": record.width,
        "height": record.height,
        "file_size": record.file_size,
        "format": record.format,
        "verdicts": {k: _verdict_to_dict(v) for k, v in record.verdicts.items()},
        "overall_passed": record.overall_passed,
        "phash": record.phash,
        "clip_embedding_path": record.clip_embedding_path,
        "clip_category_scores": record.clip_category_scores,
        "duplicate_of": record.duplicate_of,
        "manual_override": record.manual_override,
    }


def save_report(report: FilterReport, output_path: Path) -> Path:
    """Save full filter report as JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "total_images": report.total_images,
        "passed": report.passed,
        "rejected": report.rejected,
        "rejection_reasons": report.rejection_reasons,
        "records": [record_to_dict(r) for r in report.records],
    }
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("[filter] report saved to %s", output_path)
    return output_path
