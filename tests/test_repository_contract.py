import asyncio

import pytest
from pydantic import ValidationError

from linksift.application.repositories import DuplicateMaterialError, MaterialRepository
from linksift.domain.models import AnalysisResult
from linksift.infrastructure.database.engine import (
    DatabaseConfigurationError,
    create_database_engine,
)
from linksift.infrastructure.database.repositories import _safe_error_message
from tests.fakes import FakeMaterialRepository


def analysis_result() -> AnalysisResult:
    return AnalysisResult.model_validate(
        {
            "source": {"type": "article", "url": "https://example.com"},
            "language": "en",
            "summary": "Summary",
            "key_points": ["Point"],
            "entities": [],
            "processing": {"llm_provider": "test", "used_visual_analysis": False},
        }
    )


def test_fake_repository_contract_and_owner_isolation():
    async def run() -> None:
        repository: MaterialRepository = FakeMaterialRepository()
        material = await repository.create_material(
            owner_telegram_id=100,
            source_type="article",
            source_key="example",
            source_url="https://example.com",
        )
        assert await repository.get_material(material_id=material.id, owner_telegram_id=100)
        assert await repository.get_material(material_id=material.id, owner_telegram_id=200) is None

        with pytest.raises(DuplicateMaterialError):
            await repository.create_material(
                owner_telegram_id=100,
                source_type="article",
                source_key="example",
            )

        other_owner = await repository.create_material(
            owner_telegram_id=200,
            source_type="article",
            source_key="example",
        )
        assert other_owner.owner_telegram_id == 200

        attempt = await repository.create_attempt(
            material_id=material.id,
            owner_telegram_id=100,
            pipeline_version="test-v1",
        )
        assert attempt.attempt_number == 1
        await repository.mark_processing(
            material_id=material.id,
            attempt_id=attempt.id,
            owner_telegram_id=100,
        )
        stored = await repository.save_result(
            material_id=material.id,
            attempt_id=attempt.id,
            owner_telegram_id=100,
            result=analysis_result(),
            transcript=None,
            provider_usage={"input_tokens": 10},
        )
        assert stored.result.summary == "Summary"

        retry = await repository.retry_material(
            material_id=material.id,
            owner_telegram_id=100,
            pipeline_version="test-v2",
        )
        assert retry.attempt_number == 2
        assert len(await repository.list_history(owner_telegram_id=100, limit=1)) == 1

        await repository.soft_delete(material_id=material.id, owner_telegram_id=100)
        assert await repository.get_material(material_id=material.id, owner_telegram_id=100) is None
        replacement = await repository.create_material(
            owner_telegram_id=100,
            source_type="article",
            source_key="example",
        )
        assert replacement.id != material.id

    asyncio.run(run())


def test_result_is_validated_before_storage():
    with pytest.raises(ValidationError):
        AnalysisResult.model_validate(
            {
                "source": {"type": "article"},
                "language": "en",
                "summary": "",
                "key_points": [],
                "entities": [],
                "processing": {"llm_provider": "test", "used_visual_analysis": False},
            }
        )


def test_database_url_errors_and_messages_do_not_expose_credentials():
    secret = "postgresql+psycopg://postgres.project:top-secret@pooler.example:5432/postgres"
    assert "top-secret" not in _safe_error_message(f"failed to connect to {secret}")

    with pytest.raises(DatabaseConfigurationError) as error:
        create_database_engine("postgresql://postgres:top-secret@example.com/postgres")
    assert "top-secret" not in str(error.value)
