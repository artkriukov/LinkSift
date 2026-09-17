import asyncio

import pytest

from linksift.application.ingestion import (
    InvalidUrlError,
    MaterialIngestionService,
    MultipleUrlsError,
    TextTooLongError,
    classify_url,
    normalize_url,
    prepare_source,
)
from tests.fakes import FakeMaterialRepository


def test_url_normalization_and_youtube_identity():
    variants = [
        "https://youtu.be/VIDEO_ID",
        "https://youtube.com/watch?v=VIDEO_ID",
        "https://www.youtube.com/watch?utm_source=test&v=VIDEO_ID#chapter",
    ]
    prepared = [prepare_source(value) for value in variants]
    assert len({item.source_key for item in prepared}) == 1
    assert all(item.source_type == "youtube" for item in prepared)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://instagram.com/reel/abc/", "instagram_reel"),
        ("https://cdn.example/video.MP4?download=1", "direct_media"),
        ("https://example.com/story", "article"),
    ],
)
def test_source_classification(url, expected):
    assert classify_url(normalize_url(url)) == expected


def test_normalization_removes_tracking_fragment_ports_and_sorts_query():
    assert normalize_url("HTTPS://Example.COM:443/a/?z=2&utm_medium=x&a=1#part") == (
        "https://example.com/a?a=1&z=2"
    )


def test_invalid_or_multiple_urls_and_long_text_are_rejected():
    with pytest.raises(InvalidUrlError):
        normalize_url("https://user:pass@example.com")
    with pytest.raises(MultipleUrlsError):
        prepare_source("https://one.example https://two.example")
    with pytest.raises(InvalidUrlError):
        prepare_source("ftp://example.com/file")
    with pytest.raises(TextTooLongError):
        prepare_source("x" * 20_001)


def test_text_is_stored_but_only_its_hash_is_used_as_key():
    source = prepare_source("  a   private note  ")
    assert source.source_type == "text"
    assert source.source_text == "a   private note"
    assert source.source_text not in source.source_key


def test_ingestion_creates_material_and_attempt_atomically():
    async def run() -> None:
        repository = FakeMaterialRepository()
        service = MaterialIngestionService(repository)
        result = await service.ingest(owner_telegram_id=123, text="hello")
        assert result.created
        assert result.material.source_text == "hello"
        assert len(repository.attempts) == 1
        assert next(iter(repository.attempts.values())).pipeline_version == (
            "telegram-ingestion-v1"
        )

    asyncio.run(run())
