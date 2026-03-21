"""Image-level deduplication using perceptual hashing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import imagehash
from PIL import Image

from .base import FilterVerdict, ImageFilter


class DuplicateFilter(ImageFilter):
    """Detects near-duplicate images via pHash.

    Stateful: must process all images in a batch so it can track seen hashes.
    Call ``reset()`` between independent batches.
    """

    name = "duplicate"

    def __init__(self, max_hamming_distance: int = 6) -> None:
        self.max_hamming_distance = max_hamming_distance
        # phash_hex -> image_path of the first (primary) occurrence
        self._seen: dict[str, str] = {}

    def reset(self) -> None:
        self._seen.clear()

    def evaluate(self, image_path: Path, metadata: dict[str, Any]) -> FilterVerdict:
        try:
            with Image.open(image_path) as img:
                phash = imagehash.phash(img)
        except Exception as exc:
            return FilterVerdict(
                passed=False,
                score=0.0,
                reason=f"cannot open image: {exc}",
                filter_name=self.name,
                details={"error": str(exc)},
            )

        phash_hex = str(phash)

        # Check against all seen hashes
        for seen_hex, seen_path in self._seen.items():
            seen_hash = imagehash.hex_to_hash(seen_hex)
            distance = phash - seen_hash
            if distance <= self.max_hamming_distance:
                return FilterVerdict(
                    passed=False,
                    score=0.0,
                    reason=f"duplicate of {seen_path} (distance={distance})",
                    filter_name=self.name,
                    details={
                        "phash": phash_hex,
                        "duplicate_of": seen_path,
                        "hamming_distance": distance,
                    },
                )

        # First occurrence — register as primary
        self._seen[phash_hex] = str(image_path)
        return FilterVerdict(
            passed=True,
            score=1.0,
            reason="",
            filter_name=self.name,
            details={"phash": phash_hex},
        )
