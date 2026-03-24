"""CLI entry point for the data collection module."""

from __future__ import annotations

import logging
from pathlib import Path

import typer

from data_collection.config import get_settings
from data_collection.pipelines.normalize import process_raw_data
from data_collection.scrapers.xhs import XhsCakeDrinkScraper
from data_collection.utils.logging_utils import configure_logging

app = typer.Typer(help="Chasing Bread – data collection CLI")
logger = logging.getLogger(__name__)


@app.callback()
def _setup(debug: bool = typer.Option(False, help="Enable debug logging")) -> None:
    settings = get_settings()
    configure_logging(debug=debug or settings.log_level.upper() == "DEBUG")
    settings.ensure_data_directories()


@app.command()
def collect(
    keywords: list[str] | None = typer.Option(
        None,
        "--keyword",
        "-k",
        help="Search keywords (repeatable). Defaults to built-in cake/drink terms.",
    ),
    max_pages: int = typer.Option(5, "--pages", "-p", help="Max pages per keyword"),
    download: bool = typer.Option(False, "--download", "-d", help="Also download images"),
) -> None:
    """Search XHS for cake/drink posts and save raw results."""
    settings = get_settings()
    kws = keywords or settings.search_keywords
    scraper = XhsCakeDrinkScraper()

    for kw in kws:
        result = scraper.search(kw, max_pages=max_pages)
        if result.items:
            path = result.save()
            typer.echo(f"[{kw}] saved {len(result.items)} items → {path}")

            if download and settings.raw_data_dir is not None:
                img_dir = settings.raw_data_dir / "images" / kw
                saved = scraper.download_images(result.items, img_dir)
                typer.echo(f"[{kw}] downloaded {len(saved)} images → {img_dir}")
        else:
            typer.echo(f"[{kw}] no items found")


@app.command()
def normalize(
    input_file: Path = typer.Argument(..., help="Raw JSON file to normalize"),
    output_file: Path | None = typer.Option(None, "--out", "-o", help="Output path"),
) -> None:
    """Normalize a raw data file into the canonical recipe-image schema."""
    out = process_raw_data(input_file, output_file)
    typer.echo(f"Processed → {out}")


@app.command()
def info() -> None:
    """Show current settings and detected paths."""
    settings = get_settings()
    vendor_mc = settings.project_root / "vendor" / "MediaCrawler"
    typer.echo(f"Project root     : {settings.project_root}")
    typer.echo(f"Data directory   : {settings.data_dir}")
    typer.echo(f"MediaCrawler     : {vendor_mc} ({'found' if vendor_mc.is_dir() else 'NOT FOUND'})")
    typer.echo(f"Rate limit       : {settings.rate_limit_rps} rps")
    typer.echo(f"Default keywords : {', '.join(settings.search_keywords)}")


def _parse_tags(
    tag_options: list[str] | None,
    tags_str: str | None,
    tags_file: Path | None,
) -> list[str]:
    """Merge tags from --tag, --tags (JSON list or comma-separated), and --tags-file.

    Accepts:
        --tags '["抹茶蛋糕","珍珠奶茶"]'   (JSON array)
        --tags "抹茶蛋糕,珍珠奶茶"          (comma-separated)
        --tag "抹茶蛋糕" --tag "珍珠奶茶"   (repeatable)
        --tags-file tags.txt               (one per line)
    """
    import json as _json

    result: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        t = raw.strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            result.append(t)

    def _add_many(raw: str) -> None:
        for part in raw.split(","):
            _add(part)

    if tag_options:
        for t in tag_options:
            _add(t)
    if tags_str:
        s = tags_str.strip()
        if s.startswith("["):
            try:
                parsed = _json.loads(s)
                if isinstance(parsed, list):
                    for t in parsed:
                        if isinstance(t, str):
                            _add(t)
                else:
                    _add_many(s)
            except _json.JSONDecodeError:
                _add_many(s)
        else:
            _add_many(s)
    if tags_file and tags_file.exists():
        for line in tags_file.read_text(encoding="utf-8").splitlines():
            _add(line)
    return result


