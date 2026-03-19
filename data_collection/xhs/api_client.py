"""Reusable async XHS API client with built-in throttling and session management."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from data_collection.utils.debug_snapshot import save_snapshot
from data_collection.xhs.mc_api._client import get_search_id_via_api
from data_collection.xhs.mc_api._dom import (
    ensure_logged_in_or_raise,
    try_clear_page_popup,
)
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

VERIFICATION_POLL_SEC = 3.0
VERIFICATION_TIMEOUT_SEC = 120.0

logger = logging.getLogger(__name__)

_AUTH_RETRY_CODES = {-100, -101, -104}


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

    async def _open_session(self, *, force_qrcode: bool = False) -> None:
        """Open a browser session and initialize the API client."""
        self._session = await open_xhs_api_session(
            login_timeout_sec=self._login_timeout_sec,
            post_login_wait_sec=self._post_login_wait_sec,
            session_profile_dir=self._session_profile_dir,
            force_qrcode=force_qrcode or self._force_qrcode,
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

    async def _close_session(self) -> None:
        """Close the current browser session."""
        if self._session is not None:
            await self._session.close()
            self._session = None
        self._client = None

    async def _relogin(self) -> None:
        """Close expired session and re-open with forced QR code login."""
        logger.warning("[api_client] session expired, triggering re-login with QR code...")
        await self._close_session()
        await self._open_session(force_qrcode=True)
        logger.info("[api_client] re-login successful, session refreshed")

    async def __aenter__(self) -> XhsApiClient:
        await self._open_session()
        self._throttler = XhsRequestThrottler(self._throttle_cfg)
        logger.info("[api_client] session opened, client ready")

        # Verify session is actually valid; re-login if expired
        if not self._nologin and not await self.ping():
            logger.warning("[api_client] session invalid after open, attempting re-login")
            await self._snapshot(
                trigger="session_invalid_on_open",
                error="ping failed after session open",
                phase="aenter_ping",
            )
            await self._relogin()
            if not await self.ping():
                logger.error("[api_client] re-login failed, session still invalid")
                await self._snapshot(
                    trigger="relogin_ping_failed",
                    error="ping still fails after re-login",
                    phase="aenter_relogin",
                )

        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self._close_session()
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

    async def _check_page_state(self, *, endpoint: str, phase: str) -> None:
        """Check the browser page for verification modals or login prompts.

        Raises XhsApiError if verification/login is required.
        """
        if self._session is None:
            return
        await ensure_logged_in_or_raise(
            page=self._session.page,
            endpoint=endpoint,
            phase=phase,
        )

    async def _wait_for_verification(self, exc: XhsApiError) -> bool:
        """Wait for user to solve a secondary verification (captcha/QR).

        Polls the page until the verification modal disappears or timeout.
        Returns True if verification was resolved, False if timed out.
        """
        import asyncio
        import time

        payload = exc.payload if isinstance(exc.payload, dict) else {}
        is_verify_modal = payload.get("verify_modal") or payload.get("verification_modal")
        if not is_verify_modal or self._session is None:
            return False

        page = self._session.page
        logger.warning(
            "[api_client] secondary verification required — "
            "please scan the QR code in the browser window (timeout=%ds)",
            int(VERIFICATION_TIMEOUT_SEC),
        )

        await self._snapshot(
            trigger="verification_required",
            error=exc,
            endpoint=payload.get("endpoint", ""),
            phase="verification_start",
        )

        deadline = time.monotonic() + VERIFICATION_TIMEOUT_SEC
        while time.monotonic() < deadline:
            await asyncio.sleep(VERIFICATION_POLL_SEC)
            try:
                await ensure_logged_in_or_raise(
                    page=page,
                    endpoint="verify_check",
                    phase="wait",
                )
                # No exception → verification resolved
                logger.info("[api_client] verification resolved, resuming operations")
                # Try to close any remaining popups
                await try_clear_page_popup(page)
                return True
            except XhsApiError as check_exc:
                check_payload = check_exc.payload if isinstance(check_exc.payload, dict) else {}
                if check_payload.get("verify_modal"):
                    remaining = int(deadline - time.monotonic())
                    if remaining > 0 and remaining % 15 < VERIFICATION_POLL_SEC:
                        logger.info(
                            "[api_client] still waiting for verification... %ds remaining",
                            remaining,
                        )
                    continue
                # Different error (e.g. login_ui) — stop waiting
                return False

        logger.error("[api_client] verification timeout after %ds", int(VERIFICATION_TIMEOUT_SEC))
        await self._snapshot(
            trigger="verification_timeout",
            error=exc,
            phase="verification_timeout",
        )
        return False

    async def _snapshot(
        self,
        trigger: str,
        error: Exception | str | None = None,
        *,
        endpoint: str = "",
        phase: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Capture a debug snapshot of the current browser state."""
        page = self._session.page if self._session else None
        await save_snapshot(
            page=page,
            trigger=trigger,
            error=error,
            endpoint=endpoint,
            phase=phase,
            extra=extra,
        )

    async def _handle_api_error(self, exc: XhsApiError, *, endpoint: str) -> bool:
        """Handle auth/verification errors. Returns True if recovered and caller should retry."""
        payload = exc.payload if isinstance(exc.payload, dict) else {}

        # Snapshot on every unexpected error
        await self._snapshot(
            trigger=f"api_error_{exc.code or 'unknown'}",
            error=exc,
            endpoint=endpoint,
            phase="handle_error",
            extra={"payload": payload},
        )

        # Secondary verification modal — wait for user to scan QR
        if payload.get("verify_modal") or payload.get("verification_modal"):
            return await self._wait_for_verification(exc)

        # Session expired — try re-login
        if exc.code in _AUTH_RETRY_CODES and not self._nologin:
            logger.warning(
                "[api_client] auth error code=%s on %s, attempting re-login", exc.code, endpoint
            )
            try:
                await self._relogin()
                return True
            except Exception as relogin_exc:
                logger.error("[api_client] re-login failed: %s", relogin_exc)
                await self._snapshot(
                    trigger="relogin_failed",
                    error=relogin_exc,
                    endpoint=endpoint,
                    phase="relogin",
                )
                return False

        return False

    async def _call_with_recovery(
        self,
        endpoint: str,
        fn: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Call an API function with page-state check, error conversion, and auto-recovery.

        On auth/verification errors: takes a debug snapshot, attempts recovery
        (verification wait or re-login), then retries once.
        """
        await self._check_page_state(endpoint=endpoint, phase=f"before_{endpoint}")
        try:
            return await fn(*args, **kwargs)
        except XhsApiError:
            raise
        except Exception as exc:
            raise to_api_error(endpoint, exc) from exc

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

        call_kwargs = dict(
            keyword=keyword,
            search_id=search_id,
            page=page,
            page_size=page_size,
            sort=sort_enum,
            note_type=note_type_enum,
        )
        try:
            return await self._call_with_recovery(
                "search",
                client.get_note_by_keyword,
                **call_kwargs,
            )
        except XhsApiError as exc:
            if await self._handle_api_error(exc, endpoint="search"):
                return await client.get_note_by_keyword(**call_kwargs)
            raise

    async def get_note_detail(
        self,
        note_id: str,
        xsec_token: str,
        *,
        xsec_source: str = "pc_search",
    ) -> dict[str, Any]:
        client = self._require_client()
        await self.throttler.throttle("detail")

        call_kwargs = dict(
            note_id=note_id,
            xsec_source=xsec_source,
            xsec_token=xsec_token,
        )
        try:
            return await self._call_with_recovery(
                "detail",
                client.get_note_by_id,
                **call_kwargs,
            )
        except XhsApiError as exc:
            if await self._handle_api_error(exc, endpoint="detail"):
                return await client.get_note_by_id(**call_kwargs)
            raise

    async def get_comments(
        self,
        note_id: str,
        xsec_token: str,
        *,
        cursor: str = "",
    ) -> dict[str, Any]:
        client = self._require_client()
        await self.throttler.throttle("comment")

        call_kwargs = dict(
            note_id=note_id,
            xsec_token=xsec_token,
            cursor=cursor,
        )
        try:
            return await self._call_with_recovery(
                "comment",
                client.get_note_comments,
                **call_kwargs,
            )
        except XhsApiError as exc:
            if await self._handle_api_error(exc, endpoint="comment"):
                return await client.get_note_comments(**call_kwargs)
            raise

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

        call_kwargs = dict(
            note_id=note_id,
            root_comment_id=root_comment_id,
            xsec_token=xsec_token,
            num=num,
            cursor=cursor,
        )
        try:
            return await self._call_with_recovery(
                "sub_comment",
                client.get_note_sub_comments,
                **call_kwargs,
            )
        except XhsApiError as exc:
            if await self._handle_api_error(exc, endpoint="sub_comment"):
                return await client.get_note_sub_comments(**call_kwargs)
            raise

    async def ping(self) -> bool:
        """Lightweight session check — raw API call, no page guards or recovery.

        Returns True if the API responds with valid data (even empty results).
        Returns False only if the API returns an auth error code.
        """
        client = self._require_client()
        try:
            search_id = get_search_id_via_api()
            _, SearchSortType, SearchNoteType, _ = load_symbols()
            data = await client.get_note_by_keyword(
                keyword="test",
                search_id=search_id,
                page=1,
                page_size=5,
                sort=SearchSortType("general"),
                note_type=SearchNoteType(0),
            )
            # Any valid response (even empty items) means session works
            return isinstance(data, dict)
        except Exception as exc:
            code = getattr(exc, "code", None)
            msg = str(exc).lower()
            # Only treat auth errors as ping failure
            if code in _AUTH_RETRY_CODES or "登录" in msg or "login" in msg:
                logger.warning("[api_client] ping failed (auth): %s", exc)
                return False
            # Non-auth errors (rate limit, network, etc.) — session is likely fine
            logger.debug("[api_client] ping non-auth error (session OK): %s", exc)
            return True
