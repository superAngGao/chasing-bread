"""Export filtered data to training-ready formats."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .filter import FilterReport
from .filters.base import ImageRecord

logger = logging.getLogger(__name__)


def export_metadata_jsonl(
    report: FilterReport,
    output_path: Path,
    *,
    passed_only: bool = True,
) -> Path:
    """Export to metadata.jsonl — one JSON object per line.

    Format: {"file_name": "xxx.jpg", "source_title": "...", "source_desc": "...",
             "category": "cake", "category_score": 0.82}

    This is a minimal training-oriented format. Formal captions will be
    generated in Phase 2B; for now, source text is included as reference.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0

    with open(output_path, "w", encoding="utf-8") as f:
        for record in report.records:
            if passed_only and not record.overall_passed:
                continue

            # Determine best category from CLIP scores
            category = ""
            category_score = 0.0
            if record.clip_category_scores:
                category = max(record.clip_category_scores, key=record.clip_category_scores.get)
                category_score = record.clip_category_scores[category]

            entry = {
                "file_name": record.image_path.name,
                "image_path": str(record.image_path),
                "source_note_id": record.source_note_id,
                "source_title": record.source_title,
                "source_desc": record.source_desc,
                "category": category,
                "category_score": round(category_score, 4),
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            count += 1

    logger.info("[export] wrote %d entries to %s", count, output_path)
    return output_path