@app.command("tag-track")
def tag_track(
    tag_options: list[str] | None = typer.Option(
        None,
        "--tag",
        "-t",
        help="Tags to track (repeatable).",
    ),
    tags_str: str | None = typer.Option(
        None,
        "--tags",
        help='Comma-separated tags, e.g. "美食,探店,抹茶蛋糕".',
    ),
    tags_file: Path | None = typer.Option(
        None,
        "--tags-file",
        help="File with one tag per line.",
    ),
    out: Path = typer.Option(
        "data/raw/tag_tracker.json",
        "--out",
        "-o",
        help="Tracker JSON output file.",
    ),
    pages_per_tag: int = typer.Option(3, "--pages", help="Search pages per tag"),
    page_size: int = typer.Option(20, "--page-size"),
    max_comments: int = typer.Option(100, "--max-comments", help="Max comments per note"),
    skip_older_days: int = typer.Option(
        30, "--skip-older-days", help="Skip detail for notes older than N days"
    ),
    auto_expand: bool = typer.Option(
        True,
        "--auto-expand/--no-auto-expand",
        help="Auto-discover related tags from note content.",
    ),
    auto_expand_threshold: float = typer.Option(
        0.3, "--expand-threshold", help="Min tag hit-rate to auto-add (0-1)."
    ),
    max_auto_tags: int = typer.Option(10, "--max-auto-tags", help="Max tags to auto-add per run."),
    refresh_cached: bool = typer.Option(
        True,
        "--refresh-cached/--no-refresh-cached",
        help="Refresh previously tracked notes not in current search.",
    ),
    stable_max_rounds: int = typer.Option(
        3, "--stable-rounds", help="Max refresh rounds before declaring stable."
    ),
    once: bool = typer.Option(True, "--once/--schedule", help="Run once (default) or schedule"),
    run_at: str | None = typer.Option(
        None, "--run-at", help="Daily run time HH:MM (implies --schedule)"
    ),
    interval: float = typer.Option(30.0, "--interval", help="Interval minutes (with --schedule)"),
    force_qrcode: bool = typer.Option(False, "--force-qrcode"),
    nologin: bool = typer.Option(False, "--nologin"),
) -> None:
    """Track XHS tags over time — search, collect details & comments."""
    from data_collection.xhs.tag_tracker import (
        TagTrackConfig,
        run_daily_scheduler,
        run_interval_scheduler,
        run_tracking_once,
    )

    tags = _parse_tags(tag_options, tags_str, tags_file)
    if not tags:
        typer.echo("Error: provide at least one tag via --tag, --tags, or --tags-file", err=True)
        raise typer.Exit(1)

    cfg = TagTrackConfig(
        tags=tags,
        out_path=out,
        pages_per_tag=pages_per_tag,
        page_size=page_size,
        max_comments_per_note=max_comments,
        skip_detail_older_than_days=skip_older_days,
        auto_expand_tags=auto_expand,
        auto_expand_hit_rate_threshold=auto_expand_threshold,
        max_auto_expand_tags=max_auto_tags,
        refresh_cached=refresh_cached,
        stable_max_rounds=stable_max_rounds,
        force_qrcode=force_qrcode,
        nologin=nologin,
        debug=logger.isEnabledFor(logging.DEBUG),
    )

    if run_at:
        run_daily_scheduler(cfg, run_at)
    elif not once:
        run_interval_scheduler(cfg, interval_minutes=interval)
    else:
        summary = run_tracking_once(cfg)
        auto_tags = summary.get("auto_added_tags", [])
        auto_str = f", auto-added {len(auto_tags)} tags" if auto_tags else ""
        typer.echo(
            f"Done: {summary['notes_discovered']} discovered, "
            f"{summary['notes_updated']} updated, "
            f"{summary['notes_skipped_old']} skipped (old)"
            f"{auto_str}"
        )


@app.command("filter")
def filter_cmd(
    input_file: Path = typer.Argument(..., help="Processed JSON file from normalize"),
    images: Path = typer.Option(..., "--images", "-i", help="Directory with downloaded images"),
    out: Path = typer.Option("data/filtered/report.json", "--out", "-o", help="Output report JSON"),
    html: Path = typer.Option("data/filtered/report.html", "--html", help="HTML visual report"),
    export: Path | None = typer.Option(None, "--export", "-e", help="Export metadata.jsonl path"),
    clip_threshold: float = typer.Option(0.3, "--clip-threshold", help="CLIP relevance threshold"),
    min_resolution: int = typer.Option(512, "--min-res", help="Minimum width/height in px"),
    max_aspect_ratio: float = typer.Option(3.0, "--max-ratio", help="Maximum aspect ratio"),
    min_blur_var: float = typer.Option(100.0, "--min-blur-var", help="Minimum Laplacian variance"),
    max_hamming: int = typer.Option(6, "--max-hamming", help="Max hamming distance for dedup"),
    fail_fast: bool = typer.Option(False, "--fail-fast", help="Stop filters on first rejection"),
    no_clip: bool = typer.Option(False, "--no-clip", help="Skip CLIP filter (faster)"),
) -> None:
    """Filter processed data for quality, relevance, and duplicates."""
    import json

    from data_collection.pipelines.filter import FilterPipeline, save_report
    from data_collection.pipelines.filters.aspect_ratio import AspectRatioFilter
    from data_collection.pipelines.filters.blur import BlurFilter
    from data_collection.pipelines.filters.duplicate import DuplicateFilter
    from data_collection.pipelines.filters.negative_keyword import NegativeKeywordFilter
    from data_collection.pipelines.filters.resolution import ResolutionFilter
    from data_collection.pipelines.report import generate_html_report

    with open(input_file, encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("items", data) if isinstance(data, dict) else data
    if not isinstance(items, list):
        items = [items]

    filters = [
        ResolutionFilter(min_width=min_resolution, min_height=min_resolution),
        BlurFilter(min_laplacian_var=min_blur_var),
        AspectRatioFilter(max_ratio=max_aspect_ratio),
        DuplicateFilter(max_hamming_distance=max_hamming),
        NegativeKeywordFilter(),
    ]

    if not no_clip:
        from data_collection.pipelines.filters.clip_relevance import ClipRelevanceFilter

        embedding_dir = out.parent / "embeddings"
        filters.append(ClipRelevanceFilter(threshold=clip_threshold, embedding_dir=embedding_dir))

    pipeline = FilterPipeline(filters, fail_fast=fail_fast)
    report = pipeline.run_batch(items, images)

    save_report(report, out)
    typer.echo(
        f"Report: {report.total_images} total, {report.passed} passed, {report.rejected} rejected"
    )
    typer.echo(f"  → {out}")

    generate_html_report(report, html)
    typer.echo(f"  → {html}")

    if export is not None:
        from data_collection.pipelines.export import export_metadata_jsonl

        export_metadata_jsonl(report, export)
        typer.echo(f"  → {export}")


if __name__ == "__main__":
    app()
