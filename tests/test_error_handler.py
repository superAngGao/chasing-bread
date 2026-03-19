"""Tests for error classification and recovery actions."""

from __future__ import annotations

import pytest

from data_collection.xhs.error_handler import (
    AbortError,
    ErrorType,
    RecoveryAction,
    ReLoginRequiredError,
    XhsErrorHandler,
)
from data_collection.xhs.mc_api._errors import XhsApiError


@pytest.fixture
def handler():
    return XhsErrorHandler()


class TestClassify:
    def test_auth_invalid_by_code(self, handler):
        exc = XhsApiError(endpoint="test", code=-100, msg="", payload=None)
        assert handler.classify(exc) == ErrorType.AUTH_INVALID

    def test_auth_invalid_by_msg(self, handler):
        exc = XhsApiError(endpoint="test", code=-101, msg="请登录", payload=None)
        assert handler.classify(exc) == ErrorType.AUTH_INVALID

    def test_rate_limit(self, handler):
        exc = XhsApiError(endpoint="test", code=300012, msg="", payload=None)
        result = handler.classify(exc)
        assert result == ErrorType.RATE_LIMIT

    def test_network_error(self, handler):
        assert handler.classify("Connection timeout") == ErrorType.NETWORK_ERROR

    def test_note_abnormal_by_code(self, handler):
        exc = XhsApiError(endpoint="test", code=-510001, msg="", payload=None)
        assert handler.classify(exc) == ErrorType.NOTE_ABNORMAL

    def test_unknown_error(self, handler):
        assert handler.classify("something random happened") == ErrorType.UNKNOWN

    def test_integer_input(self, handler):
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
        await handler.execute_recovery(RecoveryAction.SKIP, 0.0, "test")

    @pytest.mark.asyncio
    async def test_retry_immediately(self, handler):
        await handler.execute_recovery(RecoveryAction.RETRY_IMMEDIATELY, 0.0, "test")
