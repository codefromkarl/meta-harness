from __future__ import annotations

from pathlib import Path
import json
from typing import Any

from meta_harness.archive import list_run_records, load_run_record
from meta_harness.failure_index import search_failure_signatures


def list_run_summaries(
    runs_root: Path,
    *,
    profile: str | None = None,
    project: str | None = None,
    candidate_id: str | None = None,
) -> list[dict[str, str]]:
    payload: list[dict[str, str]] = []
    for record in list_run_records(runs_root):
        if profile is not None and record["profile"] != profile:
            continue
        if project is not None and record["project"] != project:
            continue
        if candidate_id is not None and record.get("candidate_id") != candidate_id:
            continue
        composite = "-"
        if record["score"] is not None:
            composite = str(record["score"].get("composite", "-"))
        payload.append(
            {
                "run_id": str(record["run_id"]),
                "profile": str(record["profile"]),
                "project": str(record["project"]),
                "composite": composite,
            }
        )
    return payload


def load_run_summary(runs_root: Path, run_id: str) -> dict[str, Any]:
    return load_run_record(runs_root, run_id)


def list_task_results(
    runs_root: Path,
    run_id: str,
    *,
    task_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    tasks_dir = runs_root / run_id / "tasks"
    if not tasks_dir.exists():
        return []
    items: list[dict[str, Any]] = []
    for task_dir in sorted(path for path in tasks_dir.iterdir() if path.is_dir()):
        if task_id is not None and task_dir.name != task_id:
            continue
        task_result_path = task_dir / "task_result.json"
        if not task_result_path.exists():
            continue
        payload = json.loads(task_result_path.read_text(encoding="utf-8"))
        if status is not None:
            task_status = "succeeded" if bool(payload.get("success")) else "failed"
            if task_status != status:
                continue
        items.append(payload)
    return items


def list_trace_events(
    runs_root: Path,
    run_id: str,
    *,
    task_id: str | None = None,
    phase: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    tasks_dir = runs_root / run_id / "tasks"
    if not tasks_dir.exists():
        return []
    items: list[dict[str, Any]] = []
    for task_dir in sorted(path for path in tasks_dir.iterdir() if path.is_dir()):
        if task_id is not None and task_dir.name != task_id:
            continue
        steps_path = task_dir / "steps.jsonl"
        if not steps_path.exists():
            continue
        for line in steps_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if phase is not None and payload.get("phase") != phase:
                continue
            if status is not None and payload.get("status") != status:
                continue
            items.append(payload)
    return items


def list_evaluator_reports(runs_root: Path, run_id: str) -> list[dict[str, Any]]:
    evaluators_dir = runs_root / run_id / "evaluators"
    if not evaluators_dir.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(evaluators_dir.glob("*.json")):
        items.append(_normalize_evaluator_payload(path.stem, json.loads(path.read_text(encoding="utf-8"))))
    return items


def load_task_result(runs_root: Path, run_id: str, task_id: str) -> dict[str, Any]:
    task_result_path = runs_root / run_id / "tasks" / task_id / "task_result.json"
    if not task_result_path.exists():
        raise FileNotFoundError(f"task '{task_id}' not found in run '{run_id}'")
    return json.loads(task_result_path.read_text(encoding="utf-8"))


def load_evaluator_report(
    runs_root: Path,
    run_id: str,
    evaluator_name: str,
) -> dict[str, Any]:
    path = runs_root / run_id / "evaluators" / f"{evaluator_name}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"evaluator '{evaluator_name}' not found in run '{run_id}'"
        )
    return _normalize_evaluator_payload(
        evaluator_name,
        json.loads(path.read_text(encoding="utf-8")),
    )


def _normalize_evaluator_payload(
    evaluator_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if "report" in payload and "evaluator_name" in payload:
        return {
            "name": evaluator_name,
            "evaluator_name": payload.get("evaluator_name", evaluator_name),
            "run_id": payload.get("run_id"),
            "status": payload.get("status", "completed"),
            "started_at": payload.get("started_at"),
            "completed_at": payload.get("completed_at"),
            "duration_ms": payload.get("duration_ms"),
            "artifact_refs": payload.get("artifact_refs", []),
            "trace_grade": payload.get("trace_grade", {}),
            "profiling": payload.get("profiling", {}),
            "trace_artifact": payload.get("trace_artifact"),
            "report": payload.get("report", {}),
        }
    return {
        "name": evaluator_name,
        "evaluator_name": evaluator_name,
        "run_id": None,
        "status": "completed",
        "started_at": None,
        "completed_at": None,
        "duration_ms": None,
        "artifact_refs": [],
        "trace_grade": {},
        "profiling": {},
        "trace_artifact": None,
        "report": payload,
    }


def search_failure_records(runs_root: Path, query: str) -> list[dict[str, str]]:
    return [
        {
            "run_id": str(record["run_id"]),
            "task_id": str(record["task_id"]),
            "phase": str(record["phase"]),
            "signature": str(record["signature"]),
        }
        for record in search_failure_signatures(runs_root, query)
    ]
