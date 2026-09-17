from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from linksift.application.repositories import (
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


class FakeMaterialRepository:
    def __init__(self) -> None:
        self.materials: dict[UUID, Material] = {}
        self.attempts: dict[UUID, ProcessingAttempt] = {}
        self.results: dict[UUID, StoredAnalysisResult] = {}

    async def create_material(
        self,
        *,
        owner_telegram_id: int,
        source_type: SourceType,
        source_key: str,
        source_url: str | None = None,
        title: str | None = None,
    ) -> Material:
        if await self.get_existing_material(
            owner_telegram_id=owner_telegram_id, source_key=source_key
        ):
            raise DuplicateMaterialError("duplicate")
        now = datetime.now(UTC)
        material = Material(
            id=uuid4(),
            owner_telegram_id=owner_telegram_id,
            source_type=source_type,
            source_url=source_url,
            source_key=source_key,
            title=title,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        self.materials[material.id] = material
        return material

    async def get_existing_material(
        self, *, owner_telegram_id: int, source_key: str
    ) -> Material | None:
        return next(
            (
                material
                for material in self.materials.values()
                if material.owner_telegram_id == owner_telegram_id
                and material.source_key == source_key
                and material.status != "deleted"
            ),
            None,
        )

    async def get_material(self, *, material_id: UUID, owner_telegram_id: int) -> Material | None:
        material = self.materials.get(material_id)
        if (
            material is None
            or material.owner_telegram_id != owner_telegram_id
            or material.status == "deleted"
        ):
            return None
        return material

    async def list_history(
        self, *, owner_telegram_id: int, limit: int = 50, offset: int = 0
    ) -> list[Material]:
        rows = sorted(
            (
                material
                for material in self.materials.values()
                if material.owner_telegram_id == owner_telegram_id and material.status != "deleted"
            ),
            key=lambda material: (material.created_at, material.id),
            reverse=True,
        )
        return rows[offset : offset + limit]

    async def create_attempt(
        self, *, material_id: UUID, owner_telegram_id: int, pipeline_version: str
    ) -> ProcessingAttempt:
        material = self._required_material(material_id, owner_telegram_id)
        attempt_number = 1 + max(
            (
                attempt.attempt_number
                for attempt in self.attempts.values()
                if attempt.material_id == material.id
            ),
            default=0,
        )
        attempt = ProcessingAttempt(
            id=uuid4(),
            material_id=material.id,
            attempt_number=attempt_number,
            status="pending",
            pipeline_version=pipeline_version,
            created_at=datetime.now(UTC),
        )
        self.attempts[attempt.id] = attempt
        return attempt

    async def mark_processing(
        self, *, material_id: UUID, attempt_id: UUID, owner_telegram_id: int
    ) -> ProcessingAttempt:
        material = self._required_material(material_id, owner_telegram_id)
        attempt = self.attempts[attempt_id]
        if material.status != "pending" or attempt.status != "pending":
            raise InvalidStateTransitionError("not pending")
        now = datetime.now(UTC)
        self.materials[material.id] = material.model_copy(
            update={"status": "processing", "updated_at": now}
        )
        updated = attempt.model_copy(update={"status": "processing", "started_at": now})
        self.attempts[attempt.id] = updated
        return updated

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
        material = self._required_material(material_id, owner_telegram_id)
        attempt = self.attempts[attempt_id]
        if material.status != "processing" or attempt.status != "processing":
            raise InvalidStateTransitionError("not processing")
        now = datetime.now(UTC)
        self.materials[material.id] = material.model_copy(
            update={"status": "completed", "updated_at": now}
        )
        self.attempts[attempt.id] = attempt.model_copy(
            update={"status": "completed", "finished_at": now}
        )
        stored = StoredAnalysisResult(
            id=uuid4(),
            attempt_id=attempt.id,
            result=AnalysisResult.model_validate(result),
            transcript=transcript,
            provider_usage=dict(provider_usage),
            created_at=now,
        )
        self.results[attempt.id] = stored
        return stored

    async def save_failure(
        self,
        *,
        material_id: UUID,
        attempt_id: UUID,
        owner_telegram_id: int,
        error_code: str,
        error_message: str,
    ) -> ProcessingAttempt:
        material = self._required_material(material_id, owner_telegram_id)
        attempt = self.attempts[attempt_id]
        now = datetime.now(UTC)
        self.materials[material.id] = material.model_copy(
            update={"status": "failed", "updated_at": now}
        )
        updated = attempt.model_copy(
            update={
                "status": "failed",
                "error_code": error_code,
                "error_message": error_message,
                "finished_at": now,
            }
        )
        self.attempts[attempt.id] = updated
        return updated

    async def soft_delete(self, *, material_id: UUID, owner_telegram_id: int) -> Material:
        material = self._required_material(material_id, owner_telegram_id)
        now = datetime.now(UTC)
        deleted = material.model_copy(
            update={"status": "deleted", "deleted_at": now, "updated_at": now}
        )
        self.materials[material.id] = deleted
        return deleted

    async def retry_material(
        self, *, material_id: UUID, owner_telegram_id: int, pipeline_version: str
    ) -> ProcessingAttempt:
        material = self._required_material(material_id, owner_telegram_id)
        if material.status not in {"failed", "completed"}:
            raise InvalidStateTransitionError("not retryable")
        self.materials[material.id] = material.model_copy(
            update={"status": "pending", "updated_at": datetime.now(UTC)}
        )
        return await self.create_attempt(
            material_id=material_id,
            owner_telegram_id=owner_telegram_id,
            pipeline_version=pipeline_version,
        )

    def _required_material(self, material_id: UUID, owner_telegram_id: int) -> Material:
        material = self.materials.get(material_id)
        if (
            material is None
            or material.owner_telegram_id != owner_telegram_id
            or material.status == "deleted"
        ):
            raise MaterialNotFoundError("not found")
        return material
