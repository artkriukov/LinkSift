from linksift.domain.models import (
    AnalysisResult,
    Material,
    ProcessingAttempt,
    StoredAnalysisResult,
    Transcript,
)
from linksift.infrastructure.database.models import (
    AnalysisResultRow,
    MaterialRow,
    ProcessingAttemptRow,
)


def to_material(row: MaterialRow) -> Material:
    return Material.model_validate(
        {
            "id": row.id,
            "owner_telegram_id": row.owner_telegram_id,
            "source_type": row.source_type,
            "source_url": row.source_url,
            "source_key": row.source_key,
            "title": row.title,
            "status": row.status,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "deleted_at": row.deleted_at,
        }
    )


def to_attempt(row: ProcessingAttemptRow) -> ProcessingAttempt:
    return ProcessingAttempt.model_validate(
        {
            "id": row.id,
            "material_id": row.material_id,
            "attempt_number": row.attempt_number,
            "status": row.status,
            "pipeline_version": row.pipeline_version,
            "error_code": row.error_code,
            "error_message": row.error_message,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
            "created_at": row.created_at,
        }
    )


def to_stored_result(row: AnalysisResultRow) -> StoredAnalysisResult:
    return StoredAnalysisResult(
        id=row.id,
        attempt_id=row.attempt_id,
        result=AnalysisResult.model_validate(row.result),
        transcript=(
            Transcript.model_validate(row.transcript) if row.transcript is not None else None
        ),
        provider_usage=row.provider_usage,
        created_at=row.created_at,
    )
