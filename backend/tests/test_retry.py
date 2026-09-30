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


def test_smtp_replies_are_classified_by_their_code() -> None:
    import smtplib

    assert is_retryable_exception(smtplib.SMTPResponseException(451, b"try again later"))
    assert not is_retryable_exception(smtplib.SMTPResponseException(550, b"mailbox unavailable"))
    assert not is_retryable_exception(smtplib.SMTPAuthenticationError(535, b"bad credentials"))
    assert not is_retryable_exception(
        smtplib.SMTPRecipientsRefused({"a@example.test": (550, b"no such user")})
    )
    assert is_retryable_exception(
        smtplib.SMTPRecipientsRefused({"a@example.test": (452, b"mailbox full")})
    )
    # A dropped connection is still temporary.
    assert is_retryable_exception(smtplib.SMTPServerDisconnected("closed"))


def test_certificate_failures_and_explicit_classes() -> None:
    import ssl

    from app.services.retry import PermanentError, RetryableError, retry_after_seconds

    assert not is_retryable_exception(ssl.SSLCertVerificationError("self-signed certificate"))
    assert is_retryable_exception(RetryableError("throttled", retry_after=30))
    assert not is_retryable_exception(PermanentError("not verified"))
    assert retry_after_seconds("120") == 120
    assert retry_after_seconds("Wed, 21 Oct 2026 07:28:00 GMT") is None
    assert retry_after_seconds(None) is None
