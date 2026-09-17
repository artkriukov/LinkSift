from collections.abc import Mapping
from typing import Any, Protocol
from uuid import UUID

from linksift.domain.models import (
    AnalysisResult,
    ClaimedProcessingAttempt,
    Material,
    ProcessingAttempt,
    SourceType,
    StoredAnalysisResult,
    Transcript,
)


class RepositoryError(RuntimeError):
    """A safe application error that never contains database credentials."""


class DuplicateMaterialError(RepositoryError):
    pass


class MaterialNotFoundError(RepositoryError):
    pass


class AttemptNotFoundError(RepositoryError):
    pass


class InvalidStateTransitionError(RepositoryError):
    pass


class LeaseLostError(InvalidStateTransitionError):
    pass


class DatabaseOperationError(RepositoryError):
    pass


class MaterialRepository(Protocol):
    async def claim_next_pending(
        self, *, worker_id: str, lease_seconds: int
    ) -> ClaimedProcessingAttempt | None: ...

    async def heartbeat(self, *, attempt_id: UUID, worker_id: str, lease_seconds: int) -> bool: ...

    async def complete_claim(
        self,
        *,
        material_id: UUID,
        attempt_id: UUID,
        worker_id: str,
        result: AnalysisResult,
    ) -> StoredAnalysisResult: ...

    async def fail_claim(
        self,
        *,
        material_id: UUID,
        attempt_id: UUID,
        worker_id: str,
        error_code: str,
        error_message: str,
        retry: bool,
    ) -> ProcessingAttempt: ...
    async def create_material(
        self,
        *,
        owner_telegram_id: int,
        source_type: SourceType,
        source_key: str,
        source_url: str | None = None,
        source_text: str | None = None,
        title: str | None = None,
    ) -> Material: ...

    async def create_material_with_attempt(
        self,
        *,
        owner_telegram_id: int,
        source_type: SourceType,
        source_key: str,
        pipeline_version: str,
        source_url: str | None = None,
        source_text: str | None = None,
        title: str | None = None,
    ) -> tuple[Material, ProcessingAttempt]: ...

    async def get_existing_material(
        self, *, owner_telegram_id: int, source_key: str
    ) -> Material | None: ...

    async def get_material(
        self, *, material_id: UUID, owner_telegram_id: int
    ) -> Material | None: ...

    async def list_history(
        self, *, owner_telegram_id: int, limit: int = 50, offset: int = 0
    ) -> list[Material]: ...

    async def create_attempt(
        self, *, material_id: UUID, owner_telegram_id: int, pipeline_version: str
    ) -> ProcessingAttempt: ...

    async def mark_processing(
        self, *, material_id: UUID, attempt_id: UUID, owner_telegram_id: int
    ) -> ProcessingAttempt: ...

    async def save_result(
        self,
        *,
        material_id: UUID,
        attempt_id: UUID,
        owner_telegram_id: int,
        result: AnalysisResult,
        transcript: Transcript | None,
        provider_usage: Mapping[str, Any],
    ) -> StoredAnalysisResult: ...

    async def save_failure(
        self,
        *,
        material_id: UUID,
        attempt_id: UUID,
        owner_telegram_id: int,
        error_code: str,
        error_message: str,
    ) -> ProcessingAttempt: ...

    async def soft_delete(self, *, material_id: UUID, owner_telegram_id: int) -> Material: ...

    async def retry_material(
        self, *, material_id: UUID, owner_telegram_id: int, pipeline_version: str
    ) -> ProcessingAttempt: ...
