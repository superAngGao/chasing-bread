from __future__ import annotations

from typing import Any

from ._headers import build_headers, cookie_header_to_dict
from ._symbols import load_symbols

_CLIENT_CACHE: dict[int, tuple[str, Any]] = {}


async def get_client(*, page, cookie_header: str):
    key = id(page)
    cached = _CLIENT_CACHE.get(key)
    if cached and cached[0] == cookie_header:
        return cached[1]

    XiaoHongShuClient, _, _, _ = load_symbols()
    client = XiaoHongShuClient(
        proxy=None,
        headers=build_headers(cookie_header),
        playwright_page=page,
        cookie_dict=cookie_header_to_dict(cookie_header),
        proxy_ip_pool=None,
    )
    _CLIENT_CACHE[key] = (cookie_header, client)
    return client


def get_search_id_via_api() -> str:
    _, _, _, help_module = load_symbols()
    return help_module.get_search_id()
