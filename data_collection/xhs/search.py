"""XHS keyword search API wrapper with pagination and rate limiting."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from data_collection.utils.rate_limit import RateLimiter
from data_collection.xhs.item_parser import extract_item_id
from data_collection.xhs.mc_api import XhsApiError, get_note_by_keyword, get_search_id_via_api
from data_collection.xhs.session import run_with_xhs_session

PING_KEYWORD = "Xiaohongshu"
logger = logging.getLogger(__name__)

get_search_id = get_search_id_via_api


@dataclass(slots=True)
class XhsSearchResult:
    keyword: str
    start_page: int
    pages: int
    page_size: int
    sort: str
    note_type: int
    items: list[dict[str, Any]]


class XhsSearchError(RuntimeError):
    def __init__(self, code: int | None, msg: str | None):
        self.code = code
        self.msg = msg or "unknown error"
        super().__init__(f"XHS search failed: code={self.code}, msg={self.msg}")


async def _request_search_page(
    *,
    page,
    cookie_header: str,
    a1: str,
    keyword: str,
    page_no: int,
    page_size: int,
    search_id: str,
    sort: str,
    note_type: int,
    debug: bool,
) -> dict[str, Any]:
    try:
        data_obj = await get_note_by_keyword(
            page=page,
            cookie_header=cookie_header,
            keyword=keyword,
            page_no=page_no,
            page_size=page_size,
            search_id=search_id,
            sort=sort,
            note_type=note_type,
        )
    except XhsApiError as exc:
        raise XhsSearchError(code=exc.code, msg=exc.msg) from exc
    if debug:
        items = data_obj.get("items") if isinstance(data_obj, dict) else []
        items_len = len(items) if isinstance(items, list) else 0
        logger.info(
            "[xhs_search] keyword=%s page=%s via=mediacrawler items_len=%s",
            keyword,
            page_no,
            items_len,
        )
    return data_obj


async def _pong_login_state(
    *,
    page,
    cookie_header: str,
    a1: str,
    debug: bool,
) -> None:
    search_id = get_search_id()
    data_obj = await _request_search_page(
        page=page,
        cookie_header=cookie_header,
        a1=a1,
        keyword=PING_KEYWORD,
        page_no=1,
        page_size=5,
        search_id=search_id,
        sort="general",
        note_type=0,
        debug=debug,
    )
    items = data_obj.get("items", [])
    if debug:
        if isinstance(items, list) and len(items) > 0:
            logger.info(f"[xhs_search] pong check passed with {len(items)} probe items.")
        else:
            logger.warning("[xhs_search] pong check got code=0 but probe items are empty.")


async def search_keyword_async(
    *,
    keyword: str,
    pages: int,
    start_page: int,
    page_size: int,
    sort: str,
    note_type: int,
    delay: float,
    max_rps: float,
    login_timeout_sec: int,
    post_login_wait_sec: float,
    session_profile_dir: Path | None,
    force_qrcode: bool,
    hold_browser_on_error: bool,
    debug: bool,
) -> XhsSearchResult:
    keyword = keyword.strip()
    if not keyword:
        raise ValueError("keyword is required")
    if pages <= 0:
        raise ValueError("pages must be > 0")
    if page_size <= 0:
        raise ValueError("page_size must be > 0")
    if sort not in {"general", "time_descending", "popularity_descending"}:
        raise ValueError("sort must be one of: general, time_descending, popularity_descending")
    if note_type not in {0, 1, 2}:
        raise ValueError("note_type must be one of: 0(all), 1(video), 2(image)")

    limiter = RateLimiter(max_rps)
    search_id = get_search_id()
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    async def _worker(session):
        page = session.page
        cookie_header = session.cookie_header
        a1 = session.a1
        await _pong_login_state(page=page, cookie_header=cookie_header, a1=a1, debug=debug)

        for idx in range(pages):
            await limiter.wait_async()
            page_no = start_page + idx
            data_obj = await _request_search_page(
                page=page,
                cookie_header=cookie_header,
                a1=a1,
                keyword=keyword,
                page_no=page_no,
                page_size=page_size,
                search_id=search_id,
                sort=sort,
                note_type=note_type,
                debug=debug,
            )
            page_items = data_obj.get("items", [])
            if isinstance(page_items, list):
                for item in page_items:
                    note_id = extract_item_id(item)
                    if note_id and note_id in seen:
                        continue
                    if note_id:
                        seen.add(note_id)
                    items.append(item)
            if data_obj.get("has_more") is False:
                break
            if delay > 0:
                await asyncio.sleep(delay)
        return None

    await run_with_xhs_session(
        login_timeout_sec=login_timeout_sec,
        post_login_wait_sec=post_login_wait_sec,
        session_profile_dir=session_profile_dir,
        force_qrcode=force_qrcode,
        debug=debug,
        worker=_worker,
        hold_browser_on_error=hold_browser_on_error,
    )

    return XhsSearchResult(
        keyword=keyword,
        start_page=start_page,
        pages=pages,
        page_size=page_size,
        sort=sort,
        note_type=note_type,
        items=items,
    )


def search_keyword(
    *,
    keyword: str,
    pages: int,
    start_page: int = 1,
    page_size: int = 20,
    sort: str = "general",
    note_type: int = 0,
    delay: float = 0.0,
    max_rps: float = 0.5,
    login_timeout_sec: int = 180,
    post_login_wait_sec: float = 2.0,
    session_profile_dir: Path | None = None,
    force_qrcode: bool = False,
    hold_browser_on_error: bool = False,
    debug: bool = False,
    out: Path | None = None,
) -> XhsSearchResult:
    if hold_browser_on_error and not debug:
        logger.warning("[xhs_search] --hold-browser-on-error is ignored unless --debug is enabled.")
        hold_browser_on_error = False

    result = asyncio.run(
        search_keyword_async(
            keyword=keyword,
            pages=pages,
            start_page=start_page,
            page_size=page_size,
            sort=sort,
            note_type=note_type,
            delay=delay,
            max_rps=max_rps,
            login_timeout_sec=login_timeout_sec,
            post_login_wait_sec=post_login_wait_sec,
            session_profile_dir=session_profile_dir,
            force_qrcode=force_qrcode,
            hold_browser_on_error=hold_browser_on_error,
            debug=debug,
        )
    )

    if out is not None:
        payload = {
            "keyword": result.keyword,
            "start_page": result.start_page,
            "pages": result.pages,
            "page_size": result.page_size,
            "sort": result.sort,
            "note_type": result.note_type,
            "items": result.items,
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return result
