"""Filter images with extreme aspect ratios."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from .base import FilterVerdict, ImageFilter


class AspectRatioFilter(ImageFilter):
    name = "aspect_ratio"

    def __init__(self, max_ratio: float = 3.0) -> None:
        self.max_ratio = max_ratio

    def evaluate(self, image_path: Path, metadata: dict[str, Any]) -> FilterVerdict:
        try:
            with Image.open(image_path) as img:
                w, h = img.size
        except Exception as exc:
            return FilterVerdict(
                passed=False,
                score=0.0,
                reason=f"cannot open image: {exc}",
                filter_name=self.name,
                details={"error": str(exc)},
            )

        if min(w, h) == 0:
            return FilterVerdict(
                passed=False,
                score=0.0,
                reason="zero dimension",
                filter_name=self.name,
                details={"width": w, "height": h},
            )

        ratio = max(w, h) / min(w, h)
        passed = ratio <= self.max_ratio
        score = min(self.max_ratio / ratio, 1.0) if ratio > 0 else 0.0
        reason = "" if passed else f"ratio={ratio:.2f} exceeds {self.max_ratio}"

        return FilterVerdict(
            passed=passed,
            score=score,
            reason=reason,
            filter_name=self.name,
            details={"width": w, "height": h, "ratio": round(ratio, 2)},
        )
