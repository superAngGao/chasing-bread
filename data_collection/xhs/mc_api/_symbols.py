"""MediaCrawler symbol loader — imports XiaoHongShuClient and related types."""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
import types
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)
logging.getLogger("MediaCrawler").setLevel(logging.WARNING)


def _find_vendor_root() -> Path:
    """Locate vendor/MediaCrawler relative to the project root."""
    # _symbols.py -> mc_api -> xhs -> data_collection -> project root
    repo_root = Path(__file__).resolve().parents[3]
    mc_root = repo_root / "vendor" / "MediaCrawler"
    if not mc_root.is_dir():
        raise RuntimeError(
            f"MediaCrawler not found at {mc_root}. Run: git submodule update --init --recursive"
        )
    return mc_root


@lru_cache(maxsize=1)
def load_symbols():
    """Return (XiaoHongShuClient, SearchSortType, SearchNoteType, help_module)."""
    mc_root = _find_vendor_root()
    mc_root_str = str(mc_root)
    if mc_root_str not in sys.path:
        sys.path.insert(0, mc_root_str)

    # Stub out packages that MediaCrawler expects
    media_platform_pkg = types.ModuleType("media_platform")
    media_platform_pkg.__path__ = [str(mc_root / "media_platform")]
    sys.modules.setdefault("media_platform", media_platform_pkg)

    xhs_pkg = types.ModuleType("media_platform.xhs")
    xhs_pkg.__path__ = [str(mc_root / "media_platform" / "xhs")]
    sys.modules.setdefault("media_platform.xhs", xhs_pkg)

    proxy_pkg = types.ModuleType("proxy")
    proxy_pkg.__path__ = [str(mc_root / "proxy")]
    sys.modules.setdefault("proxy", proxy_pkg)

    if "tools.utils" not in sys.modules:
        tools_pkg = types.ModuleType("tools")
        tools_pkg.__path__ = [str(mc_root / "tools")]
        sys.modules.setdefault("tools", tools_pkg)
        utils_mod = types.ModuleType("tools.utils")
        utils_mod.logger = logging.getLogger("MediaCrawler")
        sys.modules["tools.utils"] = utils_mod
    if "tools.crawler_util" not in sys.modules:
        crawler_util_mod = types.ModuleType("tools.crawler_util")

        def _extract_url_params_to_dict(url: str) -> dict[str, str]:
            from urllib.parse import parse_qsl, urlparse

            query = urlparse(url).query
            return {k: v for k, v in parse_qsl(query)}

        crawler_util_mod.extract_url_params_to_dict = _extract_url_params_to_dict
        sys.modules["tools.crawler_util"] = crawler_util_mod
    if "media_platform.xhs.extractor" not in sys.modules:
        extractor_mod = types.ModuleType("media_platform.xhs.extractor")

        class _DummyXiaoHongShuExtractor:
            pass

        extractor_mod.XiaoHongShuExtractor = _DummyXiaoHongShuExtractor
        sys.modules["media_platform.xhs.extractor"] = extractor_mod

    field_module = importlib.import_module("media_platform.xhs.field")
    help_module = importlib.import_module("media_platform.xhs.help")

    client_mod_name = "media_platform.xhs.client"
    if client_mod_name not in sys.modules:
        client_path = mc_root / "media_platform" / "xhs" / "client.py"
        spec = importlib.util.spec_from_file_location(client_mod_name, client_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Failed to load MediaCrawler xhs client module")
        module = importlib.util.module_from_spec(spec)
        sys.modules[client_mod_name] = module
        spec.loader.exec_module(module)
    client_module = sys.modules[client_mod_name]
    return (
        client_module.XiaoHongShuClient,
        field_module.SearchSortType,
        field_module.SearchNoteType,
        help_module,
    )
