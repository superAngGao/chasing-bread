"""Centralized request throttling, retry, and cooldown utilities for XHS API."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from data_collection.utils.rate_limit import RateLimiter
from data_collection.xhs.error_handler import (
    ErrorType,
    RecoveryAction,
    ReLoginRequiredError,
    XhsErrorHandler,
)

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RequestThrottleConfig:
    global_max_rps: float = 0.4
    comment_max_rps: float = 0.2
    request_jitter_sec: float = 0.25
    comment_failure_streak_threshold: int = 5
    comment_failure_cooldown_base_sec: float = 120.0
    comment_failure_cooldown_max_sec: float = 1800.0
    rate_limit_cooldown_min_sec: float = 300.0
    rate_limit_cooldown_max_sec: float = 1800.0
    scheduler_backoff_minutes: tuple[int, ...] = (2, 5, 10)


class FailureStreakTracker:
    def __init__(
        self,
        *,
        streak_threshold: int,
        cooldown_base_sec: float,
        cooldown_max_sec: float,
        name: str = "comment",
    ) -> None:
        self._threshold = streak_threshold
        self._base = cooldown_base_sec
        self._max = cooldown_max_sec
        self._name = name

        self.streak: int = 0
        self.cooldown_level: int = 0
        self._cooldown_until_ts: float = 0.0

    def record_success(self) -> None:
        self.streak = 0
        self.cooldown_level = 0
        self._cooldown_until_ts = 0.0

    def record_failure(self) -> float:
        self.streak += 1
        if self.streak >= self._threshold and self._base > 0:
            self.cooldown_level += 1
            cooldown_sec = min(
                self._base * (2 ** (self.cooldown_level - 1)),
                self._max,
            )
            self._cooldown_until_ts = time.monotonic() + cooldown_sec
            logger.warning(
                "[request_utils] %s consecutive failures=%s, escalating cooldown level=%s duration=%.0fs",
                self._name,
                self.streak,
                self.cooldown_level,
                cooldown_sec,
            )
            self.streak = 0
            return cooldown_sec
        return 0.0

    def escalate_from_rate_limit(self, wait_sec: float, fallback_base: float) -> float:
        self.streak = 0
        self.cooldown_level += 1
        cooldown_sec = min(
            max(self._base, wait_sec, fallback_base) * (2 ** (self.cooldown_level - 1)),
            self._max,
        )
        self._cooldown_until_ts = time.monotonic() + cooldown_sec
        return cooldown_sec

    def clear_cooldown(self) -> None:
        self._cooldown_until_ts = 0.0

    @property
    def cooldown_remaining(self) -> float:
        return max(0.0, self._cooldown_until_ts - time.monotonic())

    async def wait_cooldown(self) -> None:
        remaining = self.cooldown_remaining
        if remaining > 0:
            logger.warning(
                "[request_utils] %s cooldown active (level=%s, remaining=%.0fs); pausing",
                self._name,
                self.cooldown_level,
                remaining,
            )
            await asyncio.sleep(remaining)
            self._cooldown_until_ts = 0.0


class XhsRequestThrottler:
    def __init__(
        self,
        config: RequestThrottleConfig | None = None,
        *,
        log: logging.Logger | None = None,
    ) -> None:
        self._cfg = config or RequestThrottleConfig()
        self._log = log or logger

        self._error_handler = XhsErrorHandler(self._log)
        self._global_limiter = RateLimiter(self._cfg.global_max_rps)
        self._comment_limiter = RateLimiter(self._cfg.comment_max_rps)

        self.comment_streak = FailureStreakTracker(
            streak_threshold=self._cfg.comment_failure_streak_threshold,
            cooldown_base_sec=self._cfg.comment_failure_cooldown_base_sec,
            cooldown_max_sec=self._cfg.comment_failure_cooldown_max_sec,
            name="comment",
        )

    @property
    def config(self) -> RequestThrottleConfig:
        return self._cfg

    @property
    def error_handler(self) -> XhsErrorHandler:
        return self._error_handler

    @property
    def global_limiter(self) -> RateLimiter:
        return self._global_limiter

    @property
    def comment_limiter(self) -> RateLimiter:
        return self._comment_limiter

    async def throttle(self, endpoint: str = "default") -> None:
        await self._global_limiter.wait_async()
        if endpoint == "comment":
            await self._comment_limiter.wait_async()
        if self._cfg.request_jitter_sec > 0:
            await asyncio.sleep(random.uniform(0, self._cfg.request_jitter_sec))

    def classify_error(self, exc: Exception | str | int) -> ErrorType:
        return self._error_handler.classify(exc)

    def determine_recovery(
        self, error_type: ErrorType, attempt: int = 1
    ) -> tuple[RecoveryAction, float]:
        return self._error_handler.determine_action(error_type, attempt)

    async def handle_comment_rate_limit(self, exc: Exception) -> float:
        err_type = self.classify_error(exc)

        if err_type == ErrorType.RATE_LIMIT:
            action, wait_sec = self.determine_recovery(
                ErrorType.RATE_LIMIT,
                attempt=max(1, self.comment_streak.cooldown_level + 1),
            )
            if action == RecoveryAction.LONG_SLEEP:
                cooldown_sec = self.comment_streak.escalate_from_rate_limit(
                    wait_sec,
                    self._cfg.rate_limit_cooldown_min_sec,
                )
                self._log.warning(
                    "[request_utils] comment rate-limit confirmed; cooldown level=%s duration=%.0fs",
                    self.comment_streak.cooldown_level,
                    cooldown_sec,
                )
                await asyncio.sleep(cooldown_sec)
                self.comment_streak.clear_cooldown()
                return cooldown_sec

        if err_type == ErrorType.AUTH_INVALID:
            raise ReLoginRequiredError("comment auth invalid")

        return 0.0

    async def execute_with_retry(
        self,
        fn: Callable[..., Awaitable[T]],
        *args: Any,
        endpoint: str = "default",
        max_retries: int = 2,
        **kwargs: Any,
    ) -> T:
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            await self.throttle(endpoint)
            try:
                return await fn(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                err_type = self.classify_error(exc)
                action, wait_sec = self.determine_recovery(err_type, attempt)

                if action in (
                    RecoveryAction.SKIP,
                    RecoveryAction.ABORT,
                    RecoveryAction.RELOGIN,
                    RecoveryAction.LONG_SLEEP,
                ):
                    raise

                if attempt < max_retries:
                    self._log.info(
                        "[request_utils] %s attempt %s/%s failed (%s); retry in %.1fs",
                        endpoint,
                        attempt,
                        max_retries,
                        err_type.name,
                        wait_sec,
                    )
                    await asyncio.sleep(wait_sec)
                else:
                    raise
        assert last_exc is not None
        raise last_exc
