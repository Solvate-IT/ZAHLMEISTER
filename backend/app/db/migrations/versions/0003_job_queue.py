"""Job queue: priorities, typed references and de-duplication.

- priority: interactive work is claimed before bulk sends (claim index updated);
- collection_id / message_id: typed references replace lookups by payload text;
- dedupe_key: one logical unit of work (a reminder rule, a periodic sync) is
  enqueued at most once while pending or running.

Existing jobs are backfilled from their JSON payload, so the new lookups also
find work that was queued before this revision.

Revision ID: 0003_job_queue
Revises: 0002_foreign_key_indexes
Create Date: 2026-09-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_job_queue"
down_revision: str | None = "0002_foreign_key_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = "[0-9a-fA-F-]{36}"


def upgrade() -> None:
    op.add_column(
        "scheduled_jobs",
        sa.Column("priority", sa.SmallInteger(), server_default=sa.text("100"), nullable=False),
    )
    op.add_column("scheduled_jobs", sa.Column("collection_id", sa.UUID(), nullable=True))
    op.add_column("scheduled_jobs", sa.Column("message_id", sa.UUID(), nullable=True))
    op.add_column("scheduled_jobs", sa.Column("dedupe_key", sa.String(length=200), nullable=True))

    # Backfill before the foreign keys exist; each UPDATE joins the referenced
    # table, so only ids that really exist are written.
    op.execute(
        f"""
        UPDATE scheduled_jobs AS j
        SET collection_id = c.id
        FROM collections AS c
        WHERE j.job_type IN ('send_collection', 'send_reminders')
          AND j.payload ~ '"collection_id": *"{_UUID}"'
          AND c.id = CAST(substring(j.payload FROM '"collection_id": *"({_UUID})"') AS uuid)
        """
    )
    op.execute(
        f"""
        UPDATE scheduled_jobs AS j
        SET message_id = m.id, collection_id = m.collection_id
        FROM communication_messages AS m
        WHERE j.job_type = 'send_message'
          AND j.payload ~ '"message_id": *"{_UUID}"'
          AND m.id = CAST(substring(j.payload FROM '"message_id": *"({_UUID})"') AS uuid)
        """
    )
    # Reminder rules were de-duplicated by exact payload text. Only one active job
    # per rule can therefore exist; the window keeps the unique index safe anyway.
    op.execute(
        """
        WITH candidates AS (
            SELECT id,
                   'reminder:' || collection_id || ':'
                       || substring(payload FROM '"rule": *"([^"]+)"') AS key,
                   status IN ('pending', 'running') AS active,
                   row_number() OVER (
                       PARTITION BY collection_id,
                                    substring(payload FROM '"rule": *"([^"]+)"'),
                                    status IN ('pending', 'running')
                       ORDER BY created_at
                   ) AS rn
            FROM scheduled_jobs
            WHERE job_type = 'send_reminders'
              AND collection_id IS NOT NULL
              AND payload ~ '"rule": *"[^"]+"'
        )
        UPDATE scheduled_jobs AS j
        SET dedupe_key = c.key
        FROM candidates AS c
        WHERE j.id = c.id AND (NOT c.active OR c.rn = 1)
        """
    )

    op.create_foreign_key(
        "scheduled_jobs_collection_id_fkey",
        "scheduled_jobs",
        "collections",
        ["collection_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "scheduled_jobs_message_id_fkey",
        "scheduled_jobs",
        "communication_messages",
        ["message_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_index("ix_jobs_due", table_name="scheduled_jobs")
    op.create_index("ix_jobs_claim", "scheduled_jobs", ["status", "priority", "scheduled_at"])
    op.create_index(op.f("ix_scheduled_jobs_collection_id"), "scheduled_jobs", ["collection_id"])
    op.create_index(op.f("ix_scheduled_jobs_message_id"), "scheduled_jobs", ["message_id"])
    op.create_index(op.f("ix_scheduled_jobs_dedupe_key"), "scheduled_jobs", ["dedupe_key"])
    op.create_index(
        "uq_scheduled_jobs_active_dedupe",
        "scheduled_jobs",
        ["dedupe_key"],
        unique=True,
        postgresql_where=sa.text("dedupe_key IS NOT NULL AND status IN ('pending', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_scheduled_jobs_active_dedupe", table_name="scheduled_jobs")
    op.drop_index(op.f("ix_scheduled_jobs_dedupe_key"), table_name="scheduled_jobs")
    op.drop_index(op.f("ix_scheduled_jobs_message_id"), table_name="scheduled_jobs")
    op.drop_index(op.f("ix_scheduled_jobs_collection_id"), table_name="scheduled_jobs")
    op.drop_index("ix_jobs_claim", table_name="scheduled_jobs")
    op.create_index("ix_jobs_due", "scheduled_jobs", ["status", "scheduled_at"])
    op.drop_constraint("scheduled_jobs_message_id_fkey", "scheduled_jobs", type_="foreignkey")
    op.drop_constraint("scheduled_jobs_collection_id_fkey", "scheduled_jobs", type_="foreignkey")
    op.drop_column("scheduled_jobs", "dedupe_key")
    op.drop_column("scheduled_jobs", "message_id")
    op.drop_column("scheduled_jobs", "collection_id")
    op.drop_column("scheduled_jobs", "priority")
