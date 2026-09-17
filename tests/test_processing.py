import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from linksift.application.processing import ProcessingService, ProcessingWorker
from linksift.application.processors import ProcessorRouter
from linksift.application.repositories import LeaseLostError
from linksift.domain.models import (
    AnalysisResult,
    ClaimedProcessingAttempt,
    Material,
    ProcessingAttempt,
    StoredAnalysisResult,
)
from tests.test_repository_contract import analysis_result


class WorkerRepository:
    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.material = Material(
            id=uuid4(),
            owner_telegram_id=10,
            source_type="text",
            source_text="private user text",
            source_key="key",
            status="pending",
            created_at=now,
            updated_at=now,
        )
        self.attempt = ProcessingAttempt(
            id=uuid4(),
            material_id=self.material.id,
            attempt_number=1,
            status="pending",
            pipeline_version="test",
            created_at=now,
        )
        self.lock = asyncio.Lock()
        self.saved: AnalysisResult | None = None
        self.claim_calls = 0

    async def claim_next_pending(
        self, *, worker_id: str, lease_seconds: int
    ) -> ClaimedProcessingAttempt | None:
        async with self.lock:
            self.claim_calls += 1
            now = datetime.now(UTC)
            claimable = self.attempt.status == "pending" or (
                self.attempt.status == "processing"
                and self.attempt.lease_expires_at is not None
                and self.attempt.lease_expires_at < now
            )
            if not claimable or self.material.deleted_at is not None:
                return None
            self.material = self.material.model_copy(
                update={"status": "processing", "updated_at": now}
            )
            self.attempt = self.attempt.model_copy(
                update={
                    "status": "processing",
                    "worker_id": worker_id,
                    "lease_expires_at": now + timedelta(seconds=lease_seconds),
                    "heartbeat_at": now,
                    "claim_count": self.attempt.claim_count + 1,
                    "started_at": now,
                }
            )
            return ClaimedProcessingAttempt(material=self.material, attempt=self.attempt)

    async def heartbeat(self, *, attempt_id: UUID, worker_id: str, lease_seconds: int) -> bool:
        if self.attempt.id != attempt_id or self.attempt.worker_id != worker_id:
            return False
        now = datetime.now(UTC)
        self.attempt = self.attempt.model_copy(
            update={
                "heartbeat_at": now,
                "lease_expires_at": now + timedelta(seconds=lease_seconds),
            }
        )
        return True

    def _assert_owner(self, attempt_id: UUID, worker_id: str) -> None:
        if self.attempt.id != attempt_id or self.attempt.worker_id != worker_id:
            raise LeaseLostError("lost")
        if self.attempt.lease_expires_at is None:
            raise LeaseLostError("lost")

    async def complete_claim(
        self,
        *,
        material_id: UUID,
        attempt_id: UUID,
        worker_id: str,
        result: AnalysisResult,
    ) -> StoredAnalysisResult:
        self._assert_owner(attempt_id, worker_id)
        now = datetime.now(UTC)
        self.saved = result
        self.material = self.material.model_copy(update={"status": "completed"})
        self.attempt = self.attempt.model_copy(
            update={
                "status": "completed",
                "finished_at": now,
                "worker_id": None,
                "lease_expires_at": None,
                "heartbeat_at": None,
            }
        )
        return StoredAnalysisResult(
            id=uuid4(), attempt_id=attempt_id, result=result, provider_usage={}, created_at=now
        )

    async def fail_claim(
        self,
        *,
        material_id: UUID,
        attempt_id: UUID,
        worker_id: str,
        error_code: str,
        error_message: str,
        retry: bool,
    ) -> ProcessingAttempt:
        self._assert_owner(attempt_id, worker_id)
        status = "pending" if retry else "failed"
        self.material = self.material.model_copy(update={"status": status})
        self.attempt = self.attempt.model_copy(
            update={
                "status": status,
                "error_code": error_code,
                "error_message": error_message,
                "worker_id": None,
                "lease_expires_at": None,
                "heartbeat_at": None,
            }
        )
        return self.attempt


