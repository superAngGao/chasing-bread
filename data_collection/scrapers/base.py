"""Abstract base scraper defining the interface all scrapers must implement."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from data_collection.config import get_settings
from data_collection.utils import RateLimiter

logger = logging.getLogger(__name__)


@dataclass
class ScrapeResult:
    """Container for a batch of scraped items."""

    keyword: str
    platform: str
    items: list[dict[str, Any]] = field(default_factory=list)
    pages_fetched: int = 0

    def save(self, out_dir: Path | None = None) -> Path:
        """Persist results as a JSON file and return the path."""
        settings = get_settings()
        out_dir = out_dir or settings.raw_data_dir
        if out_dir is None:
            raise ValueError("No output directory configured")
        out_dir.mkdir(parents=True, exist_ok=True)

        safe_keyword = self.keyword.replace("/", "_").replace("\\", "_")
        filename = f"{self.platform}_{safe_keyword}_{self.pages_fetched}p.json"
        path = out_dir / filename

        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "keyword": self.keyword,
                    "platform": self.platform,
                    "pages_fetched": self.pages_fetched,
                    "total_items": len(self.items),
                    "items": self.items,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        logger.info("Saved %d items to %s", len(self.items), path)
        return path


class BaseScraper(ABC):
    """Interface that every platform scraper must implement."""

    platform: str = "unknown"

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        settings = get_settings()
        self.rate_limiter = rate_limiter or RateLimiter(max_rps=settings.rate_limit_rps)

    @abstractmethod
    def search(self, keyword: str, max_pages: int = 5) -> ScrapeResult:
        """Search for posts matching *keyword* and return collected items."""

    @abstractmethod
    def download_images(self, items: list[dict[str, Any]], out_dir: Path) -> list[Path]:
        """Download images from scraped items into *out_dir*. Return saved paths."""
