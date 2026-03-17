# Scrapers

Thin scraper layer that provides a uniform interface over platform SDKs.

## Architecture

All scrapers extend `BaseScraper` and implement two methods:

- **`search(keyword, max_pages)`** — search for posts and return a `ScrapeResult`
- **`download_images(items, out_dir)`** — download images from collected items

The heavy lifting (authentication, API calls, throttling) lives in [`data_collection.xhs`](../xhs/) — scrapers are thin wrappers that add domain-specific filtering.

## Available Scrapers

### XhsCakeDrinkScraper (`xhs.py`)

Scrapes Xiaohongshu for cake and drink posts. Uses the `data_collection.xhs` SDK.

- Keyword filtering against built-in cake/drink terms (Chinese + English)
- Cover image download via XHS CDN
- Skips filtering when the search keyword itself is a category match

## Adding a New Scraper

1. Create a new file (e.g., `pinterest.py`)
2. Subclass `BaseScraper` and implement `search()` and `download_images()`
3. Export it from `__init__.py`

## Tag Tracking

Tag tracking uses the XHS SDK directly — see [`data_collection.xhs.tag_tracker`](../xhs/tag_tracker/).

```python
from data_collection.xhs.tag_tracker import TagTrackConfig, run_tracking_once

cfg = TagTrackConfig(
    tags=["蛋糕", "奶茶"],
    out_path=Path("data/raw/tracker.json"),
)
summary = run_tracking_once(cfg)
```
