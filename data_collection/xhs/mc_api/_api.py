from __future__ import annotations

import logging
from typing import Any

from ._client import get_client
from ._errors import XhsApiError, to_api_error

logger = logging.getLogger(__name__)


async def get_note_all_comments(
    *,
    page,
    cookie_header: str,
    note_id: str,
    xsec_token: str,
    max_count: int,
    crawl_interval: float = 1.0,
) -> list[dict[str, Any]]:
    client = await get_client(page=page, cookie_header=cookie_header)
    try:
        data_obj = await client.get_note_comments(note_id=note_id, xsec_token=xsec_token, cursor="")
    except XhsApiError:
        raise
    except Exception as exc:
        logger.warning("[mc_api] comment collection failed note_id=%s: %s", note_id, exc)
        return []
    del crawl_interval
    comments = data_obj.get("comments", []) if isinstance(data_obj, dict) else []
    return [x for x in comments if isinstance(x, dict)]


async def get_note_by_id(
    *,
    page,
    cookie_header: str,
    note_id: str,
    xsec_token: str = "",
    xsec_source: str = "",
) -> dict[str, Any]:
    client = await get_client(page=page, cookie_header=cookie_header)
    try:
        data_obj = await client.get_note_by_id(
            note_id=note_id, xsec_token=xsec_token, xsec_source=xsec_source
        )
    except Exception as exc:
        raise to_api_error("note_detail", exc) from exc
    return data_obj if isinstance(data_obj, dict) else {}


async def get_note_sub_comments(
    *,
    page,
    cookie_header: str,
    note_id: str,
    root_comment_id: str,
    xsec_token: str,
    num: int = 10,
    cursor: str = "",
) -> dict[str, Any]:
    client = await get_client(page=page, cookie_header=cookie_header)
    try:
        data_obj = await client.get_note_sub_comments(
            note_id=note_id,
            root_comment_id=root_comment_id,
            xsec_token=xsec_token,
            num=num,
            cursor=cursor,
        )
    except Exception as exc:
        raise to_api_error("sub_comment", exc) from exc
    return data_obj if isinstance(data_obj, dict) else {}


async def get_creator_info(
    *,
    page,
    cookie_header: str,
    user_id: str,
    xsec_token: str = "",
    xsec_source: str = "",
) -> dict[str, Any]:
    client = await get_client(page=page, cookie_header=cookie_header)
    try:
        data_obj = await client.get_creator_info(
            user_id=user_id, xsec_token=xsec_token, xsec_source=xsec_source
        )
    except Exception as exc:
        raise to_api_error("creator_info", exc) from exc
    return data_obj if isinstance(data_obj, dict) else {}


async def get_notes_by_creator(
    *,
    page,
    cookie_header: str,
    creator: str,
    cursor: str,
    page_size: int = 30,
    xsec_token: str = "",
    xsec_source: str = "pc_feed",
) -> dict[str, Any]:
    client = await get_client(page=page, cookie_header=cookie_header)
    try:
        data_obj = await client.get_notes_by_creator(
            creator=creator,
            cursor=cursor,
            page_size=page_size,
            xsec_token=xsec_token,
            xsec_source=xsec_source,
        )
    except Exception as exc:
        raise to_api_error("creator_notes", exc) from exc
    return data_obj if isinstance(data_obj, dict) else {}


async def get_all_notes_by_creator(
    *,
    page,
    cookie_header: str,
    user_id: str,
    xsec_token: str = "",
    xsec_source: str = "pc_feed",
    crawl_interval: float = 1.0,
    callback: Any = None,
) -> list[dict[str, Any]]:
    client = await get_client(page=page, cookie_header=cookie_header)
    try:
        data_obj = await client.get_all_notes_by_creator(
            user_id=user_id,
            xsec_token=xsec_token,
            xsec_source=xsec_source,
            crawl_interval=crawl_interval,
            callback=callback,
        )
    except Exception as exc:
        raise to_api_error("all_creator_notes", exc) from exc
    return [x for x in data_obj if isinstance(x, dict)] if isinstance(data_obj, list) else []


async def get_note_short_url(*, page, cookie_header: str, note_id: str) -> dict[str, Any]:
    client = await get_client(page=page, cookie_header=cookie_header)
    try:
        data_obj = await client.get_note_short_url(note_id=note_id)
    except Exception as exc:
        raise to_api_error("short_url", exc) from exc
    return data_obj if isinstance(data_obj, dict) else {}


async def get_note_by_id_from_html(
    *,
    page,
    cookie_header: str,
    note_id: str,
    xsec_source: str,
    xsec_token: str,
    enable_cookie: bool = False,
) -> dict[str, Any] | None:
    client = await get_client(page=page, cookie_header=cookie_header)
    try:
        return await client.get_note_by_id_from_html(
            note_id=note_id,
            xsec_source=xsec_source,
            xsec_token=xsec_token,
            enable_cookie=enable_cookie,
        )
    except Exception as exc:
        raise to_api_error("note_detail_html", exc) from exc
