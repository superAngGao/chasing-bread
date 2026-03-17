# Pipelines

Data normalization and transformation from raw scraped data to a canonical schema.

## Canonical Schema

Each normalized item follows this structure:

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Platform-specific post ID |
| `platform` | `str` | Source platform (e.g., `xhs`) |
| `title` | `str` | Post title |
| `description` | `str` | Post body / description |
| `author_id` | `str` | Author's platform ID |
| `author_name` | `str` | Author display name |
| `image_urls` | `list[str]` | URLs of associated images |
| `tags` | `list[str]` | Tags / hashtags |
| `like_count` | `int` | Number of likes |
| `collect_count` | `int` | Number of saves/collects |
| `raw_data` | `dict` | Original unmodified item |

## Usage

```python
from data_collection.pipelines import normalize_recipe_item, process_raw_data

# Single item
canonical = normalize_recipe_item(raw_item, platform="xhs")

# Batch process a file
process_raw_data(Path("data/raw/xhs_蛋糕_5p.json"))
```
