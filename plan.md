# Chasing Bread - Development Plan

## Phase 1: Data Collection [DONE]

XHS scraper, tag tracker, normalize pipeline, CLI. All functional.

## Phase 2A: Data Quality Filtering [NEXT]

Filter raw collected data for quality and relevance before annotation and training.

### Deliverables

1. Filter pipeline framework (composable ImageFilter interface)
2. Basic image filters: resolution, blur detection, aspect ratio
3. Image-level dedup via pHash
4. Text negative keyword exclusion
5. Chinese-CLIP ViT-H/14 semantic relevance scoring
6. HTML visual report for human review
7. Training-format export (`metadata.jsonl`)

### Implementation Order

1. `filters/base.py` — ABC, FilterVerdict, ImageRecord dataclasses
2. `filters/resolution.py`, `filters/blur.py`, `filters/aspect_ratio.py` — Pillow-based, no new deps
3. `filters/duplicate.py` — pHash via imagehash
4. `filters/negative_keyword.py` — rule-based text filter
5. `filters/clip_relevance.py` — Chinese-CLIP ViT-H/14
6. `pipelines/filter.py` — pipeline orchestrator
7. `pipelines/report.py` — HTML visual report
8. `pipelines/export.py` — training format export
9. CLI `filter` command integration
10. Tests

### Tech choices

- Chinese-CLIP ViT-H/14 (24G consumer GPU)
- Tag-based filtering (no hard delete)
- Image-level dedup
- Source text as reference only, not caption

See `docs/phase2a_filtering.md` for full design.

## Phase 2B: Data Annotation & Enhancement [PLANNED]

Use multimodal model to generate structured captions for filtered images. Builds on CLIP embeddings and category scores from Phase 2A.

Key questions in `open_questions.md`.

## Phase 3: Core Model Training [PLANNED]

Fine-tune image generation model (e.g., SDXL / Flux) with LoRA on annotated dataset.

## Phase 4: Full Recipe Generation [PLANNED]

Expand from image rendering to full recipe generation (instructions, flavors, ingredients).

## Phase 5: Category Expansion [PLANNED]

Extend beyond cakes/drinks to broader food categories.
