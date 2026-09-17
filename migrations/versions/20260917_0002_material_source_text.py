"""Add source text to materials.

Revision ID: 20260917_0002
Revises: 20260917_0001
Create Date: 2026-09-17
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20260917_0002"
down_revision: str | None = "20260917_0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("materials", sa.Column("source_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("materials", "source_text")
