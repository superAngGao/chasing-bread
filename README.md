# Chasing Bread

An AI application that generates food recipes — including instructions, flavor profiles, ingredients, and predicted rendering pictures of the final dish.

## Current Focus

The initial phase targets **cake and drink categories**, as their visual presentation is more selective and deterministic compared to other foods. The primary goal right now is generating realistic **rendering pictures** of recipes.

## Architecture

The project is built in Python and consists of the following core components:

### Data Collection Module (`data_collection/`)

Collects recipe-related data (images, descriptions, ingredients, etc.) from public networks. Self-contained with [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) vendored as a git submodule.

```text
data_collection/
├── config/          # Pydantic-based settings (.env support)
├── xhs/             # XHS platform SDK (session, API client, search, tracking)
│   ├── mc_api/      # MediaCrawler integration layer
│   │   ├── _errors.py   # Error types
│   │   ├── _symbols.py  # MediaCrawler symbol loader
│   │   ├── _headers.py  # HTTP header/cookie utils
│   │   ├── _dom.py      # Playwright DOM helpers
│   │   ├── _client.py   # Client instantiation
│   │   └── _search.py   # Search + comment API wrappers
│   ├── api_client.py    # High-level async API client
│   ├── search.py        # Keyword search with pagination
│   ├── session.py       # Session lifecycle + QR auth
│   └── tag_tracker/     # Tag tracking with scheduling
├── scrapers/        # Thin scraper layer (uses xhs/ SDK)
│   ├── base.py      # Abstract scraper interface
│   └── xhs.py       # XHS cake/drink scraper
├── pipelines/       # Data normalization to canonical schema
├── utils/           # Rate limiter, logging helpers
└── cli.py           # CLI (collect, normalize, tag-track, info)
vendor/
└── MediaCrawler/    # Git submodule (DO NOT MODIFY)
```

**Quick start:**

```bash
# Clone with submodules
git clone --recurse-submodules <repo-url>

# Install a local virtualenv
$env:UV_CACHE_DIR=".uv-cache"
uv sync

# Run the CLI through uv
uv run chasing-bread collect

# Search with custom keywords and download images
uv run chasing-bread collect -k "抹茶蛋糕" -k "珍珠奶茶" --download

# Normalize a raw data file
uv run chasing-bread normalize data/raw/xhs_蛋糕_5p.json

# Show current config
uv run chasing-bread info

# Alternative without the console-script shim
python -m data_collection info
```

`chasing-bread` is a packaged console script, so calling it directly only works after the project environment is installed and active. In PowerShell, `uv run ...` is the safest default.

### Data Preprocessing & Filtering

A lightweight AI module that filters collected data for relevance and quality, then preprocesses it into formats suitable for model training.

### Core Model Training

The central component that fine-tunes and trains the main generative AI model for recipe rendering and generation.

### Test Utilities

Supporting scripts and tools for evaluation, debugging, and experimentation — can take any form as needed.

## Tech Stack

- **Language:** Python
- **Domain:** Generative AI, image synthesis, recipe generation

## Planning

See `plan.md` for development roadmap and `docs/` for design documents.
