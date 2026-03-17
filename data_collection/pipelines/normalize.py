"""Normalize raw scraped data into a canonical recipe-image schema."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def normalize_recipe_item(item: dict[str, Any], platform: str = "xhs") -> dict[str, Any]:
    """Map a raw scraped item to the canonical recipe-image schema.

    The canonical schema is designed around cake/drink visual data:
    - Metadata: id, title, description, author, platform
    - Visual: image URLs
    - Recipe hints: tags, ingredients mentioned, category
    """
    # Handle nested note_card structure (XHS specific)
    card = item.get("note_card", item)

    note_id = item.get("note_id") or item.get("id") or card.get("note_id") or card.get("id") or ""

    # Extract image URLs
    raw_images = card.get("image_list") or card.get("images") or []
    image_urls: list[str] = []
    for img in raw_images:
        if isinstance(img, str):
            image_urls.append(img)
        elif isinstance(img, dict):
            url = (
                img.get("url")
                or img.get("url_default")
                or img.get("info_list", [{}])[0].get("url", "")
            )
            if url:
                image_urls.append(url)

    # Extract tags
    tag_list = card.get("tag_list") or card.get("tags") or []
    tags: list[str] = []
    for t in tag_list:
        if isinstance(t, str):
            tags.append(t)
        elif isinstance(t, dict):
            tags.append(t.get("name", ""))

    return {
        "id": note_id,
        "platform": platform,
        "title": card.get("title", ""),
        "description": card.get("desc", "") or card.get("content", ""),
        "author_id": card.get("user_id") or card.get("user", {}).get("user_id", ""),
        "author_name": card.get("nickname") or card.get("user", {}).get("nickname", ""),
        "image_urls": image_urls,
        "tags": [t for t in tags if t],
        "like_count": _to_int(card.get("liked_count") or card.get("like_count")),
        "collect_count": _to_int(card.get("collected_count") or card.get("collect_count")),
        "raw_data": item,
    }


def normalize_items(
    items: list[dict[str, Any]],
    platform: str = "xhs",
) -> list[dict[str, Any]]:
    """Normalize a batch of items, skipping any that fail."""
    results = []
    for item in items:
        try:
            results.append(normalize_recipe_item(item, platform))
        except Exception:
            logger.warning("Failed to normalize item", exc_info=True)
    return results


def process_raw_data(
    input_path: Path,
    output_path: Path | None = None,
    platform: str = "xhs",
) -> Path:
    """Load a raw JSON file, normalize it, and write the processed output."""
    from data_collection.config import get_settings

    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    items = data.get("items", data) if isinstance(data, dict) else data
    if not isinstance(items, list):
        items = [items]

    normalized = normalize_items(items, platform)

    if output_path is None:
        settings = get_settings()
        out_dir = settings.processed_data_dir
        if out_dir is None:
            raise ValueError("No processed data directory configured")
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / f"processed_{input_path.name}"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)

    logger.info("Processed %d items → %s", len(normalized), output_path)
    return output_path


def _to_int(val: Any) -> int:
    if val is None:
        return 0
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0
