# Utils

Shared utilities used across the data collection module.

## RateLimiter

Token-bucket style rate limiter with both sync and async support.

```python
from data_collection.utils import RateLimiter

limiter = RateLimiter(max_rps=0.5)  # 1 request every 2 seconds

# Sync usage
limiter.wait_sync()

# Async usage
await limiter.wait_async()
```

## Logging

Configures the root logger with timestamped, leveled output.

```python
from data_collection.utils import configure_logging

configure_logging(level="DEBUG")
```
