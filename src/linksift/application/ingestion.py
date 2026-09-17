import hashlib
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from linksift.application.repositories import DuplicateMaterialError, MaterialRepository
from linksift.domain.models import Material, SourceType

PIPELINE_VERSION = "telegram-ingestion-v1"
MAX_TEXT_LENGTH = 20_000
MAX_URL_LENGTH = 2_048
TRACKING_PARAMETERS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
}
MEDIA_EXTENSIONS = {".mp4", ".mov", ".webm", ".mp3", ".m4a", ".wav", ".ogg"}
URL_PATTERN = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
UNSUPPORTED_URL_PATTERN = re.compile(r"(?:file|ftp|javascript|data):", re.IGNORECASE)


class InvalidInputError(ValueError):
    pass


class MultipleUrlsError(InvalidInputError):
    pass


class TextTooLongError(InvalidInputError):
    pass


class InvalidUrlError(InvalidInputError):
    pass


@dataclass(frozen=True, slots=True)
class PreparedSource:
    source_type: SourceType
    source_key: str
    source_url: str | None = None
    source_text: str | None = None


@dataclass(frozen=True, slots=True)
class IngestionResult:
    material: Material
    created: bool


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _trim_url_punctuation(value: str) -> str:
    return value.rstrip(".,;:!?)]}")


def extract_urls(text: str) -> list[str]:
    return [_trim_url_punctuation(match.group(0)) for match in URL_PATTERN.finditer(text)]


def normalize_url(raw_url: str) -> str:
    if len(raw_url) > MAX_URL_LENGTH:
        raise InvalidUrlError("URL is too long")
    try:
        parts = urlsplit(raw_url)
        port = parts.port
    except ValueError:
        raise InvalidUrlError("Invalid URL") from None

    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"} or not parts.hostname:
        raise InvalidUrlError("Unsupported URL")
    if parts.username is not None or parts.password is not None:
        raise InvalidUrlError("Credentials in URLs are not allowed")

    hostname = parts.hostname.lower().rstrip(".")
    if not hostname:
        raise InvalidUrlError("Invalid hostname")
    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError:
        raise InvalidUrlError("Invalid hostname") from None

    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None
    host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = f"{host}:{port}" if port is not None else host
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"

    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMETERS
    ]
    query.sort()

    youtube_id: str | None = None
    if hostname in {"youtu.be", "www.youtu.be"}:
        youtube_id = path.strip("/").split("/", 1)[0]
    elif hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"} and path == "/watch":
        youtube_id = next((value for key, value in query if key == "v"), None)
    if youtube_id:
        return urlunsplit(("https", "youtube.com", "/watch", urlencode({"v": youtube_id}), ""))

    return urlunsplit((scheme, netloc, path, urlencode(query, doseq=True), ""))


def classify_url(normalized_url: str) -> SourceType:
    parts = urlsplit(normalized_url)
    hostname = parts.hostname or ""
    if hostname in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
        return "youtube"
    if hostname in {"instagram.com", "www.instagram.com", "m.instagram.com"} and (
        parts.path.startswith("/reel/") or parts.path.startswith("/reels/")
    ):
        return "instagram_reel"
    lowered_path = parts.path.lower()
    if any(lowered_path.endswith(extension) for extension in MEDIA_EXTENSIONS):
        return "direct_media"
    return "article"


def prepare_source(text: str) -> PreparedSource:
    urls = extract_urls(text)
    if len(urls) > 1:
        raise MultipleUrlsError("Only one URL is allowed")
    if urls:
        original_url = urls[0]
        normalized_url = normalize_url(original_url)
        return PreparedSource(
            source_type=classify_url(normalized_url),
            source_key=_sha256(normalized_url),
            source_url=original_url,
        )

    if UNSUPPORTED_URL_PATTERN.search(text):
        raise InvalidUrlError("Unsupported URL scheme")

    if len(text) > MAX_TEXT_LENGTH:
        raise TextTooLongError("Text is too long")
    normalized_text = " ".join(text.split())
    if not normalized_text:
        raise InvalidInputError("Text is empty")
    return PreparedSource(
        source_type="text",
        source_key=_sha256(normalized_text),
        source_text=text.strip(),
    )


class MaterialIngestionService:
    def __init__(self, repository: MaterialRepository) -> None:
        self.repository = repository

    async def history(self, *, owner_telegram_id: int, limit: int = 10) -> list[Material]:
        return await self.repository.list_history(owner_telegram_id=owner_telegram_id, limit=limit)

    async def ingest(self, *, owner_telegram_id: int, text: str) -> IngestionResult:
        source = prepare_source(text)
        existing = await self.repository.get_existing_material(
            owner_telegram_id=owner_telegram_id, source_key=source.source_key
        )
        if existing is not None:
            return IngestionResult(material=existing, created=False)
        try:
            material, _ = await self.repository.create_material_with_attempt(
                owner_telegram_id=owner_telegram_id,
                source_type=source.source_type,
                source_key=source.source_key,
                source_url=source.source_url,
                source_text=source.source_text,
                pipeline_version=PIPELINE_VERSION,
            )
        except DuplicateMaterialError:
            existing = await self.repository.get_existing_material(
                owner_telegram_id=owner_telegram_id, source_key=source.source_key
            )
            if existing is None:
                raise
            return IngestionResult(material=existing, created=False)
        return IngestionResult(material=material, created=True)


def status_label(status: str) -> str:
    return {
        "pending": "ожидает обработки",
        "processing": "обрабатывается",
        "completed": "готов",
        "failed": "ошибка",
    }.get(status, status)
