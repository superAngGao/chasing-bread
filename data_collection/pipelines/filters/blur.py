"""Filter blurry images using Laplacian variance."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .base import FilterVerdict, ImageFilter


def _laplacian_variance(gray: np.ndarray) -> float:
    """Compute variance of the Laplacian (no OpenCV dependency)."""
    kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float64)
    from scipy.signal import convolve2d

    lap = convolve2d(gray.astype(np.float64), kernel, mode="same", boundary="symm")
    return float(np.var(lap))


class BlurFilter(ImageFilter):
    name = "blur"

    def __init__(self, min_laplacian_var: float = 100.0) -> None:
        self.min_laplacian_var = min_laplacian_var

    def evaluate(self, image_path: Path, metadata: dict[str, Any]) -> FilterVerdict:
        try:
            with Image.open(image_path) as img:
                gray = np.array(img.convert("L"))
        except Exception as exc:
            return FilterVerdict(
                passed=False,
                score=0.0,
                reason=f"cannot open image: {exc}",
                filter_name=self.name,
                details={"error": str(exc)},
            )

        var = _laplacian_variance(gray)
        passed = var >= self.min_laplacian_var
        score = min(var / self.min_laplacian_var, 1.0) if self.min_laplacian_var > 0 else 1.0
        reason = "" if passed else f"laplacian_var={var:.1f} below {self.min_laplacian_var}"

        return FilterVerdict(
            passed=passed,
            score=score,
            reason=reason,
            filter_name=self.name,
            details={"laplacian_var": round(var, 2)},
        )
