import contextvars
import json
import logging
import re
import sys
import time
import uuid
from datetime import UTC, datetime

from app.core.config import settings

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")


def _safe_log_path(path: str) -> str:
    path = re.sub(r"(/api/v1/public/payments/)[^/]+", r"\1<redacted>", path)
    path = re.sub(r"(/api/v1/webhooks/[^/]+/)[^/]+", r"\1<redacted>", path)
    return path


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None) or _request_id.get()
        if request_id and request_id != "-":
            payload["request_id"] = request_id
        for key in (
            "event",
            "method",
            "path",
            "status_code",
            "duration_ms",
            "client_ip",
            "job_id",
            "job_type",
            "attempt",
            "retry_in_seconds",
            "organization_id",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = _request_id.get()
        return True


def configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())
    if settings.log_format.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s")
        )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


class RequestLoggingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        headers_in = dict(scope.get("headers", []))
        supplied = headers_in.get(b"x-request-id", b"").decode(
            "ascii", errors="ignore"
        ).strip()
        request_id = supplied if _REQUEST_ID_RE.fullmatch(supplied) else uuid.uuid4().hex
        token = _request_id.set(request_id)
        started = time.perf_counter()
        status_holder = {"value": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["value"] = message["status"]
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            logging.getLogger("zahlmeister.request").exception(
                "Unhandled request error",
                extra={
                    "event": "request_failed",
                    "method": scope.get("method"),
                    "path": _safe_log_path(scope.get("path", "")),
                },
            )
            raise
        finally:
            raw_path = scope.get("path", "")
            path = _safe_log_path(raw_path)
            if raw_path != "/api/v1/health":
                duration_ms = round((time.perf_counter() - started) * 1000, 2)
                forwarded = headers_in.get(b"x-forwarded-for", b"").decode(
                    "ascii", errors="ignore"
                )
                real_ip = headers_in.get(b"x-real-ip", b"").decode(
                    "ascii", errors="ignore"
                )
                client = scope.get("client")
                if settings.trust_proxy_headers and real_ip:
                    client_ip = real_ip.strip()
                elif settings.trust_proxy_headers and forwarded:
                    client_ip = forwarded.split(",", 1)[0].strip()
                else:
                    client_ip = client[0] if client else "unknown"
                logging.getLogger("zahlmeister.request").info(
                    "HTTP request",
                    extra={
                        "event": "request",
                        "method": scope.get("method"),
                        "path": path,
                        "status_code": status_holder["value"],
                        "duration_ms": duration_ms,
                        "client_ip": client_ip,
                    },
                )
            _request_id.reset(token)
