from pathlib import Path
from typing import Protocol

from linksift.domain.models import AnalysisContext, AnalysisResult, Evidence, Transcript


class SpeechToTextProvider(Protocol):
    async def transcribe(self, audio_path: Path) -> Transcript: ...


class VisionProvider(Protocol):
    async def analyze_frames(self, frames: list[Path]) -> list[Evidence]: ...


class AnalysisProvider(Protocol):
    async def analyze(self, context: AnalysisContext) -> AnalysisResult: ...


class VideoAnalysisProvider(Protocol):
    async def analyze_video(self, source: str | Path) -> AnalysisResult: ...
