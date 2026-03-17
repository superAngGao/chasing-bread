"""Xiaohongshu scraper for cake & drink images.

Uses the data_collection.xhs platform SDK with vendor/MediaCrawler
as a git submodule. Fully self-contained.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from data_collection.utils import RateLimiter
from data_collection.xhs.search import search_keyword

from .base import BaseScraper, ScrapeResult

logger = logging.getLogger(__name__)

# Cake / drink related keywords used for filtering results
CATEGORY_KEYWORDS: set[str] = {
    "蛋糕",
    "甜品",
    "甜点",
    "烘焙",
    "面包",
    "慕斯",
    "马卡龙",
    "泡芙",
    "奶茶",
    "饮品",
    "果汁",
    "咖啡",
    "奶昔",
    "气泡水",
    "冰淇淋",
    "cake",
    "dessert",
    "pastry",
    "drink",
    "boba",
    "coffee",
    "smoothie",
}


def _is_cake_or_drink(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in CATEGORY_KEYWORDS)


class XhsCakeDrinkScraper(BaseScraper):
    """Collects cake / drink images from Xiaohongshu (小红书)."""

    platform: str = "xhs"

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(rate_limiter)

    def search(self, keyword: str, max_pages: int = 5) -> ScrapeResult:
        """Search XHS for *keyword* and collect items related to cakes/drinks."""
        result = ScrapeResult(keyword=keyword, platform=self.platform)

        logger.info("Searching XHS for '%s' (max %d pages)", keyword, max_pages)
        try:
            search_result = search_keyword(keyword=keyword, pages=max_pages)
            raw_items: list[dict[str, Any]] = search_result.items
        except Exception:
            logger.error("XHS search failed for keyword '%s'", keyword, exc_info=True)
            return result

        # If the keyword itself is a cake/drink term, skip filtering
        keyword_matches = _is_cake_or_drink(keyword)
        for item in raw_items:
            if keyword_matches:
                result.items.append(item)
                continue
            card = item.get("note_card") or item.get("noteCard") or {}
            title = item.get("title", "") or card.get("display_title", "") or card.get("title", "")
            desc = item.get("desc", "") or card.get("desc", "") or card.get("content", "")
            combined = f"{title} {desc} {keyword}"
            if _is_cake_or_drink(combined):
                result.items.append(item)

        result.pages_fetched = max_pages
        logger.info(
            "Collected %d/%d items for '%s'%s",
            len(result.items),
            len(raw_items),
            keyword,
            "" if keyword_matches else " (filtered)",
        )
        return result

    def download_images(
        self,
        items: list[dict[str, Any]],
        out_dir: Path,
    ) -> list[Path]:
        """Fetch note details to get image URLs, then download them.

        The search API only returns image dimensions — actual URLs require
        the note detail API, which returns ``image_list[].info_list[].url``.
        """
        import asyncio

        import httpx

        from data_collection.xhs.api_client import XhsApiClient

        out_dir.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []

        # Collect image URLs via the detail API (needs browser session for signing)
        url_map: dict[str, list[str]] = {}  # note_id -> [url, ...]

        async def _fetch_urls():
            async with XhsApiClient(debug=False) as api:
                for item in items:
                    note_id = item.get("id") or (item.get("note_card") or {}).get("id", "")
                    xsec_token = item.get("xsec_token", "")
                    if not note_id:
                        continue
                    try:
                        detail = await api.get_note_detail(note_id, xsec_token)
                    except Exception:
                        logger.debug("Failed to get detail for %s", note_id)
                        continue
                    urls: list[str] = []
                    for img in detail.get("image_list") or []:
                        info_list = img.get("info_list") or []
                        # Pick the largest (last) or any available URL
                        for info in reversed(info_list):
                            u = info.get("url", "")
                            if u:
                                urls.append(u)
                                break
                        else:
                            # Fallback: direct url field
                            u = img.get("url") or img.get("url_default", "")
                            if u:
                                urls.append(u)
                    if urls:
                        url_map[note_id] = urls

        asyncio.run(_fetch_urls())
        logger.info("Fetched image URLs for %d/%d notes", len(url_map), len(items))

        # Download the images
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            for note_id, urls in url_map.items():
                for idx, url in enumerate(urls):
                    self.rate_limiter.wait_sync()
                    try:
                        resp = client.get(url)
                        resp.raise_for_status()
                    except Exception:
                        logger.debug("Failed to download %s", url[:80])
                        continue

                    ext = _guess_ext(resp.headers.get("content-type", ""))
                    path = out_dir / f"{note_id}_{idx}{ext}"
                    path.write_bytes(resp.content)
                    saved.append(path)

        logger.info("Downloaded %d images to %s", len(saved), out_dir)
        return saved


def _guess_ext(content_type: str) -> str:
    ct = content_type.lower()
    if "png" in ct:
        return ".png"
    if "webp" in ct:
        return ".webp"
    if "gif" in ct:
        return ".gif"
    return ".jpg"
