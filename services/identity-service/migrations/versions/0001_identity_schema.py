"""M02 identity schema: persons, credentials, memberships, consents, tokens, guardianships.

Revision ID: 0001_identity_schema
Revises:
Create Date: 2026-07-21

Creates the identity-service tables per M02 §9. Depends on the M01 base
migration (`tenants` table must exist for the FK on memberships and consents).

Table ownership:

- persons          global (no tenant_id) — enables portable identity (ENG-002)
- credentials      global (attached to persons)
- tokens           global (attached to persons)
- guardianships    global (person-to-person link)
- memberships      tenant-scoped — RLS + tenant_isolation policy
- consents         tenant-scoped where consent is per-tenant (e.g. sharing
                   with a specific coach); global consents (data storage,
                   parental) leave tenant_id NULL (allowed via nullable FK)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from cip_data.rls import (
    disable_rls_statements,
    drop_tenant_isolation_policy_sql,
    enable_rls_statements,
    tenant_isolation_policy_sql,
)

revision: str = "0001_identity_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TENANT_SCOPED_TABLES = ("memberships",)  # consents stays global for M02


def upgrade() -> None:
    # persons — global identity, portable across tenants (ENG-002).
    op.create_table(
        "persons",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column(
            "status",
            sa.Text,
            nullable=False,
            server_default=sa.text("'pending_verification'"),
        ),
        sa.Column("dob_band", sa.Text, nullable=True),  # 'adult' | 'minor' | null
        sa.Column("display_name", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint("uq_persons_email", "persons", ["email"])
    op.create_index("ix_persons_status", "persons", ["status"])

    # credentials — password hash OR OAuth provider linkage.
    op.create_table(
        "credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("persons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.Text, nullable=False),  # 'password' | 'oauth'
        sa.Column("password_hash", sa.Text, nullable=True),  # populated when type='password'
        sa.Column("provider", sa.Text, nullable=True),  # 'google' | 'microsoft' | ...
        sa.Column("provider_subject", sa.Text, nullable=True),  # OAuth 'sub' claim
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_credentials_person_id", "credentials", ["person_id"])
    op.create_unique_constraint(
        "uq_credentials_provider_subject",
        "credentials",
        ["provider", "provider_subject"],
    )

    # memberships — person <-> tenant with a role (RBAC). Tenant-scoped.
    op.create_table(
        "memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("persons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column(
            "status",
            sa.Text,
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_memberships_tenant_id", "memberships", ["tenant_id"])
    op.create_index("ix_memberships_person_id", "memberships", ["person_id"])
    op.create_unique_constraint(
        "uq_memberships_person_tenant",
        "memberships",
        ["person_id", "tenant_id"],
    )

    # consents — global by default; tenant_id populated for scoped consents
    # (e.g. 'share analysis with coach at tenant X'). Global consents
    # (guardian consent to processing, storage-consent) leave tenant_id NULL.
    op.create_table(
        "consents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("persons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("type", sa.Text, nullable=False),  # 'processing' | 'sharing' | ...
        sa.Column(
            "granted_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("persons.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "scope",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index("ix_consents_person_id", "consents", ["person_id"])

    # tokens — refresh/session token registry so we can revoke.
    op.create_table(
        "tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("persons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text, nullable=False),  # 'refresh' | 'reset' | 'verify'
        sa.Column("token_hash", sa.Text, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "revoked",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_tokens_person_id", "tokens", ["person_id"])
    op.create_index("ix_tokens_hash", "tokens", ["token_hash"])

    # guardianships — verified minor <-> guardian link.
    op.create_table(
        "guardianships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "minor_person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("persons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "guardian_person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("persons.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "verified",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint(
        "uq_guardianships_pair",
        "guardianships",
        ["minor_person_id", "guardian_person_id"],
    )

    # RLS on the tenant-scoped tables (memberships).
    for table in TENANT_SCOPED_TABLES:
        for stmt in enable_rls_statements(table):
            op.execute(stmt)
        op.execute(tenant_isolation_policy_sql(table))
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cip_app")

    # Grant privileges on the global tables to cip_app too.
    for table in ("persons", "credentials", "consents", "tokens", "guardianships"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cip_app")


def downgrade() -> None:
    for table in TENANT_SCOPED_TABLES:
        op.execute(drop_tenant_isolation_policy_sql(table))
        for stmt in disable_rls_statements(table):
            op.execute(stmt)

    op.drop_constraint("uq_guardianships_pair", "guardianships", type_="unique")
    op.drop_table("guardianships")

    op.drop_index("ix_tokens_hash", table_name="tokens")
    op.drop_index("ix_tokens_person_id", table_name="tokens")
    op.drop_table("tokens")

    op.drop_index("ix_consents_person_id", table_name="consents")
    op.drop_table("consents")

    op.drop_constraint("uq_memberships_person_tenant", "memberships", type_="unique")
    op.drop_index("ix_memberships_person_id", table_name="memberships")
    op.drop_index("ix_memberships_tenant_id", table_name="memberships")
    op.drop_table("memberships")

    op.drop_constraint("uq_credentials_provider_subject", "credentials", type_="unique")
    op.drop_index("ix_credentials_person_id", table_name="credentials")
    op.drop_table("credentials")

    op.drop_index("ix_persons_status", table_name="persons")
    op.drop_constraint("uq_persons_email", "persons", type_="unique")
    op.drop_table("persons")
