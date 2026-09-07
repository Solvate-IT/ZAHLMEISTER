from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

DEFAULT_REMINDER_RULES = [{"type": "after_send", "days": 5}]
ALLOWED_RULE_TYPES = {"after_send", "before_due", "on_due", "after_due"}


def normalize_reminder_rules(value: list[dict] | None) -> list[dict[str, int | str]]:
    if value is None:
        value = DEFAULT_REMINDER_RULES
    normalized: list[dict[str, int | str]] = []
    seen: set[tuple[str, int]] = set()
    for raw in value:
        rule_type = str(raw.get("type", "")).strip()
        if rule_type not in ALLOWED_RULE_TYPES:
            raise ValueError(f"Unsupported reminder rule: {rule_type}")
        days = int(raw.get("days", 0))
        if days < 0 or days > 365:
            raise ValueError("Reminder days must be between 0 and 365")
        if rule_type == "on_due":
            days = 0
        key = (rule_type, days)
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"type": rule_type, "days": days})
    if len(normalized) > 10:
        raise ValueError("At most 10 reminder rules are allowed")
    return normalized


def serialize_reminder_rules(value: list[dict] | None) -> str:
    return json.dumps(normalize_reminder_rules(value), separators=(",", ":"))


def deserialize_reminder_rules(value: str | None) -> list[dict[str, int | str]]:
    if not value:
        return list(DEFAULT_REMINDER_RULES)
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return list(DEFAULT_REMINDER_RULES)
    if not isinstance(parsed, list):
        return list(DEFAULT_REMINDER_RULES)
    try:
        return normalize_reminder_rules(parsed)
    except (TypeError, ValueError):
        return list(DEFAULT_REMINDER_RULES)


def reminder_schedule(
    *,
    rules: list[dict],
    send_at: datetime,
    due_at: datetime | None,
    now: datetime | None = None,
) -> list[tuple[str, datetime]]:
    now = now or datetime.now(UTC)
    if send_at.tzinfo is None:
        send_at = send_at.replace(tzinfo=UTC)
    if due_at is not None and due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=UTC)
    schedules: dict[datetime, str] = {}
    for rule in normalize_reminder_rules(rules):
        rule_type = str(rule["type"])
        days = int(rule["days"])
        scheduled: datetime | None = None
        if rule_type == "after_send":
            scheduled = send_at + timedelta(days=days)
        elif rule_type == "before_due" and due_at is not None:
            scheduled = due_at - timedelta(days=days)
        elif rule_type == "on_due" and due_at is not None:
            scheduled = due_at
        elif rule_type == "after_due" and due_at is not None:
            scheduled = due_at + timedelta(days=days)
        if scheduled is None or scheduled <= max(send_at, now):
            continue
        schedules.setdefault(scheduled, f"{rule_type}:{days}")
    return [(key, scheduled) for scheduled, key in sorted(schedules.items())]
