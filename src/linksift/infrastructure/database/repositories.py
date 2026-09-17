import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from linksift.application.repositories import (
    AttemptNotFoundError,
    DatabaseOperationError,
    DuplicateMaterialError,
    InvalidStateTransitionError,
    MaterialNotFoundError,
)
from linksift.domain.models import (
    AnalysisResult,
    Material,
    ProcessingAttempt,
    SourceType,
    StoredAnalysisResult,
    Transcript,
)
from linksift.infrastructure.database.mappings import to_attempt, to_material, to_stored_result
from linksift.infrastructure.database.models import (
    AnalysisResultRow,
    MaterialRow,
    ProcessingAttemptRow,
)

_DATABASE_URL_PATTERN = re.compile(r"postgres(?:ql)?(?:\+psycopg)?://\S+", re.IGNORECASE)


def _safe_error_message(message: str) -> str:
    return _DATABASE_URL_PATTERN.sub("[database-url-redacted]", message)[:2000]


class SqlAlchemyMaterialRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_material(
        self,
        *,
        owner_telegram_id: int,
        source_type: SourceType,
        source_key: str,
        source_url: str | None = None,
        title: str | None = None,
    ) -> Material:
        try:
            async with self._session_factory() as session, session.begin():
                row = MaterialRow(
                    owner_telegram_id=owner_telegram_id,
                    source_type=source_type,
                    source_url=source_url,
                    source_key=source_key,
                    title=title,
                    status="pending",
                )
                session.add(row)
                await session.flush()
                return to_material(row)
        except IntegrityError:
            raise DuplicateMaterialError(
                "An active material with this source already exists"
            ) from None
        except SQLAlchemyError:
            raise DatabaseOperationError("Could not create material") from None

    async def get_existing_material(
        self, *, owner_telegram_id: int, source_key: str
    ) -> Material | None:
        try:
            async with self._session_factory() as session, session.begin():
                row = await session.scalar(
                    select(MaterialRow).where(
                        MaterialRow.owner_telegram_id == owner_telegram_id,
                        MaterialRow.source_key == source_key,
                        MaterialRow.deleted_at.is_(None),
                        MaterialRow.status != "deleted",
                    )
                )
                return to_material(row) if row is not None else None
        except SQLAlchemyError:
            raise DatabaseOperationError("Could not read material") from None

    async def get_material(self, *, material_id: UUID, owner_telegram_id: int) -> Material | None:
        try:
            async with self._session_factory() as session, session.begin():
                row = await self._material_for_owner(
                    session, material_id=material_id, owner_telegram_id=owner_telegram_id
                )
                return to_material(row) if row is not None else None
        except SQLAlchemyError:
            raise DatabaseOperationError("Could not read material") from None

    async def list_history(
        self, *, owner_telegram_id: int, limit: int = 50, offset: int = 0
    ) -> list[Material]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("limit must be 1..100 and offset must be non-negative")
        try:
            async with self._session_factory() as session, session.begin():
                rows = (
                    await session.scalars(
                        select(MaterialRow)
                        .where(
                            MaterialRow.owner_telegram_id == owner_telegram_id,
                            MaterialRow.deleted_at.is_(None),
                            MaterialRow.status != "deleted",
                        )
                        .order_by(MaterialRow.created_at.desc(), MaterialRow.id.desc())
                        .limit(limit)
                        .offset(offset)
                    )
                ).all()
                return [to_material(row) for row in rows]
        except SQLAlchemyError:
            raise DatabaseOperationError("Could not list material history") from None

    async def create_attempt(
        self, *, material_id: UUID, owner_telegram_id: int, pipeline_version: str
    ) -> ProcessingAttempt:
        try:
            async with self._session_factory() as session, session.begin():
                material = await self._required_material(
                    session,
                    material_id=material_id,
                    owner_telegram_id=owner_telegram_id,
                    for_update=True,
                )
                if material.status != "pending":
                    raise InvalidStateTransitionError(
                        f"Cannot create an attempt while material is {material.status}"
                    )
                row = await self._add_attempt(
                    session, material_id=material.id, pipeline_version=pipeline_version
                )
                return to_attempt(row)
        except SQLAlchemyError:
            raise DatabaseOperationError("Could not create processing attempt") from None

    async def mark_processing(
        self, *, material_id: UUID, attempt_id: UUID, owner_telegram_id: int
    ) -> ProcessingAttempt:
        try:
            async with self._session_factory() as session, session.begin():
                material = await self._required_material(
                    session,
                    material_id=material_id,
                    owner_telegram_id=owner_telegram_id,
                    for_update=True,
                )
                attempt = await self._required_attempt(
                    session, material_id=material.id, attempt_id=attempt_id, for_update=True
                )
                if material.status != "pending" or attempt.status != "pending":
                    raise InvalidStateTransitionError("Only pending work can start processing")
                now = datetime.now(UTC)
                material.status = "processing"
                material.updated_at = now
                attempt.status = "processing"
                attempt.started_at = now
                await session.flush()
                return to_attempt(attempt)
        except SQLAlchemyError:
            raise DatabaseOperationError("Could not start processing") from None

    async def save_result(
        self,
        *,
        material_id: UUID,
        attempt_id: UUID,
        owner_telegram_id: int,
        result: AnalysisResult,
        transcript: Transcript | None,
        provider_usage: Mapping[str, Any],
    ) -> StoredAnalysisResult:
        validated_result = AnalysisResult.model_validate(result)
        validated_transcript = (
            Transcript.model_validate(transcript) if transcript is not None else None
        )
        try:
            async with self._session_factory() as session, session.begin():
                material = await self._required_material(
                    session,
                    material_id=material_id,
                    owner_telegram_id=owner_telegram_id,
                    for_update=True,
                )
                attempt = await self._required_attempt(
                    session, material_id=material.id, attempt_id=attempt_id, for_update=True
                )
                if material.status != "processing" or attempt.status != "processing":
                    raise InvalidStateTransitionError("Only processing work can be completed")

                stored = AnalysisResultRow(
                    attempt_id=attempt.id,
                    result=validated_result.model_dump(mode="json"),
                    transcript=(
                        validated_transcript.model_dump(mode="json")
                        if validated_transcript is not None
                        else None
                    ),
                    provider_usage=dict(provider_usage),
                )
                session.add(stored)
                now = datetime.now(UTC)
                material.status = "completed"
                material.updated_at = now
                attempt.status = "completed"
                attempt.finished_at = now
                await session.flush()
                return to_stored_result(stored)
        except IntegrityError:
            raise InvalidStateTransitionError("This attempt already has a result") from None
        except SQLAlchemyError:
            raise DatabaseOperationError("Could not save analysis result") from None

    async def save_failure(
        self,
        *,
        material_id: UUID,
        attempt_id: UUID,
        owner_telegram_id: int,
        error_code: str,
        error_message: str,
    ) -> ProcessingAttempt:
        try:
            async with self._session_factory() as session, session.begin():
                material = await self._required_material(
                    session,
                    material_id=material_id,
                    owner_telegram_id=owner_telegram_id,
                    for_update=True,
                )
                attempt = await self._required_attempt(
                    session, material_id=material.id, attempt_id=attempt_id, for_update=True
                )
                if material.status != "processing" or attempt.status != "processing":
                    raise InvalidStateTransitionError("Only processing work can fail")
                now = datetime.now(UTC)
                material.status = "failed"
                material.updated_at = now
                attempt.status = "failed"
                attempt.error_code = error_code[:200]
                attempt.error_message = _safe_error_message(error_message)
                attempt.finished_at = now
                await session.flush()
                return to_attempt(attempt)
        except SQLAlchemyError:
            raise DatabaseOperationError("Could not save processing failure") from None

    async def soft_delete(self, *, material_id: UUID, owner_telegram_id: int) -> Material:
        try:
            async with self._session_factory() as session, session.begin():
                material = await self._required_material(
                    session,
                    material_id=material_id,
                    owner_telegram_id=owner_telegram_id,
                    for_update=True,
                )
                now = datetime.now(UTC)
                material.status = "deleted"
                material.deleted_at = now
                material.updated_at = now
                await session.flush()
                return to_material(material)
        except SQLAlchemyError:
            raise DatabaseOperationError("Could not delete material") from None

    async def retry_material(
        self, *, material_id: UUID, owner_telegram_id: int, pipeline_version: str
    ) -> ProcessingAttempt:
        try:
            async with self._session_factory() as session, session.begin():
                material = await self._required_material(
                    session,
                    material_id=material_id,
                    owner_telegram_id=owner_telegram_id,
                    for_update=True,
                )
                if material.status not in {"failed", "completed"}:
                    raise InvalidStateTransitionError(
                        "Only failed or completed materials can be retried"
                    )
                material.status = "pending"
                material.updated_at = datetime.now(UTC)
                attempt = await self._add_attempt(
                    session, material_id=material.id, pipeline_version=pipeline_version
                )
                await session.flush()
                return to_attempt(attempt)
        except SQLAlchemyError:
            raise DatabaseOperationError("Could not retry material") from None

    @staticmethod
    async def _material_for_owner(
        session: AsyncSession,
        *,
        material_id: UUID,
        owner_telegram_id: int,
        for_update: bool = False,
    ) -> MaterialRow | None:
        query = select(MaterialRow).where(
            MaterialRow.id == material_id,
            MaterialRow.owner_telegram_id == owner_telegram_id,
            MaterialRow.deleted_at.is_(None),
            MaterialRow.status != "deleted",
        )
        if for_update:
            query = query.with_for_update()
        return await session.scalar(query)

    async def _required_material(
        self,
        session: AsyncSession,
        *,
        material_id: UUID,
        owner_telegram_id: int,
        for_update: bool = False,
    ) -> MaterialRow:
        row = await self._material_for_owner(
            session,
            material_id=material_id,
            owner_telegram_id=owner_telegram_id,
            for_update=for_update,
        )
        if row is None:
            raise MaterialNotFoundError("Material not found")
        return row

    @staticmethod
    async def _required_attempt(
        session: AsyncSession,
        *,
        material_id: UUID,
        attempt_id: UUID,
        for_update: bool = False,
    ) -> ProcessingAttemptRow:
        query = select(ProcessingAttemptRow).where(
            ProcessingAttemptRow.id == attempt_id,
            ProcessingAttemptRow.material_id == material_id,
        )
        if for_update:
            query = query.with_for_update()
        row = await session.scalar(query)
        if row is None:
            raise AttemptNotFoundError("Processing attempt not found")
        return row

    @staticmethod
    async def _add_attempt(
        session: AsyncSession, *, material_id: UUID, pipeline_version: str
    ) -> ProcessingAttemptRow:
        last_number = await session.scalar(
            select(func.max(ProcessingAttemptRow.attempt_number)).where(
                ProcessingAttemptRow.material_id == material_id
            )
        )
        row = ProcessingAttemptRow(
            material_id=material_id,
            attempt_number=(last_number or 0) + 1,
            status="pending",
            pipeline_version=pipeline_version,
        )
        session.add(row)
        await session.flush()
        return row
