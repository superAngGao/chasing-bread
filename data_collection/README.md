# Data Collection Module

Scrapes food recipe data (images, descriptions, tags) from public platforms, with an initial focus on **cake and drink** categories.

## Structure

```text
data_collection/
├── config/       # Settings and environment config
├── xhs/          # XHS platform SDK (API client, search, auth, tracking)
│   ├── mc_api/   # Low-level MediaCrawler integration
│   └── tag_tracker/  # Tag tracking with scheduling
├── scrapers/     # Thin scraper layer (uses xhs/ SDK)
│   ├── base.py   # Abstract scraper interface
│   └── xhs.py    # XHS cake/drink scraper
├── pipelines/    # Data normalization and export
├── utils/        # Shared utilities (rate limiting, logging)
└── cli.py        # CLI (collect, normalize, tag-track, info)
```

## Usage

```bash
$env:UV_CACHE_DIR=".uv-cache"

# Collect cake/drink posts from XHS using default keywords
uv run chasing-bread collect

# Custom keywords with image download
uv run chasing-bread collect -k "抹茶蛋糕" -k "珍珠奶茶" --download

# Normalize raw data
uv run chasing-bread normalize data/raw/xhs_蛋糕_5p.json

# Show config
uv run chasing-bread info

# Track tags over time (search + detail + comments)
uv run chasing-bread tag-track -t "蛋糕" -t "奶茶" --once

# Schedule tag tracking every 30 minutes
uv run chasing-bread tag-track -t "甜品" --schedule --interval 30

# Alternative module entrypoint
python -m data_collection info
```

## Dependencies

All scraping code is bundled in the project. The underlying [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) is included as a git submodule under `vendor/MediaCrawler`. Initialize it with:

```bash
git submodule update --init --recursive
```
