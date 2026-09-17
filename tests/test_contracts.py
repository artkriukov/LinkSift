import pytest
from pydantic import ValidationError

from linksift.config import Settings
from linksift.domain.models import Entity, Evidence


@pytest.mark.parametrize("confidence", [-0.01, 1.01, float("nan")])
def test_invalid_confidence_rejected(confidence):
    with pytest.raises(ValidationError):
        Entity(type="book", title="1984", confidence=confidence, verification_status="unknown")


def test_confirmed_entity_requires_evidence():
    with pytest.raises(ValidationError):
        Entity(type="book", title="1984", confidence=0.99, verification_status="confirmed")
    entity = Entity(
        type="book",
        title="1984",
        confidence=0.99,
        verification_status="confirmed",
        evidence=[Evidence(source="speech", timestamp_seconds=18.4, text="1984")],
    )
    assert Entity.model_validate_json(entity.model_dump_json()) == entity


def test_negative_timestamp_rejected():
    with pytest.raises(ValidationError):
        Evidence(source="ocr", timestamp_seconds=-1, text="1984")


def test_media_ttl_bounded():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, media_ttl_seconds=3601)
