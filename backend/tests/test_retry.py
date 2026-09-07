import httpx

from app.services.retry import is_retryable_exception, retry_delay_seconds


def test_exponential_retry_without_jitter() -> None:
    assert retry_delay_seconds(1, base_seconds=5, max_seconds=900, jitter_fraction=0) == 5
    assert retry_delay_seconds(2, base_seconds=5, max_seconds=900, jitter_fraction=0) == 10
    assert retry_delay_seconds(9, base_seconds=5, max_seconds=900, jitter_fraction=0) == 900


def test_retryable_http_statuses() -> None:
    request = httpx.Request("GET", "https://example.test")
    retryable = httpx.HTTPStatusError(
        "temporary",
        request=request,
        response=httpx.Response(503, request=request),
    )
    permanent = httpx.HTTPStatusError(
        "invalid",
        request=request,
        response=httpx.Response(400, request=request),
    )
    assert is_retryable_exception(retryable)
    assert not is_retryable_exception(permanent)
    assert not is_retryable_exception(ValueError("configuration error"))
