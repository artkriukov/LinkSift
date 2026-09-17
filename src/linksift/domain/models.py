from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

SourceType = Literal["youtube", "instagram_reel", "article", "direct_media", "upload", "text"]
MaterialStatus = Literal["pending", "processing", "completed", "failed", "deleted"]
AttemptStatus = Literal["pending", "processing", "completed", "failed"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(Contract):
    source: Literal["speech", "description", "ocr", "visual", "article"]
    timestamp_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    text: str = Field(min_length=1)


class Entity(Contract):
    type: Literal[
        "book",
        "author",
        "podcast",
        "person",
        "film",
        "series",
        "product",
        "service",
        "place",
        "idea",
        "recommendation",
        "action",
    ]
    title: str = Field(min_length=1)
    author: str | None = None
    normalized_title: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    verification_status: Literal["confirmed", "probable", "unknown"]

    @model_validator(mode="after")
    def require_evidence_for_confirmation(self) -> "Entity":
        if self.verification_status == "confirmed" and not self.evidence:
            raise ValueError("Confirmed entities require evidence")
        return self


class Source(Contract):
    type: SourceType
    url: str | None = None
    title: str | None = None
    creator: str | None = None


class Processing(Contract):
    asr_provider: str | None = None
    llm_provider: str
    used_visual_analysis: bool


class AnalysisResult(Contract):
    source: Source
    language: str
    summary: str = Field(min_length=1)
    key_points: list[str]
    entities: list[Entity]
    warnings: list[str] = Field(default_factory=list)
    processing: Processing


class TranscriptSegment(Contract):
    timestamp_seconds: float = Field(ge=0)
    text: str


class Transcript(Contract):
    language: str
    segments: list[TranscriptSegment]


class AnalysisContext(Contract):
    source: Source
    description: str | None = None
    transcript: Transcript | None = None
    observations: list[Evidence] = Field(default_factory=list)


class Material(Contract):
    id: UUID
    owner_telegram_id: int
    source_type: SourceType
    source_url: str | None = None
    source_text: str | None = None
    source_key: str
    title: str | None = None
    status: MaterialStatus
    created_at: AwareDatetime
    updated_at: AwareDatetime
    deleted_at: AwareDatetime | None = None


class ProcessingAttempt(Contract):
    id: UUID
    material_id: UUID
    attempt_number: int = Field(gt=0)
    status: AttemptStatus
    pipeline_version: str
    error_code: str | None = None
    error_message: str | None = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    worker_id: str | None = None
    lease_expires_at: AwareDatetime | None = None
    heartbeat_at: AwareDatetime | None = None
    claim_count: int = Field(default=0, ge=0)
    created_at: AwareDatetime


class ClaimedProcessingAttempt(Contract):
    material: Material
    attempt: ProcessingAttempt


class StoredAnalysisResult(Contract):
    id: UUID
    attempt_id: UUID
    result: AnalysisResult
    transcript: Transcript | None = None
    provider_usage: dict[str, Any]
    created_at: AwareDatetime
