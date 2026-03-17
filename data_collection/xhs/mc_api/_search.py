from __future__ import annotations

import logging
import time
from typing import Any

from ._client import get_client
from ._dom import try_clear_page_popup
from ._errors import check_page_url, to_api_error
from ._symbols import load_symbols

logger = logging.getLogger(__name__)


async def get_note_by_keyword(
    *,
    page,
    cookie_header: str,
    keyword: str,
    page_no: int,
    page_size: int,
    search_id: str,
    sort: str = "general",
    note_type: int = 0,
) -> dict[str, Any]:
    client = await get_client(page=page, cookie_header=cookie_header)
    _, SearchSortType, SearchNoteType, _ = load_symbols()

    sort_map = {
        "general": SearchSortType.GENERAL,
        "time_descending": SearchSortType.LATEST,
        "popularity_descending": SearchSortType.MOST_POPULAR,
    }
    note_type_map = {0: SearchNoteType.ALL, 1: SearchNoteType.VIDEO, 2: SearchNoteType.IMAGE}

    _pre_url = getattr(page, "url", "") or ""
    started = time.monotonic()
    try:
        data_obj = await client.get_note_by_keyword(
            keyword=keyword,
            search_id=search_id,
            page=page_no,
            page_size=page_size,
            sort=sort_map.get(sort, SearchSortType.GENERAL),
            note_type=note_type_map.get(note_type, SearchNoteType.ALL),
        )
    except Exception as first_exc:
        cleared = await try_clear_page_popup(getattr(client, "playwright_page", None))
        if not cleared:
            raise to_api_error("search", first_exc) from first_exc
        logger.info("[mc_api] search retry after popup clear keyword=%s page=%s", keyword, page_no)
        try:
            data_obj = await client.get_note_by_keyword(
                keyword=keyword,
                search_id=search_id,
                page=page_no,
                page_size=page_size,
                sort=sort_map.get(sort, SearchSortType.GENERAL),
                note_type=note_type_map.get(note_type, SearchNoteType.ALL),
            )
        except Exception as exc:
            raise to_api_error("search", exc) from exc

    elapsed = time.monotonic() - started
    _post_url = getattr(page, "url", "") or ""
    if _pre_url and _post_url and _post_url != _pre_url:
        check_page_url(page, expected=_pre_url, context="search")
    if elapsed >= 8.0:
        logger.warning(
            "[mc_api] slow search keyword=%s page=%s elapsed=%.2fs", keyword, page_no, elapsed
        )
    if not isinstance(data_obj, dict):
        raise RuntimeError("search response missing data object")
    return data_obj


async def get_note_comments(
    *,
    page,
    cookie_header: str,
    note_id: str,
    xsec_token: str,
    cursor: str,
) -> dict[str, Any]:
    client = await get_client(page=page, cookie_header=cookie_header)
    try:
        data_obj = await client.get_note_comments(
            note_id=note_id, xsec_token=xsec_token, cursor=cursor
        )
    except Exception as exc:
        raise to_api_error("comment", exc) from exc
    if not isinstance(data_obj, dict):
        raise RuntimeError("comment response missing data object")
    return data_obj
