import random
import smtplib
import ssl

import httpx


class RetryableError(Exception):
    """A temporary provider condition (throttling, 5xx). Retry, not before retry_after."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class PermanentError(Exception):
    """A failure that repeating the same request cannot fix."""


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


def retry_after_seconds(value: str | None) -> float | None:
    """Parse a Retry-After header given in seconds (the form providers use for throttling)."""
    try:
        seconds = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


def is_retryable_exception(exc: Exception) -> bool:
    if isinstance(exc, RetryableError):
        return True
    if isinstance(exc, PermanentError):
        return False
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code in {408, 425, 429} or code >= 500
    # smtplib errors are OSError subclasses, so they must be classified before the
    # generic OSError rule: a 5xx reply ("mailbox does not exist", "relay denied")
    # is final, a 4xx reply ("try again later", greylisting) is temporary.
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return all(400 <= code < 500 for code, _message in exc.recipients.values())
    if isinstance(exc, smtplib.SMTPResponseException):
        return 400 <= exc.smtp_code < 500
    if isinstance(exc, ssl.SSLCertVerificationError):
        # A certificate that does not verify will not start verifying on retry.
        return False
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError, TimeoutError, OSError)):
        return True
    if isinstance(exc, (ValueError, TypeError, KeyError, NotImplementedError)):
        return False
    return True
