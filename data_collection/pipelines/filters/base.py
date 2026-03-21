"""Base types for the image filtering pipeline."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class FilterVerdict:
    """Result of a single filter's evaluation on one image."""

    passed: bool
    score: float  # 0.0 ~ 1.0, higher is better
    reason: str  # empty if passed
    filter_name: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageRecord:
    """Complete record for one image after the filtering pipeline."""

    # Identity
    image_path: Path
    source_note_id: str
    source_title: str
    source_desc: str

    # Image metadata
    width: int = 0
    height: int = 0
    file_size: int = 0
    format: str = ""

    # Filter results
    verdicts: dict[str, FilterVerdict] = field(default_factory=dict)
    overall_passed: bool = False

    # Reusable assets
    phash: str = ""
    clip_embedding_path: str = ""  # path to .npy file
    clip_category_scores: dict[str, float] = field(default_factory=dict)
    duplicate_of: str | None = None  # image_path of primary if this is a dup

    # Manual review
    manual_override: bool | None = None  # None=unreviewed

    def populate_image_metadata(self) -> None:
        """Read basic metadata from the image file."""
        from PIL import Image

        self.file_size = self.image_path.stat().st_size
        with Image.open(self.image_path) as img:
            self.width, self.height = img.size
            self.format = (img.format or "").upper()

    def compute_overall(self) -> None:
        """Set overall_passed based on all verdicts, respecting manual override."""
        if self.manual_override is not None:
            self.overall_passed = self.manual_override
        else:
            self.overall_passed = all(v.passed for v in self.verdicts.values())


class ImageFilter(ABC):
    """Abstract base class for a single filtering step."""

    name: str

    @abstractmethod
    def evaluate(self, image_path: Path, metadata: dict[str, Any]) -> FilterVerdict:
        """Evaluate one image. metadata is the normalized note data."""
        ...
