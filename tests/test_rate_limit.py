from __future__ import annotations

import time

import pytest

from data_collection.utils.rate_limit import RateLimiter


class TestRateLimiter:
    def test_invalid_rps_raises(self):
        with pytest.raises(ValueError, match="must be positive"):
            RateLimiter(max_rps=0)
        with pytest.raises(ValueError, match="must be positive"):
            RateLimiter(max_rps=-1)

    def test_sync_rate_limiting(self):
        """Two consecutive sync waits should respect the minimum interval."""
        limiter = RateLimiter(max_rps=10)  # 0.1s interval
        limiter.wait_sync()
        start = time.monotonic()
        limiter.wait_sync()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.09  # allow small tolerance

    def test_first_call_no_wait(self):
        """The first call should not wait."""
        limiter = RateLimiter(max_rps=1)
        start = time.monotonic()
        limiter.wait_sync()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_async_rate_limiting(self):
        """Two consecutive async waits should respect the minimum interval."""
        limiter = RateLimiter(max_rps=10)
        await limiter.wait_async()
        start = time.monotonic()
        await limiter.wait_async()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.09

    def test_high_rps_fast(self):
        """High RPS limiter should allow rapid calls."""
        limiter = RateLimiter(max_rps=1000)
        start = time.monotonic()
        for _ in range(10):
            limiter.wait_sync()
        elapsed = time.monotonic() - start
        assert elapsed < 0.5
