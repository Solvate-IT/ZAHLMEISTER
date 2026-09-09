"""Add durable billing cycles, payment transactions and seller snapshots.

Revision ID: 0002_durable_billing
Revises: 0001_current_schema_baseline
Create Date: 2026-09-09
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002_durable_billing"
down_revision: str | None = "0001_current_schema_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "billing_legal_entities" not in tables:
        op.create_table(
            "billing_legal_entities",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("code", sa.String(40), nullable=False),
            sa.Column("legal_name", sa.String(240), nullable=False),
            sa.Column("country", sa.String(2), nullable=False),
            sa.Column("billing_email", sa.String(320), nullable=False),
            sa.Column("street_and_number", sa.String(240), nullable=False),
            sa.Column("postal_code", sa.String(40), nullable=False),
            sa.Column("city", sa.String(160), nullable=False),
            sa.Column("region", sa.String(160)),
            sa.Column("vat_number", sa.String(40)),
            sa.Column("organization_number", sa.String(80)),
            sa.Column("mollie_profile_id", sa.String(120)),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("char_length(country) = 2", name="ck_billing_legal_entity_country"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("code"),
        )
        op.create_index("ix_billing_legal_entity_active", "billing_legal_entities", ["active"])

    if "billing_tax_registrations" not in tables:
        op.create_table(
            "billing_tax_registrations",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("legal_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("registration_type", sa.String(30), nullable=False),
            sa.Column("country", sa.String(2), nullable=False),
            sa.Column("registration_reference", sa.String(120)),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("registration_type IN ('vat','eu_oss','gst','sales_tax')", name="ck_billing_tax_registration_type"),
            sa.CheckConstraint("char_length(country) = 2", name="ck_billing_tax_registration_country"),
            sa.ForeignKeyConstraint(["legal_entity_id"], ["billing_legal_entities.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("legal_entity_id", "registration_type", "country", "registration_reference", name="uq_billing_tax_registration_identity"),
        )
        op.create_index("ix_billing_tax_registration_active", "billing_tax_registrations", ["legal_entity_id", "active"])

    if "billing_cycles" not in tables:
        op.create_table(
            "billing_cycles",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("subscription_id", postgresql.UUID(as_uuid=True)),
            sa.Column("billing_key", sa.String(200), nullable=False),
            sa.Column("operation", sa.String(20), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="prepared"),
            sa.Column("provider", sa.String(20), nullable=False, server_default="mollie"),
            sa.Column("provider_environment", sa.String(20), nullable=False),
            sa.Column("product_id", sa.String(200), nullable=False),
            sa.Column("tariff_version", sa.String(40), nullable=False),
            sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column("gross_amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False),
            sa.Column("tax_rate", sa.Numeric(7, 3), nullable=False),
            sa.Column("tax_scheme", sa.String(30), nullable=False),
            sa.Column("tax_treatment", sa.String(40), nullable=False),
            sa.Column("tax_rule_version", sa.String(80), nullable=False),
            sa.Column("recipient_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("operation IN ('initial','renewal')", name="ck_billing_cycle_operation"),
            sa.CheckConstraint("status IN ('prepared','payment_pending','paid','failed','cancelled')", name="ck_billing_cycle_status"),
            sa.CheckConstraint("provider IN ('mollie')", name="ck_billing_cycle_provider"),
            sa.CheckConstraint("provider_environment IN ('test','live')", name="ck_billing_cycle_environment"),
            sa.CheckConstraint("gross_amount >= 0", name="ck_billing_cycle_gross_nonnegative"),
            sa.CheckConstraint("period_end > period_start", name="ck_billing_cycle_period"),
            sa.CheckConstraint("retry_count >= 0", name="ck_billing_cycle_retry_nonnegative"),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["subscription_id"], ["store_subscriptions.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("billing_key"),
            sa.UniqueConstraint("organization_id", "provider", "product_id", "period_start", name="uq_billing_cycle_org_provider_product_period"),
        )
        op.create_index("ix_billing_cycle_due", "billing_cycles", ["status", "period_start"])
        op.create_index("ix_billing_cycles_subscription_id", "billing_cycles", ["subscription_id"])
        op.create_index("ix_billing_cycles_status", "billing_cycles", ["status"])

    if "billing_payment_transactions" not in tables:
        op.create_table(
            "billing_payment_transactions",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("provider", sa.String(20), nullable=False, server_default="mollie"),
            sa.Column("provider_environment", sa.String(20), nullable=False),
            sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(30), nullable=False, server_default="reserved"),
            sa.Column("sequence_type", sa.String(20), nullable=False),
            sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("provider_reference", sa.String(200)),
            sa.Column("gross_amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False),
            sa.Column("paid_at", sa.DateTime(timezone=True)),
            sa.Column("last_synced_at", sa.DateTime(timezone=True)),
            sa.Column("last_error", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("provider IN ('mollie')", name="ck_billing_payment_provider"),
            sa.CheckConstraint("provider_environment IN ('test','live')", name="ck_billing_payment_environment"),
            sa.CheckConstraint("attempt > 0", name="ck_billing_payment_attempt_positive"),
            sa.CheckConstraint("status IN ('reserved','open','pending','paid','failed','cancelled','expired')", name="ck_billing_payment_status"),
            sa.CheckConstraint("sequence_type IN ('first','recurring')", name="ck_billing_payment_sequence"),
            sa.CheckConstraint("gross_amount >= 0", name="ck_billing_payment_gross_nonnegative"),
            sa.ForeignKeyConstraint(["cycle_id"], ["billing_cycles.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("cycle_id", "attempt", name="uq_billing_payment_cycle_attempt"),
            sa.UniqueConstraint("provider_reference"),
        )
        op.create_index("ix_billing_payment_cycle_status", "billing_payment_transactions", ["cycle_id", "status"])
        op.create_index("ix_billing_payment_transactions_provider_reference", "billing_payment_transactions", ["provider_reference"])
        op.create_index("ix_billing_payment_transactions_status", "billing_payment_transactions", ["status"])

    invoice_columns = {column["name"] for column in inspector.get_columns("billing_invoices")}
    additions = [
        ("billing_cycle_id", postgresql.UUID(as_uuid=True)),
        ("payment_transaction_id", postgresql.UUID(as_uuid=True)),
        ("net_amount", sa.Numeric(14, 2)),
        ("tax_amount", sa.Numeric(14, 2)),
        ("seller_legal_name", sa.String(240)),
        ("seller_country", sa.String(2)),
        ("seller_vat_number", sa.String(40)),
    ]
    for name, type_ in additions:
        if name not in invoice_columns:
            op.add_column("billing_invoices", sa.Column(name, type_, nullable=True))

    inspector = sa.inspect(bind)
    fks = {fk.get("name") for fk in inspector.get_foreign_keys("billing_invoices")}
    if "fk_billing_invoice_cycle" not in fks:
        op.create_foreign_key("fk_billing_invoice_cycle", "billing_invoices", "billing_cycles", ["billing_cycle_id"], ["id"], ondelete="SET NULL")
    if "fk_billing_invoice_payment" not in fks:
        op.create_foreign_key("fk_billing_invoice_payment", "billing_invoices", "billing_payment_transactions", ["payment_transaction_id"], ["id"], ondelete="SET NULL")

    indexes = {index["name"] for index in inspector.get_indexes("billing_invoices")}
    if "ix_billing_invoices_billing_cycle_id" not in indexes:
        op.create_index("ix_billing_invoices_billing_cycle_id", "billing_invoices", ["billing_cycle_id"])
    if "ix_billing_invoices_payment_transaction_id" not in indexes:
        op.create_index("ix_billing_invoices_payment_transaction_id", "billing_invoices", ["payment_transaction_id"])

    # Existing gross invoices are preserved. Only mathematically derivable amounts are backfilled.
    op.execute("""
        UPDATE billing_invoices
        SET net_amount = CASE
                WHEN vat_rate = 0 THEN gross_amount
                ELSE round(gross_amount / (1 + vat_rate / 100.0), 2)
            END,
            tax_amount = CASE
                WHEN vat_rate = 0 THEN 0
                ELSE gross_amount - round(gross_amount / (1 + vat_rate / 100.0), 2)
            END
        WHERE net_amount IS NULL OR tax_amount IS NULL
    """)


def downgrade() -> None:
    # Financial history is intentionally not dropped automatically.
    pass
