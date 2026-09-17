from collections.abc import Mapping
from typing import Protocol

from linksift.domain.models import AnalysisResult, Material, SourceType


class MaterialProcessor(Protocol):
    async def process(self, material: Material) -> AnalysisResult: ...


class ProcessorNotConfiguredError(RuntimeError):
    pass


class ProcessorRouter:
    """Selects a processor without coupling the application to an AI SDK."""

    def __init__(self, processors: Mapping[SourceType, MaterialProcessor] | None = None) -> None:
        self._processors = dict(processors or {})

    def for_material(self, material: Material) -> MaterialProcessor:
        processor = self._processors.get(material.source_type)
        if processor is None:
            raise ProcessorNotConfiguredError("No processor is configured for this source type")
        return processor

    async def aclose(self) -> None:
        seen: set[int] = set()
        for processor in self._processors.values():
            if id(processor) in seen:
                continue
            seen.add(id(processor))
            close = getattr(processor, "aclose", None)
            if close is not None:
                await close()
