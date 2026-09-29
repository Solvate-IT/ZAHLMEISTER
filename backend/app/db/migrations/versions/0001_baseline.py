"""Baseline: the complete Zahlmeister schema as of the switch to Alembic.

Generated from the ORM models and verified to produce exactly the schema that
Base.metadata.create_all built before (identical pg_dump --schema-only).

Installations that predate Alembic are adopted by app.db.bootstrap: it brings
them to this shape, stamps this revision and continues with the later ones.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0001_baseline'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('organizations',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('locale', sa.String(length=20), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('bank_account_name', sa.String(length=200), nullable=True),
    sa.Column('bank_iban', sa.String(length=34), nullable=True),
    sa.Column('bank_bic', sa.String(length=11), nullable=True),
    sa.Column('message_include_payment_link', sa.Boolean(), nullable=False),
    sa.Column('message_include_payment_qr', sa.Boolean(), nullable=False),
    sa.Column('api_enabled', sa.Boolean(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('runtime_heartbeats',
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('details_json', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('name')
    )
    op.create_index(op.f('ix_runtime_heartbeats_last_seen_at'), 'runtime_heartbeats', ['last_seen_at'], unique=False)
    op.create_table('api_credentials',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('token_prefix', sa.String(length=20), nullable=False),
    sa.Column('scopes_json', sa.Text(), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash', name='uq_api_credentials_token_hash')
    )
    op.create_index('ix_api_credentials_org_created', 'api_credentials', ['organization_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_api_credentials_revoked_at'), 'api_credentials', ['revoked_at'], unique=False)
    op.create_table('bank_statement_imports',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('filename', sa.String(length=500), nullable=False),
    sa.Column('format', sa.String(length=30), nullable=False),
    sa.Column('transaction_count', sa.Integer(), nullable=False),
    sa.Column('auto_matched_count', sa.Integer(), nullable=False),
    sa.Column('review_count', sa.Integer(), nullable=False),
    sa.Column('unmatched_count', sa.Integer(), nullable=False),
    sa.Column('duplicate_count', sa.Integer(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_bank_imports_org_created', 'bank_statement_imports', ['organization_id', 'created_at'], unique=False)
    op.create_table('bank_sync_connections',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('provider', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('account_label', sa.String(length=320), nullable=True),
    sa.Column('encrypted_config', sa.Text(), nullable=True),
    sa.Column('connected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_tested_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'provider', name='uq_bank_sync_connection_org_provider')
    )
    op.create_index(op.f('ix_bank_sync_connections_status'), 'bank_sync_connections', ['status'], unique=False)
    op.create_table('billing_profiles',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('customer_type', sa.String(length=20), nullable=False),
    sa.Column('given_name', sa.String(length=120), nullable=True),
    sa.Column('family_name', sa.String(length=120), nullable=True),
    sa.Column('organization_name', sa.String(length=200), nullable=True),
    sa.Column('billing_email', sa.String(length=320), nullable=False),
    sa.Column('street_and_number', sa.String(length=240), nullable=False),
    sa.Column('postal_code', sa.String(length=40), nullable=False),
    sa.Column('city', sa.String(length=160), nullable=False),
    sa.Column('region', sa.String(length=160), nullable=True),
    sa.Column('country', sa.String(length=2), nullable=False),
    sa.Column('vat_number', sa.String(length=40), nullable=True),
    sa.Column('organization_number', sa.String(length=80), nullable=True),
    sa.Column('vat_validation_status', sa.String(length=20), nullable=False),
    sa.Column('vat_validated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('organization_id')
    )
    op.create_index('ix_billing_profiles_country', 'billing_profiles', ['country'], unique=False)
    op.create_table('communication_connections',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('provider', sa.String(length=40), nullable=False),
    sa.Column('auth_type', sa.String(length=30), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('account_label', sa.String(length=320), nullable=True),
    sa.Column('account_key', sa.String(length=120), nullable=True),
    sa.Column('encrypted_config', sa.Text(), nullable=True),
    sa.Column('webhook_key', sa.String(length=80), nullable=True),
    sa.Column('connected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('last_tested_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_comm_connections_org_provider', 'communication_connections', ['organization_id', 'provider'], unique=False)
    op.create_index(op.f('ix_communication_connections_account_key'), 'communication_connections', ['account_key'], unique=False)
    op.create_index(op.f('ix_communication_connections_status'), 'communication_connections', ['status'], unique=False)
    op.create_index(op.f('ix_communication_connections_webhook_key'), 'communication_connections', ['webhook_key'], unique=True)
    op.create_table('communication_preferences',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('channel_order_json', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('organization_id')
    )
    op.create_table('message_templates',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('translations_json', sa.Text(), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'name', name='uq_message_templates_org_name')
    )
    op.create_index('uq_message_templates_org_default', 'message_templates', ['organization_id'], unique=True, postgresql_where=sa.text('is_default'))
    op.create_table('online_payment_connections',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('provider', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('account_label', sa.String(length=320), nullable=True),
    sa.Column('profile_id', sa.String(length=120), nullable=True),
    sa.Column('encrypted_config', sa.Text(), nullable=True),
    sa.Column('connected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_tested_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'provider', name='uq_online_payment_connection_org_provider')
    )
    op.create_index(op.f('ix_online_payment_connections_status'), 'online_payment_connections', ['status'], unique=False)
    op.create_table('participant_lists',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'name', name='uq_participant_lists_org_name')
    )
    op.create_table('scheduled_jobs',
    sa.Column('organization_id', sa.UUID(), nullable=True),
    sa.Column('job_type', sa.String(length=60), nullable=False),
    sa.Column('payload', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_jobs_due', 'scheduled_jobs', ['status', 'scheduled_at'], unique=False)
    op.create_index(op.f('ix_scheduled_jobs_scheduled_at'), 'scheduled_jobs', ['scheduled_at'], unique=False)
    op.create_index(op.f('ix_scheduled_jobs_status'), 'scheduled_jobs', ['status'], unique=False)
    op.create_table('store_subscriptions',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('product_id', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('external_reference', sa.String(length=320), nullable=True),
    sa.Column('purchased_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('auto_renew', sa.Boolean(), nullable=True),
    sa.Column('environment', sa.String(length=20), nullable=True),
    sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('verification_data_encrypted', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("provider IN ('admin','apple','google','mollie')", name='ck_store_subscriptions_provider'),
    sa.CheckConstraint("status IN ('pending','active','grace_period','cancelled','expired','revoked','on_hold')", name='ck_store_subscriptions_status'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('external_reference'),
    sa.UniqueConstraint('organization_id', 'provider', name='uq_store_subscription_org_provider')
    )
    op.create_index(op.f('ix_store_subscriptions_expires_at'), 'store_subscriptions', ['expires_at'], unique=False)
    op.create_index(op.f('ix_store_subscriptions_last_verified_at'), 'store_subscriptions', ['last_verified_at'], unique=False)
    op.create_index('ix_store_subscriptions_org_status', 'store_subscriptions', ['organization_id', 'status'], unique=False)
    op.create_index(op.f('ix_store_subscriptions_status'), 'store_subscriptions', ['status'], unique=False)
    op.create_table('users',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('display_name', sa.String(length=200), nullable=False),
    sa.Column('phone', sa.String(length=50), nullable=True),
    sa.Column('password_hash', sa.String(length=500), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_table('account_action_tokens',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('purpose', sa.String(length=40), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_account_action_tokens_expires_at'), 'account_action_tokens', ['expires_at'], unique=False)
    op.create_index(op.f('ix_account_action_tokens_purpose'), 'account_action_tokens', ['purpose'], unique=False)
    op.create_index(op.f('ix_account_action_tokens_token_hash'), 'account_action_tokens', ['token_hash'], unique=True)
    op.create_index(op.f('ix_account_action_tokens_user_id'), 'account_action_tokens', ['user_id'], unique=False)
    op.create_index('ix_account_action_tokens_user_purpose', 'account_action_tokens', ['user_id', 'purpose'], unique=False)
    op.create_table('auth_sessions',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_auth_sessions_expires_at'), 'auth_sessions', ['expires_at'], unique=False)
    op.create_index(op.f('ix_auth_sessions_token_hash'), 'auth_sessions', ['token_hash'], unique=True)
    op.create_index(op.f('ix_auth_sessions_user_id'), 'auth_sessions', ['user_id'], unique=False)
    op.create_table('bank_sync_accounts',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('connection_id', sa.UUID(), nullable=False),
    sa.Column('external_id', sa.String(length=120), nullable=False),
    sa.Column('name', sa.String(length=320), nullable=True),
    sa.Column('iban', sa.String(length=64), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['connection_id'], ['bank_sync_connections.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('connection_id', 'external_id', name='uq_bank_sync_account_external')
    )
    op.create_index('ix_bank_sync_accounts_org', 'bank_sync_accounts', ['organization_id'], unique=False)
    op.create_table('billing_cycles',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('subscription_id', sa.UUID(), nullable=True),
    sa.Column('billing_key', sa.String(length=200), nullable=False),
    sa.Column('operation', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('provider_environment', sa.String(length=20), nullable=False),
    sa.Column('product_id', sa.String(length=200), nullable=False),
    sa.Column('tariff_version', sa.String(length=40), nullable=False),
    sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('period_end', sa.DateTime(timezone=True), nullable=False),
    sa.Column('gross_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('tax_rate', sa.Numeric(precision=7, scale=3), nullable=False),
    sa.Column('tax_scheme', sa.String(length=30), nullable=False),
    sa.Column('tax_treatment', sa.String(length=40), nullable=False),
    sa.Column('tax_rule_version', sa.String(length=80), nullable=False),
    sa.Column('recipient_json', sa.Text(), nullable=False),
    sa.Column('retry_count', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("operation IN ('initial','renewal')", name='ck_billing_cycle_operation'),
    sa.CheckConstraint("provider IN ('mollie')", name='ck_billing_cycle_provider'),
    sa.CheckConstraint("provider_environment IN ('test','live')", name='ck_billing_cycle_environment'),
    sa.CheckConstraint("status IN ('prepared','payment_pending','paid','failed','cancelled')", name='ck_billing_cycle_status'),
    sa.CheckConstraint('gross_amount >= 0', name='ck_billing_cycle_gross_nonnegative'),
    sa.CheckConstraint('period_end > period_start', name='ck_billing_cycle_period'),
    sa.CheckConstraint('retry_count >= 0', name='ck_billing_cycle_retry_nonnegative'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['subscription_id'], ['store_subscriptions.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('billing_key'),
    sa.UniqueConstraint('organization_id', 'provider', 'product_id', 'period_start', name='uq_billing_cycle_org_provider_product_period')
    )
    op.create_index('ix_billing_cycle_due', 'billing_cycles', ['status', 'period_start'], unique=False)
    op.create_index(op.f('ix_billing_cycles_status'), 'billing_cycles', ['status'], unique=False)
    op.create_index(op.f('ix_billing_cycles_subscription_id'), 'billing_cycles', ['subscription_id'], unique=False)
    op.create_table('collections',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('participant_list_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('send_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('communication_channel', sa.String(length=30), nullable=False),
    sa.Column('message_template_id', sa.UUID(), nullable=True),
    sa.Column('message_overrides_json', sa.Text(), nullable=True),
    sa.Column('reminder_rules_json', sa.Text(), nullable=False),
    sa.Column('message_include_payment_link', sa.Boolean(), nullable=True),
    sa.Column('message_include_payment_qr', sa.Boolean(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("communication_channel IN ('auto','email','whatsapp','sms','telegram')", name='ck_collections_communication_channel'),
    sa.CheckConstraint('amount > 0', name='ck_collections_amount_positive'),
    sa.ForeignKeyConstraint(['message_template_id'], ['message_templates.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['participant_list_id'], ['participant_lists.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'name', name='uq_collections_org_name')
    )
    op.create_index('ix_collections_message_template_id', 'collections', ['message_template_id'], unique=False)
    op.create_index('ix_collections_org_created', 'collections', ['organization_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_collections_status'), 'collections', ['status'], unique=False)
    op.create_table('communication_channel_settings',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('channel', sa.String(length=30), nullable=False),
    sa.Column('mode', sa.String(length=20), nullable=False),
    sa.Column('provider', sa.String(length=40), nullable=True),
    sa.Column('connection_id', sa.UUID(), nullable=True),
    sa.Column('sender', sa.String(length=320), nullable=True),
    sa.Column('encrypted_config', sa.Text(), nullable=True),
    sa.Column('sync_cursor', sa.String(length=200), nullable=True),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('last_tested_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['connection_id'], ['communication_connections.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'channel', name='uq_comm_channel_org_channel')
    )
    op.create_index('ix_comm_channel_settings_connection', 'communication_channel_settings', ['connection_id'], unique=False)
    op.create_table('participants',
    sa.Column('list_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=True),
    sa.Column('phone', sa.String(length=50), nullable=True),
    sa.Column('channel_addresses_json', sa.Text(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['list_id'], ['participant_lists.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_participants_list_name', 'participants', ['list_id', 'name'], unique=False)
    op.create_table('platform_admin_audit',
    sa.Column('admin_user_id', sa.UUID(), nullable=True),
    sa.Column('organization_id', sa.UUID(), nullable=True),
    sa.Column('action', sa.String(length=80), nullable=False),
    sa.Column('details_json', sa.Text(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['admin_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_platform_admin_audit_action'), 'platform_admin_audit', ['action'], unique=False)
    op.create_index(op.f('ix_platform_admin_audit_admin_user_id'), 'platform_admin_audit', ['admin_user_id'], unique=False)
    op.create_index(op.f('ix_platform_admin_audit_organization_id'), 'platform_admin_audit', ['organization_id'], unique=False)
    op.create_table('billing_payment_transactions',
    sa.Column('cycle_id', sa.UUID(), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('provider_environment', sa.String(length=20), nullable=False),
    sa.Column('attempt', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('sequence_type', sa.String(length=20), nullable=False),
    sa.Column('idempotency_key', sa.UUID(), nullable=False),
    sa.Column('provider_reference', sa.String(length=200), nullable=True),
    sa.Column('gross_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("provider IN ('mollie')", name='ck_billing_payment_provider'),
    sa.CheckConstraint("provider_environment IN ('test','live')", name='ck_billing_payment_environment'),
    sa.CheckConstraint("sequence_type IN ('first','recurring')", name='ck_billing_payment_sequence'),
    sa.CheckConstraint("status IN ('reserved','open','pending','paid','failed','cancelled','expired')", name='ck_billing_payment_status'),
    sa.CheckConstraint('attempt > 0', name='ck_billing_payment_attempt_positive'),
    sa.CheckConstraint('gross_amount >= 0', name='ck_billing_payment_gross_nonnegative'),
    sa.ForeignKeyConstraint(['cycle_id'], ['billing_cycles.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('cycle_id', 'attempt', name='uq_billing_payment_cycle_attempt')
    )
    op.create_index('ix_billing_payment_cycle_status', 'billing_payment_transactions', ['cycle_id', 'status'], unique=False)
    op.create_index(op.f('ix_billing_payment_transactions_provider_reference'), 'billing_payment_transactions', ['provider_reference'], unique=True)
    op.create_index(op.f('ix_billing_payment_transactions_status'), 'billing_payment_transactions', ['status'], unique=False)
    op.create_table('collection_participants',
    sa.Column('collection_id', sa.UUID(), nullable=False),
    sa.Column('participant_id', sa.UUID(), nullable=False),
    sa.Column('payment_reference', sa.String(length=80), nullable=False),
    sa.Column('public_token', sa.String(length=80), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('initial_sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_reminder_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reminder_count', sa.Integer(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('reminder_count >= 0', name='ck_collection_participant_reminder_count'),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['participant_id'], ['participants.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('collection_id', 'participant_id', name='uq_collection_participant_identity'),
    sa.UniqueConstraint('payment_reference')
    )
    op.create_index('ix_collection_participants_collection_status', 'collection_participants', ['collection_id', 'status'], unique=False)
    op.create_index(op.f('ix_collection_participants_public_token'), 'collection_participants', ['public_token'], unique=True)
    op.create_index(op.f('ix_collection_participants_status'), 'collection_participants', ['status'], unique=False)
    op.create_table('participant_channel_settings',
    sa.Column('participant_id', sa.UUID(), nullable=False),
    sa.Column('channel', sa.String(length=30), nullable=False),
    sa.Column('availability', sa.String(length=20), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('last_failure_reason', sa.Text(), nullable=True),
    sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("availability IN ('unknown','available','unavailable')", name='ck_participant_channel_settings_availability'),
    sa.CheckConstraint("channel IN ('email','sms','whatsapp','telegram')", name='ck_participant_channel_settings_channel'),
    sa.ForeignKeyConstraint(['participant_id'], ['participants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('participant_id', 'channel', name='uq_participant_channel_setting_participant_channel')
    )
    op.create_index('ix_participant_channel_settings_participant', 'participant_channel_settings', ['participant_id'], unique=False)
    op.create_table('participant_preferences',
    sa.Column('participant_id', sa.UUID(), nullable=False),
    sa.Column('locale', sa.String(length=10), nullable=False),
    sa.CheckConstraint("locale IN ('bg','hr','cs','da','nl','en','et','fi','fr','de','el','hu','ga','it','lv','lt','mt','pl','pt','ro','sk','sl','es','sv')", name='ck_participant_preferences_locale'),
    sa.ForeignKeyConstraint(['participant_id'], ['participants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('participant_id')
    )
    op.create_table('billing_invoices',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('billing_cycle_id', sa.UUID(), nullable=True),
    sa.Column('payment_transaction_id', sa.UUID(), nullable=True),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('product_id', sa.String(length=200), nullable=False),
    sa.Column('tariff_version', sa.String(length=40), nullable=False),
    sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('period_end', sa.DateTime(timezone=True), nullable=False),
    sa.Column('net_amount', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('tax_amount', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('gross_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('vat_rate', sa.Numeric(precision=7, scale=3), nullable=False),
    sa.Column('vat_scheme', sa.String(length=30), nullable=False),
    sa.Column('tax_treatment', sa.String(length=40), nullable=False),
    sa.Column('recipient_country', sa.String(length=2), nullable=False),
    sa.Column('recipient_type', sa.String(length=20), nullable=False),
    sa.Column('recipient_vat_number', sa.String(length=40), nullable=True),
    sa.Column('seller_legal_name', sa.String(length=240), nullable=True),
    sa.Column('seller_country', sa.String(length=2), nullable=True),
    sa.Column('seller_vat_number', sa.String(length=40), nullable=True),
    sa.Column('idempotency_key', sa.UUID(), nullable=False),
    sa.Column('external_id', sa.String(length=200), nullable=True),
    sa.Column('invoice_number', sa.String(length=120), nullable=True),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('payment_reference', sa.String(length=200), nullable=True),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('details_json', sa.Text(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['billing_cycle_id'], ['billing_cycles.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['payment_transaction_id'], ['billing_payment_transactions.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'provider', 'product_id', 'period_start', name='uq_billing_invoice_org_provider_product_period')
    )
    op.create_index('ix_billing_invoice_org_period', 'billing_invoices', ['organization_id', 'period_start'], unique=False)
    op.create_index('ix_billing_invoice_status_period', 'billing_invoices', ['status', 'period_end'], unique=False)
    op.create_index(op.f('ix_billing_invoices_billing_cycle_id'), 'billing_invoices', ['billing_cycle_id'], unique=False)
    op.create_index(op.f('ix_billing_invoices_external_id'), 'billing_invoices', ['external_id'], unique=True)
    op.create_index(op.f('ix_billing_invoices_payment_reference'), 'billing_invoices', ['payment_reference'], unique=False)
    op.create_index(op.f('ix_billing_invoices_payment_transaction_id'), 'billing_invoices', ['payment_transaction_id'], unique=False)
    op.create_index(op.f('ix_billing_invoices_status'), 'billing_invoices', ['status'], unique=False)
    op.create_table('communication_messages',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('collection_id', sa.UUID(), nullable=False),
    sa.Column('collection_participant_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('channel', sa.String(length=30), nullable=False),
    sa.Column('delivery_mode', sa.String(length=20), nullable=False),
    sa.Column('direction', sa.String(length=20), nullable=False),
    sa.Column('sender', sa.String(length=320), nullable=True),
    sa.Column('recipient', sa.String(length=320), nullable=True),
    sa.Column('subject', sa.String(length=500), nullable=True),
    sa.Column('body', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('provider', sa.String(length=40), nullable=True),
    sa.Column('external_id', sa.String(length=500), nullable=True),
    sa.Column('in_reply_to', sa.String(length=500), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('metadata_json', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['collection_participant_id'], ['collection_participants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_communication_messages_collection_participant', 'communication_messages', ['collection_participant_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_communication_messages_external_id'), 'communication_messages', ['external_id'], unique=False)
    op.create_index(op.f('ix_communication_messages_in_reply_to'), 'communication_messages', ['in_reply_to'], unique=False)
    op.create_index(op.f('ix_communication_messages_status'), 'communication_messages', ['status'], unique=False)
    op.create_table('online_payment_attempts',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('collection_participant_id', sa.UUID(), nullable=False),
    sa.Column('connection_id', sa.UUID(), nullable=False),
    sa.Column('provider', sa.String(length=40), nullable=False),
    sa.Column('external_id', sa.String(length=200), nullable=True),
    sa.Column('webhook_key', sa.String(length=80), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('checkout_url', sa.Text(), nullable=True),
    sa.Column('payment_method', sa.String(length=80), nullable=True),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['collection_participant_id'], ['collection_participants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['connection_id'], ['online_payment_connections.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_online_payment_attempts_connection_external', 'online_payment_attempts', ['connection_id', 'external_id'], unique=False)
    op.create_index(op.f('ix_online_payment_attempts_external_id'), 'online_payment_attempts', ['external_id'], unique=False)
    op.create_index('ix_online_payment_attempts_participant_created', 'online_payment_attempts', ['collection_participant_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_online_payment_attempts_status'), 'online_payment_attempts', ['status'], unique=False)
    op.create_index(op.f('ix_online_payment_attempts_webhook_key'), 'online_payment_attempts', ['webhook_key'], unique=True)
    op.create_table('payments',
    sa.Column('collection_participant_id', sa.UUID(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('method', sa.String(length=30), nullable=False),
    sa.Column('provider', sa.String(length=50), nullable=True),
    sa.Column('external_reference', sa.String(length=200), nullable=True),
    sa.Column('booked_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('details', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['collection_participant_id'], ['collection_participants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_payments_external_reference'), 'payments', ['external_reference'], unique=False)
    op.create_table('bank_transactions',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('import_id', sa.UUID(), nullable=True),
    sa.Column('bank_sync_account_id', sa.UUID(), nullable=True),
    sa.Column('source_provider', sa.String(length=40), nullable=True),
    sa.Column('booked_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('counterparty_name', sa.String(length=300), nullable=True),
    sa.Column('reference', sa.Text(), nullable=True),
    sa.Column('bank_transaction_id', sa.String(length=300), nullable=True),
    sa.Column('fingerprint', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('candidate_collection_participant_id', sa.UUID(), nullable=True),
    sa.Column('match_confidence', sa.Numeric(precision=5, scale=4), nullable=True),
    sa.Column('match_reason', sa.String(length=200), nullable=True),
    sa.Column('applied_payment_id', sa.UUID(), nullable=True),
    sa.Column('raw_details', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['applied_payment_id'], ['payments.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['bank_sync_account_id'], ['bank_sync_accounts.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['candidate_collection_participant_id'], ['collection_participants.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['import_id'], ['bank_statement_imports.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'fingerprint', name='uq_bank_transaction_org_fingerprint')
    )
    op.create_index(op.f('ix_bank_transactions_booked_at'), 'bank_transactions', ['booked_at'], unique=False)
    op.create_index('ix_bank_transactions_import_status', 'bank_transactions', ['import_id', 'status'], unique=False)
    op.create_index(op.f('ix_bank_transactions_status'), 'bank_transactions', ['status'], unique=False)
    op.create_index('ix_bank_transactions_sync_account', 'bank_transactions', ['bank_sync_account_id'], unique=False)


def downgrade() -> None:
    # Going below the baseline would drop every table and all data with it.
    raise NotImplementedError("The baseline revision cannot be downgraded")
