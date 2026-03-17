# Config

Centralized project configuration using [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).

## Settings

All settings can be set via environment variables or a `.env` file in the project root. To avoid collisions with generic shell variables such as `DEBUG`, use the `CHASING_BREAD_` prefix shown in [.env.example](../../.env.example).

Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `CHASING_BREAD_LOG_LEVEL` | `INFO` | Logging verbosity |
| `CHASING_BREAD_RATE_LIMIT_RPS` | `0.5` | Max requests per second |
| `CHASING_BREAD_DEFAULT_PLATFORM` | `xhs` | Default scraping platform |
| `CHASING_BREAD_MAX_PAGES_PER_KEYWORD` | `5` | Pages to fetch per search keyword |
| `CHASING_BREAD_DATA_DIR` | `./data` | Base directory for all data |
| `CHASING_BREAD_OUTPUT_FORMAT` | `json` | Output format (json) |

## Usage

```python
from data_collection.config import get_settings

settings = get_settings()
settings.ensure_data_directories()
```
