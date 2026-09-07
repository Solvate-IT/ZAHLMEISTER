from datetime import UTC, datetime

from app.services.reminders import normalize_reminder_rules, reminder_schedule


def test_reminder_rules_deduplicate_and_normalize() -> None:
    rules = normalize_reminder_rules([
        {"type": "after_send", "days": 5},
        {"type": "after_send", "days": 5},
        {"type": "on_due", "days": 9},
    ])
    assert rules == [
        {"type": "after_send", "days": 5},
        {"type": "on_due", "days": 0},
    ]


def test_reminder_schedule_uses_send_and_due_dates() -> None:
    send = datetime(2026, 9, 1, 8, tzinfo=UTC)
    due = datetime(2026, 9, 10, 8, tzinfo=UTC)
    schedule = reminder_schedule(
        rules=[
            {"type": "after_send", "days": 5},
            {"type": "before_due", "days": 2},
            {"type": "on_due", "days": 0},
        ],
        send_at=send,
        due_at=due,
        now=datetime(2026, 9, 1, 7, tzinfo=UTC),
    )
    assert [item[0] for item in schedule] == ["after_send:5", "before_due:2", "on_due:0"]
