import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class MaterialRow(Base):
    __tablename__ = "materials"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('upload', 'youtube', 'instagram_reel', 'article', "
            "'direct_media', 'text')",
            name="ck_materials_source_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed', 'deleted')",
            name="ck_materials_status",
        ),
        CheckConstraint("btrim(source_key) <> ''", name="ck_materials_source_key_not_blank"),
        Index(
            "uq_materials_owner_source_active",
            "owner_telegram_id",
            "source_key",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND status <> 'deleted'"),
        ),
        Index(
            "ix_materials_owner_created_active",
            "owner_telegram_id",
            text("created_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_materials_status_active",
            "status",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_materials_source_key", "source_key"),
        Index(
            "ix_materials_deleted_at",
            "deleted_at",
            postgresql_where=text("deleted_at IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    owner_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_key: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProcessingAttemptRow(Base):
    __tablename__ = "processing_attempts"
    __table_args__ = (
        CheckConstraint("attempt_number > 0", name="ck_processing_attempts_number"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_processing_attempts_status",
        ),
        UniqueConstraint(
            "material_id", "attempt_number", name="uq_processing_attempts_material_number"
        ),
        Index("ix_processing_attempts_material", "material_id", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    material_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("materials.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending", server_default="pending"
    )
    pipeline_version: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AnalysisResultRow(Base):
    __tablename__ = "analysis_results"
    __table_args__ = (UniqueConstraint("attempt_id", name="uq_analysis_results_attempt"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("processing_attempts.id", ondelete="CASCADE"), nullable=False
    )
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    transcript: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    provider_usage: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
