"""Filter images by minimum resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from .base import FilterVerdict, ImageFilter


class ResolutionFilter(ImageFilter):
    name = "resolution"

    def __init__(self, min_width: int = 512, min_height: int = 512) -> None:
        self.min_width = min_width
        self.min_height = min_height

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

        passed = w >= self.min_width and h >= self.min_height
        score = min(w / self.min_width, h / self.min_height, 1.0)
        reason = "" if passed else f"{w}x{h} below {self.min_width}x{self.min_height}"

        return FilterVerdict(
            passed=passed,
            score=score,
            reason=reason,
            filter_name=self.name,
            details={"width": w, "height": h},
        )
