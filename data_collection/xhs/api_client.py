"""Reusable async XHS API client with built-in throttling and session management."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from data_collection.xhs.mc_api._client import get_search_id_via_api
from data_collection.xhs.mc_api._errors import (
    XhsApiError,
    to_api_error,
)
from data_collection.xhs.mc_api._headers import (
    build_headers,
    cookie_header_to_dict,
)
from data_collection.xhs.mc_api._symbols import (
    load_symbols,
)
from data_collection.xhs.request_utils import RequestThrottleConfig, XhsRequestThrottler
from data_collection.xhs.session import open_xhs_api_session

logger = logging.getLogger(__name__)


class XhsApiClient:
    """Async XHS API client backed by MediaCrawler's signed HTTP transport."""

    def __init__(
        self,
        *,
        throttle_config: RequestThrottleConfig | None = None,
        login_timeout_sec: int = 180,
        post_login_wait_sec: float = 2.0,
        session_profile_dir: Path | None = None,
        force_qrcode: bool = False,
        nologin: bool = False,
        debug: bool = False,
    ) -> None:
        self._throttle_cfg = throttle_config or RequestThrottleConfig()
        self._login_timeout_sec = login_timeout_sec
        self._post_login_wait_sec = post_login_wait_sec
        self._session_profile_dir = session_profile_dir
        self._force_qrcode = force_qrcode
        self._nologin = nologin
        self._debug = debug

        self._session: Any = None
        self._client: Any = None
        self._throttler: XhsRequestThrottler | None = None

    async def __aenter__(self) -> XhsApiClient:
        self._session = await open_xhs_api_session(
            login_timeout_sec=self._login_timeout_sec,
            post_login_wait_sec=self._post_login_wait_sec,
            session_profile_dir=self._session_profile_dir,
            force_qrcode=self._force_qrcode,
            nologin=self._nologin,
            debug=self._debug,
        )
        XiaoHongShuClient, _, _, _ = load_symbols()
        self._client = XiaoHongShuClient(
            proxy=None,
            headers=build_headers(self._session.cookie_header),
            playwright_page=self._session.page,
            cookie_dict=cookie_header_to_dict(self._session.cookie_header),
            proxy_ip_pool=None,
        )
        self._throttler = XhsRequestThrottler(self._throttle_cfg)
        logger.info("[api_client] session opened, client ready")
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
        self._client = None
        logger.info("[api_client] session closed")

    @property
    def throttler(self) -> XhsRequestThrottler:
        assert self._throttler is not None, "client not initialized (use `async with`)"
        return self._throttler

    @property
    def page(self) -> Any:
        assert self._session is not None, "client not initialized (use `async with`)"
        return self._session.page

    @property
    def cookie_header(self) -> str:
        assert self._session is not None, "client not initialized (use `async with`)"
        return self._session.cookie_header

    def _require_client(self) -> Any:
        if self._client is None:
            raise RuntimeError("XhsApiClient not initialized — use `async with` context manager")
        return self._client

    async def search_notes(
        self,
        keyword: str,
        *,
        page: int = 1,
        page_size: int = 20,
        search_id: str = "",
        sort: str = "general",
        note_type: int = 0,
    ) -> dict[str, Any]:
        client = self._require_client()
        await self.throttler.throttle("search")

        if not search_id:
            search_id = get_search_id_via_api()

        _, SearchSortType, SearchNoteType, _ = load_symbols()
        sort_enum = SearchSortType(sort) if isinstance(sort, str) else sort
        note_type_enum = SearchNoteType(note_type) if isinstance(note_type, int) else note_type

        try:
            return await client.get_note_by_keyword(
                keyword=keyword,
                search_id=search_id,
                page=page,
                page_size=page_size,
                sort=sort_enum,
                note_type=note_type_enum,
            )
        except XhsApiError:
            raise
        except Exception as exc:
            raise to_api_error("search_notes", exc) from exc

    async def get_note_detail(
        self,
        note_id: str,
        xsec_token: str,
        *,
        xsec_source: str = "pc_search",
    ) -> dict[str, Any]:
        client = self._require_client()
        await self.throttler.throttle("detail")

        try:
            return await client.get_note_by_id(
                note_id=note_id,
                xsec_source=xsec_source,
                xsec_token=xsec_token,
            )
        except XhsApiError:
            raise
        except Exception as exc:
            raise to_api_error("get_note_detail", exc) from exc

    async def get_comments(
        self,
        note_id: str,
        xsec_token: str,
        *,
        cursor: str = "",
    ) -> dict[str, Any]:
        client = self._require_client()
        await self.throttler.throttle("comment")

        try:
            return await client.get_note_comments(
                note_id=note_id,
                xsec_token=xsec_token,
                cursor=cursor,
            )
        except XhsApiError:
            raise
        except Exception as exc:
            raise to_api_error("get_comments", exc) from exc

    async def get_all_comments(
        self,
        note_id: str,
        xsec_token: str,
        *,
        max_count: int = 100,
        include_sub: bool = True,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        has_more = True
        cursor = ""

        while has_more and len(result) < max_count:
            try:
                page_data = await self.get_comments(note_id, xsec_token, cursor=cursor)
            except Exception as exc:
                cooldown = await self.throttler.handle_comment_rate_limit(exc)
                if cooldown > 0:
                    continue
                logger.warning("[api_client] get_all_comments error note=%s: %s", note_id, exc)
                break

            self.throttler.comment_streak.record_success()

            has_more = bool(page_data.get("has_more", False))
            cursor = page_data.get("cursor", "")
            comments = page_data.get("comments")
            if not isinstance(comments, list) or not comments:
                break

            remaining = max_count - len(result)
            if len(comments) > remaining:
                comments = comments[:remaining]

            result.extend(comments)

            if include_sub:
                for comment in comments:
                    if len(result) >= max_count:
                        break
                    sub_comments_inline = comment.get("sub_comments")
                    if isinstance(sub_comments_inline, list) and sub_comments_inline:
                        sub_remaining = max_count - len(result)
                        result.extend(sub_comments_inline[:sub_remaining])

                    if not comment.get("sub_comment_has_more"):
                        continue
                    root_id = comment.get("id", "")
                    sub_cursor = comment.get("sub_comment_cursor", "")
                    sub_has_more = True
                    while sub_has_more and len(result) < max_count:
                        try:
                            sub_data = await self.get_sub_comments(
                                note_id=note_id,
                                root_comment_id=root_id,
                                xsec_token=xsec_token,
                                cursor=sub_cursor,
                            )
                        except Exception as sub_exc:
                            logger.warning(
                                "[api_client] sub_comment error note=%s root=%s: %s",
                                note_id,
                                root_id,
                                sub_exc,
                            )
                            break
                        sub_has_more = bool(sub_data.get("has_more", False))
                        sub_cursor = sub_data.get("cursor", "")
                        sub_list = sub_data.get("comments")
                        if not isinstance(sub_list, list) or not sub_list:
                            break
                        sub_remaining = max_count - len(result)
                        result.extend(sub_list[:sub_remaining])

        return result

    async def get_sub_comments(
        self,
        note_id: str,
        root_comment_id: str,
        xsec_token: str,
        *,
        num: int = 10,
        cursor: str = "",
    ) -> dict[str, Any]:
        client = self._require_client()
        await self.throttler.throttle("comment")

        try:
            return await client.get_note_sub_comments(
                note_id=note_id,
                root_comment_id=root_comment_id,
                xsec_token=xsec_token,
                num=num,
                cursor=cursor,
            )
        except XhsApiError:
            raise
        except Exception as exc:
            raise to_api_error("get_sub_comments", exc) from exc

    async def ping(self) -> bool:
        try:
            data = await self.search_notes("Xiaohongshu", page_size=5)
            items = data.get("items")
            return isinstance(items, list) and len(items) > 0
        except Exception as exc:
            logger.warning("[api_client] ping failed: %s", exc)
            return False
