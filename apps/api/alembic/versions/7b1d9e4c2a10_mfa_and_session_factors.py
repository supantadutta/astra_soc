"""MFA (TOTP) on users and second-factor flag on sessions

Revision ID: 7b1d9e4c2a10
Revises: 006c58caeaa0
Create Date: 2026-09-26
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

import astrasoc.db
from alembic import op

revision = "7b1d9e4c2a10"
down_revision = "006c58caeaa0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("mfa_secret_enc", sa.Text(), nullable=True))
        b.add_column(sa.Column("mfa_pending_secret_enc", sa.Text(), nullable=True))
        b.add_column(sa.Column("mfa_recovery_hashes",
                                sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
                                nullable=False, server_default="[]"))
        b.add_column(sa.Column("mfa_last_step", sa.BigInteger(), nullable=True))
        b.add_column(sa.Column("mfa_enrolled_at", astrasoc.db.TZDateTime(timezone=True), nullable=True))
    with op.batch_alter_table("sessions") as b:
        b.add_column(sa.Column("mfa_verified", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("sessions") as b:
        b.drop_column("mfa_verified")
    with op.batch_alter_table("users") as b:
        for col in ("mfa_enrolled_at", "mfa_last_step", "mfa_recovery_hashes",
                    "mfa_pending_secret_enc", "mfa_secret_enc", "mfa_enabled"):
            b.drop_column(col)
