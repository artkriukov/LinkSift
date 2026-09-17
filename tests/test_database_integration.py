import asyncio
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from linksift.application.repositories import DuplicateMaterialError, MaterialNotFoundError
from linksift.infrastructure.database.engine import create_database_engine, create_session_factory
from linksift.infrastructure.database.models import ProcessingAttemptRow
from linksift.infrastructure.database.repositories import SqlAlchemyMaterialRepository
from tests.test_repository_contract import analysis_result

TEST_DATABASE_URL = os.getenv("LINKSIFT_TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason="LINKSIFT_TEST_DATABASE_URL is not configured",
    ),
]


@pytest.fixture(scope="module")
def migrated_database() -> str:
    production_url = os.getenv("LINKSIFT_DATABASE_URL", "")
    if TEST_DATABASE_URL == production_url:
        pytest.fail("The integration database must not be LINKSIFT_DATABASE_URL")

    config = Config("alembic.ini")
    config.attributes["database_url"] = TEST_DATABASE_URL
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield TEST_DATABASE_URL
    command.downgrade(config, "base")


def test_postgresql_repository_end_to_end(migrated_database: str):
    async def run() -> None:
        engine = create_database_engine(migrated_database)
        session_factory = create_session_factory(engine)
        repository = SqlAlchemyMaterialRepository(session_factory)
        try:
            first = await repository.create_material(
                owner_telegram_id=100,
                source_type="article",
                source_key="article-one",
                source_url="https://example.com/one",
            )
            second = await repository.create_material(
                owner_telegram_id=100,
                source_type="article",
                source_key="article-two",
            )
            await repository.create_material(
                owner_telegram_id=200,
                source_type="article",
                source_key="article-one",
            )

            assert (
                await repository.get_material(material_id=first.id, owner_telegram_id=200) is None
            )
            assert len(await repository.list_history(owner_telegram_id=100, limit=1)) == 1
            assert len(await repository.list_history(owner_telegram_id=100, limit=1, offset=1)) == 1

            with pytest.raises(DuplicateMaterialError) as error:
                await repository.create_material(
                    owner_telegram_id=100,
                    source_type="article",
                    source_key="article-one",
                )
            assert "postgresql" not in str(error.value)

            # A failed insert rolls back fully; the next independent transaction succeeds.
            third = await repository.create_material(
                owner_telegram_id=100,
                source_type="text",
                source_key="article-three",
            )
            assert third.status == "pending"

            attempt = await repository.create_attempt(
                material_id=first.id,
                owner_telegram_id=100,
                pipeline_version="integration-v1",
            )
            await repository.mark_processing(
                material_id=first.id,
                attempt_id=attempt.id,
                owner_telegram_id=100,
            )
            stored = await repository.save_result(
                material_id=first.id,
                attempt_id=attempt.id,
                owner_telegram_id=100,
                result=analysis_result(),
                transcript=None,
                provider_usage={"input_tokens": 10, "cost_usd": 0.01},
            )
            assert stored.result.summary == "Summary"
            assert stored.provider_usage["input_tokens"] == 10
            completed = await repository.get_material(material_id=first.id, owner_telegram_id=100)
            assert completed is not None and completed.status == "completed"

            retry = await repository.retry_material(
                material_id=first.id,
                owner_telegram_id=100,
                pipeline_version="integration-v2",
            )
            assert retry.attempt_number == 2
            await repository.mark_processing(
                material_id=first.id,
                attempt_id=retry.id,
                owner_telegram_id=100,
            )
            await repository.save_failure(
                material_id=first.id,
                attempt_id=retry.id,
                owner_telegram_id=100,
                error_code="provider_error",
                error_message=(
                    "connection postgresql+psycopg://postgres:secret@db.example/postgres failed"
                ),
            )
            async with session_factory() as session, session.begin():
                failed_attempt = await session.scalar(
                    select(ProcessingAttemptRow).where(ProcessingAttemptRow.id == retry.id)
                )
                assert failed_attempt is not None
                assert "secret" not in (failed_attempt.error_message or "")

            with pytest.raises(MaterialNotFoundError):
                await repository.soft_delete(material_id=second.id, owner_telegram_id=200)
            await repository.soft_delete(material_id=second.id, owner_telegram_id=100)
            replacement = await repository.create_material(
                owner_telegram_id=100,
                source_type="article",
                source_key="article-two",
            )
            assert replacement.id != second.id
        finally:
            await engine.dispose()

    asyncio.run(run())
