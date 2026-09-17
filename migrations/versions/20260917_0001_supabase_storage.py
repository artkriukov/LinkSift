"""Create Supabase PostgreSQL storage

Revision ID: 20260917_0001
Revises:
Create Date: 2026-09-17
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260917_0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.create_table(
        "materials",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("owner_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "source_type IN ('upload', 'youtube', 'instagram_reel', 'article', "
            "'direct_media', 'text')",
            name="ck_materials_source_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed', 'deleted')",
            name="ck_materials_status",
        ),
        sa.CheckConstraint("btrim(source_key) <> ''", name="ck_materials_source_key_not_blank"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_materials_owner_source_active",
        "materials",
        ["owner_telegram_id", "source_key"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND status <> 'deleted'"),
    )
    op.create_index(
        "ix_materials_owner_created_active",
        "materials",
        ["owner_telegram_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_materials_status_active",
        "materials",
        ["status"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_materials_source_key", "materials", ["source_key"])
    op.create_index(
        "ix_materials_deleted_at",
        "materials",
        ["deleted_at"],
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )

    op.create_table(
        "processing_attempts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("material_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("attempt_number > 0", name="ck_processing_attempts_number"),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_processing_attempts_status",
        ),
        sa.ForeignKeyConstraint(["material_id"], ["materials.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "material_id", "attempt_number", name="uq_processing_attempts_material_number"
        ),
    )
    op.create_index(
        "ix_processing_attempts_material",
        "processing_attempts",
        ["material_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "analysis_results",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("transcript", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "provider_usage",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["attempt_id"], ["processing_attempts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_id", name="uq_analysis_results_attempt"),
    )

    op.execute(
        """
        CREATE FUNCTION public.linksift_set_material_updated_at()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = ''
        AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER materials_set_updated_at
        BEFORE UPDATE ON public.materials
        FOR EACH ROW
        EXECUTE FUNCTION public.linksift_set_material_updated_at()
        """
    )

    # Supabase exposes public tables through its Data API. With RLS enabled and no
    # policies, anon/authenticated API clients cannot read or mutate backend data.
    op.execute("ALTER TABLE public.materials ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.processing_attempts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.analysis_results ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS materials_set_updated_at ON public.materials")
    op.execute("DROP FUNCTION IF EXISTS public.linksift_set_material_updated_at()")
    op.drop_table("analysis_results")
    op.drop_index("ix_processing_attempts_material", table_name="processing_attempts")
    op.drop_table("processing_attempts")
    op.drop_index("ix_materials_deleted_at", table_name="materials")
    op.drop_index("ix_materials_source_key", table_name="materials")
    op.drop_index("ix_materials_status_active", table_name="materials")
    op.drop_index("ix_materials_owner_created_active", table_name="materials")
    op.drop_index("uq_materials_owner_source_active", table_name="materials")
    op.drop_table("materials")