class SuccessfulProcessor:
    async def process(self, material: Material) -> AnalysisResult:
        return analysis_result()


class SlowProcessor:
    async def process(self, material: Material) -> AnalysisResult:
        await asyncio.sleep(10)
        return analysis_result()


def service(
    repository: WorkerRepository,
    processors: Mapping[str, Any],
    *,
    worker_id: str = "worker-one",
    timeout: float = 1,
) -> ProcessingService:
    return ProcessingService(
        repository,
        ProcessorRouter(processors),  # type: ignore[arg-type]
        worker_id=worker_id,
        lease_seconds=10,
        heartbeat_seconds=1,
        timeout_seconds=timeout,
        max_claims=3,
    )


def test_claim_is_exclusive_and_increments_count() -> None:
    async def run() -> None:
        repository = WorkerRepository()
        first, second = await asyncio.gather(
            repository.claim_next_pending(worker_id="one", lease_seconds=10),
            repository.claim_next_pending(worker_id="two", lease_seconds=10),
        )
        assert (first is None) != (second is None)
        assert repository.material.status == "processing"
        assert repository.attempt.claim_count == 1

    asyncio.run(run())


def test_success_saves_result_and_completes() -> None:
    async def run() -> None:
        repository = WorkerRepository()
        claim = await repository.claim_next_pending(worker_id="worker-one", lease_seconds=10)
        assert claim is not None
        outcome = await service(repository, {"text": SuccessfulProcessor()}).process(claim)
        assert outcome.status == "completed"
        assert repository.material.status == "completed"
        assert repository.saved is not None

    asyncio.run(run())


def test_missing_processor_fails_without_leaking_source_text() -> None:
    async def run() -> None:
        repository = WorkerRepository()
        claim = await repository.claim_next_pending(worker_id="worker-one", lease_seconds=10)
        assert claim is not None
        outcome = await service(repository, {}).process(claim)
        assert outcome.error_code == "processor_not_configured"
        assert repository.attempt.status == "failed"
        assert "private user text" not in (repository.attempt.error_message or "")

    asyncio.run(run())


def test_timeout_is_safe_and_retried() -> None:
    async def run() -> None:
        repository = WorkerRepository()
        claim = await repository.claim_next_pending(worker_id="worker-one", lease_seconds=10)
        assert claim is not None
        outcome = await service(repository, {"text": SlowProcessor()}, timeout=0.001).process(claim)
        assert outcome.error_code == "processing_timeout"
        assert repository.attempt.status == "pending"
        assert repository.attempt.error_message == "Processing timed out"

    asyncio.run(run())


def test_expired_lease_can_be_reclaimed_and_old_worker_is_fenced() -> None:
    async def run() -> None:
        repository = WorkerRepository()
        old = await repository.claim_next_pending(worker_id="old", lease_seconds=10)
        assert old is not None
        repository.attempt = repository.attempt.model_copy(
            update={"lease_expires_at": datetime.now(UTC) - timedelta(seconds=1)}
        )
        new = await repository.claim_next_pending(worker_id="new", lease_seconds=10)
        assert new is not None
        assert new.attempt.claim_count == 2
        try:
            await repository.complete_claim(
                material_id=old.material.id,
                attempt_id=old.attempt.id,
                worker_id="old",
                result=analysis_result(),
            )
        except LeaseLostError:
            pass
        else:
            raise AssertionError("obsolete worker completed a reclaimed attempt")

    asyncio.run(run())


def test_worker_stops_before_claiming_more_work() -> None:
    async def run() -> None:
        repository = WorkerRepository()
        stop = asyncio.Event()
        stop.set()
        worker = ProcessingWorker(
            repository,
            service(repository, {"text": SuccessfulProcessor()}),
            worker_id="worker-one",
            lease_seconds=10,
            poll_interval_seconds=0.001,
        )
        await worker.run(stop)
        assert repository.claim_calls == 0

    asyncio.run(run())
