"""Tests for rate limiting, throttling, and error handling."""

from __future__ import annotations

import time

import pytest

from data_collection.utils.rate_limit import RateLimiter
from data_collection.xhs.error_handler import (
    ErrorType,
    RecoveryAction,
    XhsErrorHandler,
)
from data_collection.xhs.mc_api import XhsApiError
from data_collection.xhs.request_utils import (
    FailureStreakTracker,
    RequestThrottleConfig,
    XhsRequestThrottler,
)


class TestRateLimiter:
    def test_sync_wait(self):
        limiter = RateLimiter(max_rps=10.0)
        # First call should not block
        limiter.wait_sync()
        t0 = time.monotonic()
        limiter.wait_sync()
        elapsed = time.monotonic() - t0
        assert elapsed >= 0.09  # ~100ms interval for 10 RPS

    @pytest.mark.asyncio
    async def test_async_wait(self):
        limiter = RateLimiter(max_rps=10.0)
        await limiter.wait_async()
        t0 = time.monotonic()
        await limiter.wait_async()
        elapsed = time.monotonic() - t0
        assert elapsed >= 0.09


class TestFailureStreakTracker:
    def test_no_cooldown_below_threshold(self):
        tracker = FailureStreakTracker(
            streak_threshold=3,
            cooldown_base_sec=10.0,
            cooldown_max_sec=100.0,
        )
        assert tracker.record_failure() == 0.0
        assert tracker.record_failure() == 0.0

    def test_cooldown_at_threshold(self):
        tracker = FailureStreakTracker(
            streak_threshold=3,
            cooldown_base_sec=10.0,
            cooldown_max_sec=100.0,
        )
        tracker.record_failure()
        tracker.record_failure()
        cooldown = tracker.record_failure()  # hits threshold
        assert cooldown == 10.0  # base * 2^0

    def test_cooldown_escalation(self):
        tracker = FailureStreakTracker(
            streak_threshold=1,
            cooldown_base_sec=10.0,
            cooldown_max_sec=100.0,
        )
        c1 = tracker.record_failure()  # level 1
        assert c1 == 10.0
        c2 = tracker.record_failure()  # level 2
        assert c2 == 20.0
        c3 = tracker.record_failure()  # level 3
        assert c3 == 40.0

    def test_cooldown_cap(self):
        tracker = FailureStreakTracker(
            streak_threshold=1,
            cooldown_base_sec=50.0,
            cooldown_max_sec=100.0,
        )
        tracker.record_failure()  # 50
        tracker.record_failure()  # 100
        c = tracker.record_failure()  # would be 200, capped at 100
        assert c == 100.0

    def test_success_resets(self):
        tracker = FailureStreakTracker(
            streak_threshold=2,
            cooldown_base_sec=10.0,
            cooldown_max_sec=100.0,
        )
        tracker.record_failure()
        tracker.record_success()
        assert tracker.streak == 0
        assert tracker.cooldown_level == 0


class TestXhsErrorHandler:
    def setup_method(self):
        self.handler = XhsErrorHandler()

    def test_classify_rate_limit(self):
        exc = XhsApiError(endpoint="test", payload=None, code=300011, msg="too many requests")
        assert self.handler.classify(exc) == ErrorType.RATE_LIMIT

    def test_classify_auth_invalid(self):
        exc = XhsApiError(endpoint="test", payload=None, code=-100, msg="need login")
        assert self.handler.classify(exc) == ErrorType.AUTH_INVALID

    def test_classify_ip_block(self):
        # 300012 is in account_state_error codes, classified as RATE_LIMIT
        # IP_BLOCK is triggered by the code check in classify after account state
        exc = XhsApiError(endpoint="test", payload=None, code=300012, msg="blocked")
        assert self.handler.classify(exc) == ErrorType.RATE_LIMIT

    def test_classify_network_connection_as_ip_block(self):
        assert self.handler.classify(Exception("network connection refused")) == ErrorType.IP_BLOCK

    def test_classify_note_abnormal(self):
        exc = XhsApiError(endpoint="test", payload=None, code=-510001, msg="note status abnormal")
        assert self.handler.classify(exc) == ErrorType.NOTE_ABNORMAL

    def test_classify_network_error(self):
        assert self.handler.classify(Exception("connection timeout")) == ErrorType.NETWORK_ERROR

    def test_determine_rate_limit_action(self):
        action, wait = self.handler.determine_action(ErrorType.RATE_LIMIT, attempt=1)
        assert action == RecoveryAction.LONG_SLEEP
        assert wait == 120.0

    def test_determine_rate_limit_escalation(self):
        _, wait1 = self.handler.determine_action(ErrorType.RATE_LIMIT, attempt=1)
        _, wait2 = self.handler.determine_action(ErrorType.RATE_LIMIT, attempt=2)
        assert wait2 > wait1

    def test_determine_auth_relogin(self):
        action, _ = self.handler.determine_action(ErrorType.AUTH_INVALID)
        assert action == RecoveryAction.RELOGIN

    def test_determine_note_abnormal_skip(self):
        action, _ = self.handler.determine_action(ErrorType.NOTE_ABNORMAL)
        assert action == RecoveryAction.SKIP


class TestRequestThrottleConfig:
    def test_defaults(self):
        cfg = RequestThrottleConfig()
        assert cfg.global_max_rps == 0.4
        assert cfg.comment_max_rps == 0.1
        assert cfg.request_jitter_sec == 0.25
        assert cfg.comment_jitter_sec == 3.0

    def test_custom(self):
        cfg = RequestThrottleConfig(global_max_rps=1.0, request_jitter_sec=0.5)
        assert cfg.global_max_rps == 1.0
        assert cfg.request_jitter_sec == 0.5


class TestXhsRequestThrottler:
    @pytest.mark.asyncio
    async def test_throttle_adds_delay(self):
        cfg = RequestThrottleConfig(global_max_rps=10.0, request_jitter_sec=0.0)
        throttler = XhsRequestThrottler(cfg)
        t0 = time.monotonic()
        await throttler.throttle("search")
        await throttler.throttle("search")
        elapsed = time.monotonic() - t0
        assert elapsed >= 0.09  # At least one rate-limit interval

    @pytest.mark.asyncio
    async def test_comment_has_separate_limit(self):
        cfg = RequestThrottleConfig(
            global_max_rps=100.0,  # fast global
            comment_max_rps=2.0,  # slow comment
            request_jitter_sec=0.0,
        )
        throttler = XhsRequestThrottler(cfg)
        await throttler.throttle("comment")
        t0 = time.monotonic()
        await throttler.throttle("comment")
        elapsed = time.monotonic() - t0
        assert elapsed >= 0.4  # 1/2.0 = 500ms, allow some margin
