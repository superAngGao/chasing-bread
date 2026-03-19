from __future__ import annotations

import os
from pathlib import Path

import pytest

from data_collection.config.settings import Settings


class TestSettings:
    def test_default_values(self):
        settings = Settings()
        assert settings.rate_limit_rps == 0.5
        assert settings.default_platform == "xhs"
        assert settings.output_format == "json"
        assert settings.log_level == "INFO"
        assert settings.request_timeout == 30
        assert settings.max_pages_per_keyword == 5

    def test_default_keywords(self):
        settings = Settings()
        assert "蛋糕" in settings.search_keywords
        assert "奶茶" in settings.search_keywords

    def test_data_dir_auto_creation(self):
        settings = Settings()
        assert settings.data_dir is not None
        assert settings.raw_data_dir is not None
        assert settings.processed_data_dir is not None
        assert settings.logs_dir is not None
        # Subdirs should be under data_dir
        assert str(settings.raw_data_dir).startswith(str(settings.data_dir))
        assert str(settings.processed_data_dir).startswith(str(settings.data_dir))

    def test_custom_data_dir(self, tmp_path):
        settings = Settings(data_dir=tmp_path)
        assert settings.data_dir == tmp_path
        assert settings.raw_data_dir == tmp_path / "raw"

    def test_env_var_override(self, monkeypatch):
        monkeypatch.setenv("CHASING_BREAD_RATE_LIMIT_RPS", "2.0")
        monkeypatch.setenv("CHASING_BREAD_LOG_LEVEL", "DEBUG")
        settings = Settings()
        assert settings.rate_limit_rps == 2.0
        assert settings.log_level == "DEBUG"

    def test_ensure_data_directories(self, tmp_path):
        settings = Settings(data_dir=tmp_path)
        settings.ensure_data_directories()
        assert (tmp_path / "raw").is_dir()
        assert (tmp_path / "processed").is_dir()
        assert (tmp_path / "logs").is_dir()
