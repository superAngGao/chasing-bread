"""Simple rate limiter supporting both sync and async usage."""

from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Token-bucket style rate limiter with sync and async wait methods."""

    def __init__(self, max_rps: float = 1.0) -> None:
        if max_rps <= 0:
            raise ValueError("max_rps must be positive")
        self._min_interval = 1.0 / max_rps
        self._last: float = 0.0
        self._async_lock = asyncio.Lock()

    def wait_sync(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last = time.monotonic()

    async def wait_async(self) -> None:
        async with self._async_lock:
            now = time.monotonic()
            elapsed = now - self._last
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last = time.monotonic()
