"""Generate an HTML visual report from filter results."""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

from .filter import FilterReport, record_to_dict
from .filters.base import ImageRecord

logger = logging.getLogger(__name__)

_THUMB_MAX = 200  # thumbnail max dimension in px


def _image_to_data_uri(path: Path, max_dim: int = _THUMB_MAX) -> str:
    """Return a base64 data URI for an image, resized for thumbnails."""
    try:
        from PIL import Image

        with Image.open(path) as img:
            img.thumbnail((max_dim, max_dim))
            import io

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=75)
            b64 = base64.b64encode(buf.getvalue()).decode()
            return f"data:image/jpeg;base64,{b64}"
    except Exception:
        return ""


def _record_html(record: ImageRecord) -> str:
    data_uri = _image_to_data_uri(record.image_path)
    status = "PASS" if record.overall_passed else "FAIL"
    color = "#2d7a2d" if record.overall_passed else "#c0392b"

    reasons = []
    for name, v in record.verdicts.items():
        if not v.passed:
            reasons.append(f"{name}: {v.reason}")
    reason_text = "<br>".join(reasons) if reasons else ""

    scores_text = ""
    if record.clip_category_scores:
        parts = [f"{k}={v:.3f}" for k, v in record.clip_category_scores.items()]
        scores_text = f'<div class="scores">{" | ".join(parts)}</div>'

    return f"""
    <div class="card">
      <img src="{data_uri}" alt="{record.image_path.name}">
      <div class="info">
        <span class="status" style="color:{color}">{status}</span>
        <div class="title">{record.source_title[:60]}</div>
        <div class="meta">{record.width}x{record.height} | {record.file_size // 1024}KB</div>
        {scores_text}
        <div class="reason">{reason_text}</div>
      </div>
    </div>"""


def generate_html_report(report: FilterReport, output_path: Path) -> Path:
    """Write a self-contained HTML report with embedded thumbnails."""
    passed_records = [r for r in report.records if r.overall_passed]
    failed_records = [r for r in report.records if not r.overall_passed]

    cards_passed = "\n".join(_record_html(r) for r in passed_records)
    cards_failed = "\n".join(_record_html(r) for r in failed_records)

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>Filter Report</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 20px; background: #f5f5f5; }}
  h1 {{ color: #333; }}
  .summary {{ background: #fff; padding: 16px; border-radius: 8px; margin-bottom: 20px; }}
  .summary span {{ margin-right: 24px; }}
  .grid {{ display: flex; flex-wrap: wrap; gap: 12px; }}
  .card {{ background: #fff; border-radius: 8px; padding: 8px; width: 220px; box-shadow: 0 1px 3px rgba(0,0,0,0.12); }}
  .card img {{ width: 100%; border-radius: 4px; }}
  .info {{ font-size: 12px; margin-top: 6px; }}
  .status {{ font-weight: bold; }}
  .title {{ color: #555; margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .meta {{ color: #999; }}
  .scores {{ color: #2980b9; margin-top: 2px; }}
  .reason {{ color: #c0392b; margin-top: 4px; }}
  h2 {{ margin-top: 32px; }}
</style>
</head>
<body>
<h1>Chasing Bread - Filter Report</h1>
<div class="summary">
  <span>Total: {report.total_images}</span>
  <span style="color:#2d7a2d">Passed: {report.passed}</span>
  <span style="color:#c0392b">Rejected: {report.rejected}</span>
</div>
<div class="summary">
  Rejection breakdown: {_rejection_summary(report)}
</div>

<h2>Passed ({len(passed_records)})</h2>
<div class="grid">{cards_passed}</div>

<h2>Rejected ({len(failed_records)})</h2>
<div class="grid">{cards_failed}</div>
</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    logger.info("[report] HTML report saved to %s", output_path)
    return output_path


def _rejection_summary(report: FilterReport) -> str:
    if not report.rejection_reasons:
        return "none"
    parts = [f"{k}: {v}" for k, v in sorted(report.rejection_reasons.items(), key=lambda x: -x[1])]
    return " | ".join(parts)
