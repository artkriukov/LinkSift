"""add processing worker leases

Revision ID: 20260917_0003
Revises: 20260917_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260917_0003"
down_revision: str | None = "20260917_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("processing_attempts", sa.Column("worker_id", sa.Text(), nullable=True))
    op.add_column(
        "processing_attempts",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "processing_attempts",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "processing_attempts",
        sa.Column("claim_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        "ck_processing_attempts_claim_count", "processing_attempts", "claim_count >= 0"
    )
    op.create_index(
        "ix_processing_attempts_claimable",
        "processing_attempts",
        ["created_at"],
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
    )


def downgrade() -> None:
    op.drop_index("ix_processing_attempts_claimable", table_name="processing_attempts")
    op.drop_constraint("ck_processing_attempts_claim_count", "processing_attempts", type_="check")
    op.drop_column("processing_attempts", "claim_count")
    op.drop_column("processing_attempts", "heartbeat_at")
    op.drop_column("processing_attempts", "lease_expires_at")
    op.drop_column("processing_attempts", "worker_id")
