"""Tests for the shared login/session module public API.

These tests verify the public interface and mock Playwright to avoid
requiring an actual browser. Integration tests that launch a real
browser should be in a separate test file with appropriate markers.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

# Test the public API surface
from data_collection.xhs import (
    QrcodeAuthSession,
    XhsApiClient,
    open_session,
    run_with_session,
)
from data_collection.xhs.api_client import _AUTH_RETRY_CODES
from data_collection.xhs.mc_api._errors import XhsApiError
from data_collection.xhs.session import (
    _wait_for_signing_ready,
    get_exception_code,
    should_force_qrcode_retry,
)


class TestPublicAPIExports:
    """Verify the shared login module exports the right symbols."""

    def test_open_session_is_callable(self):
        assert callable(open_session)

    def test_run_with_session_is_callable(self):
        assert callable(run_with_session)

    def test_xhs_api_client_is_class(self):
        assert isinstance(XhsApiClient, type)

    def test_qrcode_auth_session_is_dataclass(self):
        assert hasattr(QrcodeAuthSession, "__dataclass_fields__")


class TestGetExceptionCode:
    def test_with_code_attr(self):
        exc = Exception("test")
        exc.code = -100
        assert get_exception_code(exc) == -100

    def test_without_code_attr(self):
        assert get_exception_code(Exception("test")) is None

    def test_non_int_code(self):
        exc = Exception("test")
        exc.code = "not_an_int"
        assert get_exception_code(exc) is None


class TestShouldForceQrcodeRetry:
    def test_auth_error_triggers_retry(self):
        exc = Exception("login required")
        exc.code = -100
        assert should_force_qrcode_retry(exc, force_qrcode=False) is True

    def test_other_error_no_retry(self):
        exc = Exception("some error")
        exc.code = 500
        assert should_force_qrcode_retry(exc, force_qrcode=False) is False

    def test_already_forced_no_retry(self):
        exc = Exception("login required")
        exc.code = -100
        assert should_force_qrcode_retry(exc, force_qrcode=True) is False

    def test_all_auth_codes(self):
        for code in (-100, -101, -104):
            exc = Exception(f"auth error {code}")
            exc.code = code
            assert should_force_qrcode_retry(exc, force_qrcode=False) is True


class TestWaitForSigningReady:
    @pytest.mark.asyncio
    async def test_ready_immediately(self):
        page = AsyncMock()
        page.evaluate = AsyncMock(return_value=True)
        result = await _wait_for_signing_ready(page=page, timeout_sec=5.0, debug=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_not_ready_timeout(self):
        page = AsyncMock()
        page.evaluate = AsyncMock(return_value=False)
        result = await _wait_for_signing_ready(page=page, timeout_sec=1.0, debug=False)
        assert result is False

    @pytest.mark.asyncio
    async def test_evaluate_exception(self):
        page = AsyncMock()
        page.evaluate = AsyncMock(side_effect=Exception("page closed"))
        result = await _wait_for_signing_ready(page=page, timeout_sec=1.0, debug=False)
        assert result is False


class TestQrcodeAuthSession:
    @pytest.mark.asyncio
    async def test_close(self):
        pw = AsyncMock()
        browser = AsyncMock()
        context = AsyncMock()
        page = MagicMock()

        session = QrcodeAuthSession(
            playwright=pw,
            browser=browser,
            context=context,
            page=page,
            cookie_header="a1=abc; id_token=xyz",
            a1="abc",
        )
        await session.close()
        context.close.assert_awaited_once()
        browser.close.assert_awaited_once()
        pw.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_without_browser(self):
        pw = AsyncMock()
        context = AsyncMock()

        session = QrcodeAuthSession(
            playwright=pw,
            browser=None,
            context=context,
            page=MagicMock(),
            cookie_header="a1=abc",
            a1="abc",
        )
        await session.close()
        context.close.assert_awaited_once()
        pw.stop.assert_awaited_once()


class TestHandleApiError:
    """Test the XhsApiClient error handling for auth and verification errors."""

    @pytest.fixture(autouse=True)
    def _isolate_snapshots(self, tmp_path, monkeypatch):
        """Prevent tests from writing snapshots to data/debug/."""
        monkeypatch.setattr(
            "data_collection.utils.debug_snapshot._DEBUG_DIR", tmp_path,
        )

    def _make_client(self) -> XhsApiClient:
        return XhsApiClient(nologin=True, debug=False)

    @pytest.mark.asyncio
    async def test_verification_modal_detected(self):
        client = self._make_client()
        client._session = MagicMock()
        exc = XhsApiError(
            endpoint="comment",
            code=300012,
            msg="请通过验证",
            payload={"verify_modal": True},
        )
        # _wait_for_verification will try to poll — mock it to return True
        client._wait_for_verification = AsyncMock(return_value=True)
        result = await client._handle_api_error(exc, endpoint="comment")
        assert result is True
        client._wait_for_verification.assert_awaited_once_with(exc)

    @pytest.mark.asyncio
    async def test_auth_error_in_nologin_mode(self):
        client = self._make_client()
        client._session = MagicMock()
        exc = XhsApiError(
            endpoint="search",
            code=-100,
            msg="登录已过期",
            payload={},
        )
        # nologin=True → should NOT attempt re-login
        result = await client._handle_api_error(exc, endpoint="search")
        assert result is False

    @pytest.mark.asyncio
    async def test_auth_error_triggers_relogin(self):
        client = XhsApiClient(nologin=False, debug=False)
        client._session = MagicMock()
        client._relogin = AsyncMock()
        exc = XhsApiError(
            endpoint="search",
            code=-100,
            msg="登录已过期",
            payload={},
        )
        result = await client._handle_api_error(exc, endpoint="search")
        assert result is True
        client._relogin.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_auth_error_not_handled(self):
        client = self._make_client()
        client._session = MagicMock()
        exc = XhsApiError(
            endpoint="search",
            code=-510001,
            msg="note status abnormal",
            payload={},
        )
        result = await client._handle_api_error(exc, endpoint="search")
        assert result is False

    def test_auth_retry_codes(self):
        assert -100 in _AUTH_RETRY_CODES
        assert -101 in _AUTH_RETRY_CODES
        assert -104 in _AUTH_RETRY_CODES
