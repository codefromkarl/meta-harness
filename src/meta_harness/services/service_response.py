from __future__ import annotations

from typing import Any

from meta_harness.schemas import JobRecord, ServiceEnvelope, ServiceError, ServiceWarning


def _normalize_warnings(
    warnings: list[dict[str, Any] | ServiceWarning] | None,
) -> list[ServiceWarning]:
    if not warnings:
        return []
    normalized: list[ServiceWarning] = []
    for warning in warnings:
        if isinstance(warning, ServiceWarning):
            normalized.append(warning)
        else:
            normalized.append(ServiceWarning.model_validate(warning))
    return normalized


def success_response(
    data: Any,
    *,
    job: dict[str, Any] | JobRecord | None = None,
    warnings: list[dict[str, Any] | ServiceWarning] | None = None,
) -> dict[str, Any]:
    envelope = ServiceEnvelope(
        ok=True,
        data=data,
        job=job if isinstance(job, JobRecord) or job is None else JobRecord.model_validate(job),
        warnings=_normalize_warnings(warnings),
    )
    return envelope.model_dump(mode="json")


def error_response(
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    job: dict[str, Any] | JobRecord | None = None,
    warnings: list[dict[str, Any] | ServiceWarning] | None = None,
) -> dict[str, Any]:
    envelope = ServiceEnvelope(
        ok=False,
        data=None,
        job=job if isinstance(job, JobRecord) or job is None else JobRecord.model_validate(job),
        error=ServiceError(code=code, message=message, details=details or {}),
        warnings=_normalize_warnings(warnings),
    )
    return envelope.model_dump(mode="json")
