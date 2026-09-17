from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    type: Literal["youtube", "instagram_reel", "article", "direct_media", "upload", "text"]
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
