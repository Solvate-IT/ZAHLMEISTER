import random

import httpx


def retry_delay_seconds(
    attempt: int,
    *,
    base_seconds: int,
    max_seconds: int,
    jitter_fraction: float,
) -> float:
    attempt = max(1, attempt)
    base = min(float(max_seconds), float(base_seconds) * (2 ** (attempt - 1)))
    jitter = base * max(0.0, jitter_fraction)
    if jitter <= 0:
        return base
    return min(float(max_seconds), base + random.uniform(0, jitter))


def is_retryable_exception(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code in {408, 425, 429} or code >= 500
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError, TimeoutError, OSError)):
        return True
    if isinstance(exc, (ValueError, TypeError, KeyError, NotImplementedError)):
        return False
    return True
