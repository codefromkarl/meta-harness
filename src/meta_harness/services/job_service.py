from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from meta_harness.schemas import JobRecord, JobResultRef


def _jobs_root(reports_root: Path) -> Path:
    return reports_root / "jobs"


def _job_path(reports_root: Path, job_id: str) -> Path:
    return _jobs_root(reports_root) / f"{job_id}.json"


def _write_job(path: Path, payload: JobRecord) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
    return payload.model_dump(mode="json")


def load_job_record(*, reports_root: Path, job_id: str) -> dict[str, Any]:
    path = _job_path(reports_root, job_id)
    return JobRecord.model_validate_json(path.read_text(encoding="utf-8")).model_dump(
        mode="json"
    )


def load_job_view(
    *,
    reports_root: Path,
    job_id: str,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    payload = load_job_record(reports_root=reports_root, job_id=job_id)
    payload["result_preview"] = _result_preview(
        payload.get("result_ref"),
        repo_root=repo_root or reports_root.parent,
    )
    return payload


def list_job_records(
    *,
    reports_root: Path,
    status: str | None = None,
    job_type: str | None = None,
) -> list[dict[str, Any]]:
    root = _jobs_root(reports_root)
    if not root.exists():
        return []
    jobs = [
        JobRecord.model_validate_json(path.read_text(encoding="utf-8")).model_dump(
            mode="json"
        )
        for path in sorted(root.glob("*.json"))
    ]
    selected: list[dict[str, Any]] = []
    for job in jobs:
        if status is not None and job["status"] != status:
            continue
        if job_type is not None and job["job_type"] != job_type:
            continue
        selected.append(job)
    return selected


def list_job_views(
    *,
    reports_root: Path,
    status: str | None = None,
    job_type: str | None = None,
    repo_root: Path | None = None,
) -> list[dict[str, Any]]:
    return [
        {
            **job,
            "result_preview": _result_preview(
                job.get("result_ref"),
                repo_root=repo_root or reports_root.parent,
            ),
        }
        for job in list_job_records(
            reports_root=reports_root,
            status=status,
            job_type=job_type,
        )
    ]


def create_job_record(
    *,
    reports_root: Path,
    job_type: str,
    job_input: dict[str, Any] | None = None,
    requested_by: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    payload = JobRecord(
        job_id=job_id or uuid4().hex[:12],
        job_type=job_type,
        requested_by=requested_by,
        job_input=job_input or {},
    )
    return _write_job(_job_path(reports_root, payload.job_id), payload)


def start_job_record(*, reports_root: Path, job_id: str) -> dict[str, Any]:
    current = JobRecord.model_validate(load_job_record(reports_root=reports_root, job_id=job_id))
    current.status = "running"
    current.started_at = datetime.now(UTC)
    return _write_job(_job_path(reports_root, job_id), current)


def complete_job_record(
    *,
    reports_root: Path,
    job_id: str,
    result_ref: dict[str, Any] | JobResultRef | None = None,
) -> dict[str, Any]:
    current = JobRecord.model_validate(load_job_record(reports_root=reports_root, job_id=job_id))
    current.status = "succeeded"
    current.completed_at = datetime.now(UTC)
    current.result_ref = (
        result_ref
        if isinstance(result_ref, JobResultRef)
        else JobResultRef.model_validate(result_ref)
        if result_ref is not None
        else None
    )
    return _write_job(_job_path(reports_root, job_id), current)


def fail_job_record(
    *,
    reports_root: Path,
    job_id: str,
    error_code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = JobRecord.model_validate(load_job_record(reports_root=reports_root, job_id=job_id))
    current.status = "failed"
    current.completed_at = datetime.now(UTC)
    current.error = {
        "code": error_code,
        "message": message,
        "details": details or {},
    }
    return _write_job(_job_path(reports_root, job_id), current)


def cancel_job_record(*, reports_root: Path, job_id: str) -> dict[str, Any]:
    current = JobRecord.model_validate(load_job_record(reports_root=reports_root, job_id=job_id))
    current.status = "cancelled"
    current.completed_at = datetime.now(UTC)
    return _write_job(_job_path(reports_root, job_id), current)


def _result_preview(
    result_ref: dict[str, Any] | None,
    *,
    repo_root: Path,
) -> dict[str, Any] | None:
    if not isinstance(result_ref, dict):
        return None

    target_type = result_ref.get("target_type")
    target_id = result_ref.get("target_id")
    path = result_ref.get("path")

    if not isinstance(target_type, str) or not isinstance(target_id, str):
        return None

    preview: dict[str, Any] = {
        "target_type": target_type,
        "target_id": target_id,
    }
    if not isinstance(path, str) or not path:
        return preview

    artifact_path = Path(path)
    if not artifact_path.is_absolute():
        artifact_path = (repo_root / artifact_path).resolve()
    if not artifact_path.exists():
        return preview

    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return preview

    if target_type == "run":
        composite = payload.get("composite")
        if composite is not None:
            preview["composite"] = composite
        return preview

    if target_type == "benchmark_experiment":
        best_variant = payload.get("best_variant")
        if best_variant is not None:
            preview["best_variant"] = best_variant
        return preview

    if target_type == "benchmark_suite":
        best_by_experiment = payload.get("best_by_experiment")
        if best_by_experiment is not None:
            preview["best_by_experiment"] = best_by_experiment
        return preview

    return preview
