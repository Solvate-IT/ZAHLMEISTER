import json
import logging

from app.core.observability import JsonFormatter


def test_json_formatter_is_structured_and_does_not_expand_args() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Request %s",
        args=("ok",),
        exc_info=None,
    )
    payload = json.loads(formatter.format(record))
    assert payload["level"] == "INFO"
    assert payload["message"] == "Request ok"
    assert "timestamp" in payload
