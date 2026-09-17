import asyncio
import logging
import signal
import socket
import sys
from uuid import uuid4

from linksift.application.processing import ProcessingService, ProcessingWorker
from linksift.application.processors import ProcessorRouter
from linksift.config import Settings
from linksift.infrastructure.database.engine import create_database_engine, create_session_factory
from linksift.infrastructure.database.repositories import SqlAlchemyMaterialRepository

logger = logging.getLogger(__name__)


async def run_worker() -> None:
    settings = Settings()
    if not settings.database_url.get_secret_value():
        raise RuntimeError("LINKSIFT_DATABASE_URL is not configured")

    worker_id = f"{socket.gethostname()}-{uuid4()}"
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signame in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signame, stop.set)

    engine = create_database_engine(settings.database_url)
    repository = SqlAlchemyMaterialRepository(create_session_factory(engine))
    router = ProcessorRouter()
    service = ProcessingService(
        repository,
        router,
        worker_id=worker_id,
        lease_seconds=settings.worker_lease_seconds,
        heartbeat_seconds=settings.worker_heartbeat_seconds,
        timeout_seconds=settings.processing_timeout_seconds,
        max_claims=settings.worker_max_claims,
    )
    worker = ProcessingWorker(
        repository,
        service,
        worker_id=worker_id,
        lease_seconds=settings.worker_lease_seconds,
        poll_interval_seconds=settings.worker_poll_interval_seconds,
    )
    logger.info("worker_starting worker_id=%s", worker_id)
    try:
        await worker.run(stop)
    finally:
        try:
            await router.aclose()
        finally:
            await engine.dispose()
        logger.info("worker_stopped worker_id=%s", worker_id)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
