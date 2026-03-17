"""Project settings loaded from environment variables and .env file."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="CHASING_BREAD_",
        extra="ignore",
    )

    # -- paths --
    project_root: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[2])
    data_dir: Path | None = None
    raw_data_dir: Path | None = None
    processed_data_dir: Path | None = None
    logs_dir: Path | None = None

    # -- scraping --
    rate_limit_rps: float = Field(default=0.5, description="Max requests per second")
    respect_robots_txt: bool = True
    default_platform: str = "xhs"
    request_timeout: int = 30

    # -- search --
    search_keywords: list[str] = Field(
        default_factory=lambda: ["蛋糕", "甜品", "奶茶", "饮品", "烘焙"],
        description="Default search keywords for cake/drink collection",
    )
    max_pages_per_keyword: int = 5

    # -- output --
    output_format: str = "json"

    # -- logging --
    log_level: str = "INFO"
    debug: bool = False

    def model_post_init(self, __context: object) -> None:
        if self.data_dir is None:
            self.data_dir = self.project_root / "data"
        if self.raw_data_dir is None:
            self.raw_data_dir = self.data_dir / "raw"
        if self.processed_data_dir is None:
            self.processed_data_dir = self.data_dir / "processed"
        if self.logs_dir is None:
            self.logs_dir = self.data_dir / "logs"

    def ensure_data_directories(self) -> None:
        for d in (self.raw_data_dir, self.processed_data_dir, self.logs_dir):
            if d is not None:
                d.mkdir(parents=True, exist_ok=True)

    def setup_logging(self) -> None:
        logging.basicConfig(
            level=getattr(logging, self.log_level.upper(), logging.INFO),
            format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
