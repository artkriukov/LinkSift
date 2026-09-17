import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Protocol

from linksift.application.processors import ProcessorNotConfiguredError, ProcessorRouter
from linksift.application.repositories import LeaseLostError, MaterialRepository
from linksift.domain.models import ClaimedProcessingAttempt, Material

logger = logging.getLogger(__name__)


class ProcessingGuard(Protocol):
    async def check(self, material: Material) -> None: ...


class AllowAllProcessingGuard:
    """Extension point for user, size and budget limits before paid processing."""

    async def check(self, material: Material) -> None:
        return None


class ProcessingFailure(RuntimeError):
    def __init__(self, error_code: str, safe_message: str, *, transient: bool = False) -> None:
        super().__init__(safe_message)
        self.error_code = error_code
        self.safe_message = safe_message
        self.transient = transient


@dataclass(frozen=True, slots=True)
class ProcessingOutcome:
    attempt_id: str
    status: str
    error_code: str | None = None


class ProcessingService:
    def __init__(
        self,
        repository: MaterialRepository,
        router: ProcessorRouter,
        *,
        worker_id: str,
        lease_seconds: int,
        heartbeat_seconds: int,
        timeout_seconds: int,
        max_claims: int,
        guard: ProcessingGuard | None = None,
    ) -> None:
        self.repository = repository
        self.router = router
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.timeout_seconds = timeout_seconds
        self.max_claims = max_claims
        self.guard = guard or AllowAllProcessingGuard()

    async def process(self, claim: ClaimedProcessingAttempt) -> ProcessingOutcome:
        started = time.monotonic()
        heartbeat = asyncio.create_task(self._heartbeat(claim))
        try:
            await self.guard.check(claim.material)
            processor = self.router.for_material(claim.material)
            async with asyncio.timeout(self.timeout_seconds):
                result = await processor.process(claim.material)
            await self.repository.complete_claim(
                material_id=claim.material.id,
                attempt_id=claim.attempt.id,
                worker_id=self.worker_id,
                result=result,
            )
            logger.info(
                "worker_completed material_id=%s attempt_id=%s duration_ms=%d",
                claim.material.id,
                claim.attempt.id,
                int((time.monotonic() - started) * 1000),
            )
            return ProcessingOutcome(str(claim.attempt.id), "completed")
        except LeaseLostError:
            logger.warning(
                "worker_lease_lost material_id=%s attempt_id=%s",
                claim.material.id,
                claim.attempt.id,
            )
            return ProcessingOutcome(str(claim.attempt.id), "lease_lost", "lease_lost")
        except Exception as error:
            failure = self._classify(error)
            retry = failure.transient and claim.attempt.claim_count < self.max_claims
            try:
                await self.repository.fail_claim(
                    material_id=claim.material.id,
                    attempt_id=claim.attempt.id,
                    worker_id=self.worker_id,
                    error_code=failure.error_code,
                    error_message=failure.safe_message,
                    retry=retry,
                )
            except LeaseLostError:
                return ProcessingOutcome(str(claim.attempt.id), "lease_lost", "lease_lost")
            status = "pending" if retry else "failed"
            logger.warning(
                "worker_failed material_id=%s attempt_id=%s error_code=%s status=%s",
                claim.material.id,
                claim.attempt.id,
                failure.error_code,
                status,
            )
            return ProcessingOutcome(str(claim.attempt.id), status, failure.error_code)
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

    async def _heartbeat(self, claim: ClaimedProcessingAttempt) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_seconds)
            renewed = await self.repository.heartbeat(
                attempt_id=claim.attempt.id,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
            )
            if not renewed:
                return

    @staticmethod
    def _classify(error: Exception) -> ProcessingFailure:
        if isinstance(error, ProcessorNotConfiguredError):
            return ProcessingFailure(
                "processor_not_configured", "Processor is not configured", transient=False
            )
        if isinstance(error, TimeoutError):
            return ProcessingFailure("processing_timeout", "Processing timed out", transient=True)
        if isinstance(error, ProcessingFailure):
            return error
        return ProcessingFailure("processing_error", "Processing failed", transient=False)


class ProcessingWorker:
    def __init__(
        self,
        repository: MaterialRepository,
        service: ProcessingService,
        *,
        worker_id: str,
        lease_seconds: int,
        poll_interval_seconds: float,
    ) -> None:
        self.repository = repository
        self.service = service
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.poll_interval_seconds = poll_interval_seconds

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            claim = await self.repository.claim_next_pending(
                worker_id=self.worker_id, lease_seconds=self.lease_seconds
            )
            if claim is None:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=self.poll_interval_seconds)
                except TimeoutError:
                    pass
                continue
            logger.info(
                "worker_claimed worker_id=%s material_id=%s attempt_id=%s "
                "source_type=%s attempt_number=%s",
                self.worker_id,
                claim.material.id,
                claim.attempt.id,
                claim.material.source_type,
                claim.attempt.attempt_number,
            )
            await self.service.process(claim)
