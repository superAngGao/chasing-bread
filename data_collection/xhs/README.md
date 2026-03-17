# XHS Platform SDK

Self-contained Xiaohongshu (小红书) API library. Ported from [XHS_Scraper](https://github.com/TsuITOAR/XHS_scraper), backed by [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) (vendored as git submodule).

## Module Layout

```text
xhs/
├── mc_api/              # Low-level MediaCrawler integration
│   ├── _errors.py       # XhsApiError, PageNavigatedError, is_account_state_error
│   ├── _symbols.py      # MediaCrawler symbol loader (XiaoHongShuClient, etc.)
│   ├── _headers.py      # HTTP headers and cookie utilities
│   ├── _dom.py          # Playwright DOM helpers (scroll, popup, login check)
│   ├── _client.py       # Client instantiation and caching
│   ├── _search.py       # Search and comment API wrappers
│   └── _api.py          # Note detail, creator, and sub-comment APIs
├── api_client.py        # High-level async API client (XhsApiClient)
├── search.py            # Keyword search with pagination and deduplication
├── session.py           # Session lifecycle with auto-retry on auth failure
├── qrcode_auth.py       # QR code login via Playwright
├── error_handler.py     # Error classification (ErrorType → RecoveryAction)
├── request_utils.py     # Throttling, failure streaks, exponential backoff
├── item_parser.py       # Note ID extraction from API responses
└── tag_tracker/         # Tag tracking with scheduling
    ├── config.py        # TagTrackConfig dataclass
    ├── helpers.py       # Data extraction utilities
    └── tracker.py       # Core tracking logic + interval/daily schedulers
```

## Usage

### Keyword search

```python
from data_collection.xhs.search import search_keyword

result = search_keyword(keyword="蛋糕", pages=3)
print(f"Found {len(result.items)} items")
```

### API client (async)

```python
from data_collection.xhs.api_client import XhsApiClient

async with XhsApiClient() as api:
    data = await api.search_notes("美食")
    detail = await api.get_note_detail(note_id, xsec_token)
    comments = await api.get_all_comments(note_id, xsec_token)
```

### Tag tracking

```python
from data_collection.xhs.tag_tracker import TagTrackConfig, run_tracking_once

cfg = TagTrackConfig(tags=["蛋糕"], out_path=Path("tracker.json"))
summary = run_tracking_once(cfg)
```
