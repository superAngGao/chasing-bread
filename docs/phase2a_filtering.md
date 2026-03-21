# Phase 2A: Data Quality Filtering

## Background

Phase 1 (data collection) is complete. The pipeline collects XHS posts about cakes/drinks, downloads images, and normalizes data into a canonical schema. However, raw data contains significant noise: irrelevant images (ads, screenshots, unrelated content), blurry photos, duplicates, and misleading text-image pairs (e.g., "奶茶色穿搭" is about fashion, not drinks).

Phase 2A adds a filtering pipeline to clean the data before annotation (Phase 2B) and model training (Phase 3).

## Decisions

| Topic | Decision | Rationale |
|-------|----------|-----------|
| Semantic filter model | Chinese-CLIP ViT-H/14 | Chinese text support required; ViT-H/14 best accuracy; 24G VRAM sufficient (~8GB) |
| Filter strategy | Tag, not delete | Preserve raw data; add scores + pass/fail fields; allows threshold tuning later |
| Dedup granularity | Image-level | Training needs individual images; cross-note dedup via pHash |
| Source text handling | Reference only | XHS text too noisy for direct caption use; stored as `source_title`/`source_desc`; formal captions deferred to Phase 2B |

## Pipeline Architecture

### Processing Order

Cheap filters first, expensive filters last. CLIP only runs on images that pass initial screening.

```
Input: processed JSON + downloaded image directory
  |
  1. Basic image filter (Pillow): resolution, corruption, aspect ratio
  |
  2. Image dedup (imagehash pHash)
  |
  3. Negative keyword exclusion: text-based reject ("装修", "穿搭", etc.)
  |
  4. CLIP semantic filter: Chinese-CLIP ViT-H/14 relevance scoring
  |
Output: annotated ImageRecord JSON + stats report + HTML visual report
```

### Filter Interface

Each filter is an independent unit implementing a common interface:

```python
class ImageFilter(ABC):
    name: str

    @abstractmethod
    def evaluate(self, image_path: Path, metadata: dict) -> FilterVerdict:
        ...

@dataclass
class FilterVerdict:
    passed: bool
    score: float          # 0.0 ~ 1.0
    reason: str           # empty if passed
    filter_name: str
    details: dict         # filter-specific intermediate data
```

Concrete filters:

- `ResolutionFilter` — minimum width/height threshold (e.g., 512x512)
- `BlurFilter` — Laplacian variance below threshold = blurry
- `AspectRatioFilter` — extreme ratios (e.g., >4:1) rejected
- `DuplicateFilter` — pHash hamming distance, marks duplicate groups
- `NegativeKeywordFilter` — title/desc contains exclude terms
- `ClipRelevanceFilter` — Chinese-CLIP similarity against category prompts

### CLIP Scoring Strategy

Use positive prompts to compute image-text similarity. Take the max score across all prompts as the image's relevance score, and store per-prompt scores in `clip_category_scores` for coarse classification.

**Positive prompts:**

```python
POSITIVE_PROMPTS = {
    "cake": "蛋糕成品照片",
    "drink": "饮品成品照片",
    "dessert": "甜点特写",
    "bread": "面包烘焙成品",
    "coffee": "咖啡饮料",
}
```

- `score = max(similarity across all prompts)`
- `clip_category_scores = {"cake": 0.82, "drink": 0.15, ...}` — all prompt scores preserved
- Default threshold: 0.3 (to be tuned via HTML report after first batch run)
- CLIP image embeddings saved as `.npy` files for reuse in Phase 2B (clustering, retrieval)

### FilterPipeline

```python
class FilterPipeline:
    def __init__(self, filters: list[ImageFilter]):
        self.filters = filters

    def run(self, image_path: Path, metadata: dict) -> list[FilterVerdict]:
        ...

    def run_batch(self, items: list[dict], image_dir: Path) -> FilterReport:
        ...
```

Supports `fail_fast=True` (short-circuit on first rejection) or full evaluation for complete reports.

### Output: ImageRecord

Each processed image produces one record:

```python
@dataclass
class ImageRecord:
    image_path: Path
    source_note_id: str
    source_title: str
    source_desc: str

    # Image metadata
    width: int
    height: int
    file_size: int
    format: str

    # Filter verdicts
    verdicts: dict[str, FilterVerdict]
    overall_passed: bool

    # Reusable assets
    phash: str                    # for incremental dedup
    clip_embedding: str           # file path to .npy
    clip_category_scores: dict    # {"cake": 0.82, "drink": 0.15, ...}
    duplicate_of: str | None      # primary image ID if duplicate

    # Manual review
    manual_override: bool | None  # None=unreviewed, True/False=human verdict
```

Key design points:
- **CLIP embeddings cached** as .npy files — expensive to compute, reusable for clustering/retrieval in Phase 2B
- **pHash stored** — enables incremental dedup when new images are added
- **Category scores preserved** — coarse classification (cake/drink/pastry/other) serves as prior for Phase 2B annotation
- **Duplicate group tracking** — keeps the highest-quality image, records relationships
- **Manual override** — supports human review of borderline cases

### User-Facing Outputs

1. **Annotated JSON** — full ImageRecord data for programmatic use
2. **HTML visual report** — thumbnail grid grouped by filter result (passed / each rejection reason), clickable to view full image; for threshold tuning and spot-checking
3. **Export to training format** — one-command export to `metadata.jsonl` with `{"file_name": "xxx.jpg", "text": "..."}` for downstream training

### CLI Integration

New `filter` command:

```bash
uv run chasing-bread filter data/processed/processed_xxx.json --images data/raw/images/蛋糕/
```

### New Dependencies

- `imagehash` — perceptual hashing
- `cn_clip` (Chinese-CLIP) — semantic filtering
- `torch` — CLIP inference backend

## File Structure

```
data_collection/
  pipelines/
    normalize.py          # existing
    filter.py             # pipeline orchestrator + CLI integration
    filters/
      base.py             # ImageFilter ABC, FilterVerdict, ImageRecord
      resolution.py
      blur.py
      aspect_ratio.py
      duplicate.py
      negative_keyword.py
      clip_relevance.py
    report.py             # HTML report generation
    export.py             # training format export
```
