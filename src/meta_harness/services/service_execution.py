from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from meta_harness.services.job_service import (
    complete_job_record,
    create_job_record,
    fail_job_record,
    start_job_record,
)
from meta_harness.services.service_response import error_response, success_response


def execute_inline_job(
    *,
    reports_root: Path,
    job_type: str,
    runner: Callable[[], Any],
    job_input: dict[str, Any] | None = None,
    requested_by: str | None = None,
    result_ref_builder: Callable[[Any], dict[str, Any] | None] | None = None,
    parent_job_id: str | None = None,
    attempt: int = 1,
) -> dict[str, Any]:
    created = create_job_record(
        reports_root=reports_root,
        job_type=job_type,
        job_input=job_input or {},
        requested_by=requested_by,
        parent_job_id=parent_job_id,
        attempt=attempt,
    )
    job_id = str(created["job_id"])
    running = start_job_record(reports_root=reports_root, job_id=job_id)

    try:
        data = runner()
        result_ref = result_ref_builder(data) if result_ref_builder is not None else None
        completed = complete_job_record(
            reports_root=reports_root,
            job_id=job_id,
            result_ref=result_ref,
        )
        return success_response(data, job=completed)
    except Exception as exc:
        failed = fail_job_record(
            reports_root=reports_root,
            job_id=job_id,
            error_code="job_failed",
            message=str(exc),
            details={"job_type": job_type},
        )
        return error_response(
            "job_failed",
            str(exc),
            details={"job_type": job_type},
            job=failed,
        )
