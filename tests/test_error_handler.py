from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

# Mock mc_api before importing error_handler to avoid dependency on vendor/MediaCrawler
import sys

_mock_mc_api = MagicMock()


class _FakeXhsApiError(Exception):
    def __init__(self, code=None, msg=""):
        self.code = code
        self.msg = msg


_mock_mc_api.XhsApiError = _FakeXhsApiError
_mock_mc_api.is_account_state_error = lambda code, msg: code in {-100, -101, -104, 300012} or "登录" in (msg or "")

sys.modules.setdefault("data_collection.xhs.mc_api", _mock_mc_api)

from data_collection.xhs.error_handler import (
    ErrorType,
    RecoveryAction,
    XhsErrorHandler,
    ReLoginRequiredError,
    AbortError,
)


@pytest.fixture
def handler():
    return XhsErrorHandler()


class TestClassify:
    def test_auth_invalid_by_code(self, handler):
        exc = _mock_mc_api.XhsApiError(code=-100, msg="")
        assert handler.classify(exc) == ErrorType.AUTH_INVALID

    def test_auth_invalid_by_msg(self, handler):
        exc = _mock_mc_api.XhsApiError(code=-101, msg="请登录")
        assert handler.classify(exc) == ErrorType.AUTH_INVALID

    def test_rate_limit(self, handler):
        # 300012 is in is_account_state_error mock but not in auth codes
        # Actually our mock returns True for 300012, but classify checks
        # is_account_state_error first, then auth codes. 300012 is not in {-100,-101,-104}
        # and "登录" is not in msg, so it falls to RATE_LIMIT
        exc = _mock_mc_api.XhsApiError(code=300012, msg="")
        result = handler.classify(exc)
        # 300012 passes is_account_state_error, not in auth codes -> RATE_LIMIT
        assert result == ErrorType.RATE_LIMIT

    def test_network_error(self, handler):
        assert handler.classify("Connection timeout") == ErrorType.NETWORK_ERROR

    def test_note_abnormal_by_code(self, handler):
        exc = _mock_mc_api.XhsApiError(code=-510001, msg="")
        assert handler.classify(exc) == ErrorType.NOTE_ABNORMAL

    def test_unknown_error(self, handler):
        assert handler.classify("something random happened") == ErrorType.UNKNOWN

    def test_integer_input(self, handler):
        # -100 is in is_account_state_error -> auth codes -> AUTH_INVALID
        assert handler.classify(-100) == ErrorType.AUTH_INVALID


class TestDetermineAction:
    def test_rate_limit_action(self, handler):
        action, wait = handler.determine_action(ErrorType.RATE_LIMIT, attempt=1)
        assert action == RecoveryAction.LONG_SLEEP
        assert wait == 120

    def test_rate_limit_backoff(self, handler):
        _, wait1 = handler.determine_action(ErrorType.RATE_LIMIT, attempt=1)
        _, wait2 = handler.determine_action(ErrorType.RATE_LIMIT, attempt=2)
        assert wait2 > wait1

    def test_rate_limit_max_cap(self, handler):
        _, wait = handler.determine_action(ErrorType.RATE_LIMIT, attempt=10)
        assert wait <= 600

    def test_auth_invalid_action(self, handler):
        action, _ = handler.determine_action(ErrorType.AUTH_INVALID)
        assert action == RecoveryAction.RELOGIN

    def test_ip_block_action(self, handler):
        action, wait = handler.determine_action(ErrorType.IP_BLOCK)
        assert action == RecoveryAction.RETRY_WITH_BACKOFF
        assert wait == 10.0

    def test_network_error_action(self, handler):
        action, _ = handler.determine_action(ErrorType.NETWORK_ERROR, attempt=3)
        assert action == RecoveryAction.RETRY_WITH_BACKOFF

    def test_note_abnormal_skip(self, handler):
        action, _ = handler.determine_action(ErrorType.NOTE_ABNORMAL)
        assert action == RecoveryAction.SKIP

    def test_unknown_abort(self, handler):
        action, _ = handler.determine_action(ErrorType.UNKNOWN)
        assert action == RecoveryAction.ABORT


class TestExecuteRecovery:
    @pytest.mark.asyncio
    async def test_relogin_raises(self, handler):
        with pytest.raises(ReLoginRequiredError):
            await handler.execute_recovery(RecoveryAction.RELOGIN, 0.0, "test")

    @pytest.mark.asyncio
    async def test_abort_raises(self, handler):
        with pytest.raises(AbortError):
            await handler.execute_recovery(RecoveryAction.ABORT, 0.0, "test")

    @pytest.mark.asyncio
    async def test_skip_no_exception(self, handler):
        # SKIP should not raise
        await handler.execute_recovery(RecoveryAction.SKIP, 0.0, "test")

    @pytest.mark.asyncio
    async def test_retry_immediately(self, handler):
        # Should complete instantly without error
        await handler.execute_recovery(RecoveryAction.RETRY_IMMEDIATELY, 0.0, "test")
