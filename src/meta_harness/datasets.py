from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from meta_harness.archive import load_run_record
from meta_harness.failure_index import load_or_extract_failure_signatures
from meta_harness.schemas import DatasetCase, DatasetVersion


def extract_failure_dataset(
    runs_root: Path,
    *,
    profile_name: str | None = None,
    project_name: str | None = None,
) -> dict[str, Any]:
    cases: list[DatasetCase] = []
    if not runs_root.exists():
        return DatasetVersion(
            dataset_id="failure-signatures",
            version="v1",
            schema_version="2026-04-06",
            case_count=0,
            cases=cases,
        ).model_dump()

    for run_dir in sorted(path for path in runs_root.iterdir() if path.is_dir()):
        if not (run_dir / "run_metadata.json").exists():
            continue
        if not (run_dir / "effective_config.json").exists():
            continue
        record = load_run_record(runs_root, run_dir.name)
        if profile_name is not None and record["profile"] != profile_name:
            continue
        if project_name is not None and record["project"] != project_name:
            continue
        for failure in load_or_extract_failure_signatures(run_dir):
            cases.append(
                DatasetCase(
                    source_type="failure_signature",
                    run_id=record["run_id"],
                    profile=record["profile"],
                    project=record["project"],
                    task_id=failure["task_id"],
                    phase=failure["phase"],
                    step_id=failure["step_id"],
                    raw_error=failure["raw_error"],
                    failure_signature=failure["signature"],
                )
            )

    return DatasetVersion(
        dataset_id="failure-signatures",
        version="v1",
        schema_version="2026-04-06",
        case_count=len(cases),
        cases=cases,
    ).model_dump()


def build_dataset_from_task_set(
    task_set_path: Path,
    *,
    dataset_id: str,
    version: str = "v1",
) -> dict[str, Any]:
    payload = json.loads(task_set_path.read_text(encoding="utf-8"))
    cases: list[DatasetCase] = []
    for task in payload.get("tasks", []):
        if not isinstance(task, dict):
            continue
        phases = task.get("phases") or []
        phase_names = [
            str(phase.get("phase"))
            for phase in phases
            if isinstance(phase, dict) and phase.get("phase") is not None
        ]
        cases.append(
            DatasetCase(
                source_type="task_set",
                run_id="task-set",
                profile="task-set",
                project="task-set",
                task_id=str(task.get("task_id", "")),
                phase=phase_names[0] if phase_names else "unknown",
                raw_error="",
                failure_signature="",
                scenario=(
                    str(task["scenario"]) if task.get("scenario") is not None else None
                ),
                difficulty=(
                    str(task["difficulty"])
                    if task.get("difficulty") is not None
                    else None
                ),
                weight=(
                    float(task["weight"]) if task.get("weight") is not None else None
                ),
                expectations=(
                    task.get("expectations")
                    if isinstance(task.get("expectations"), dict)
                    else None
                ),
                phase_names=phase_names,
            )
        )

    return DatasetVersion(
        dataset_id=dataset_id,
        version=version,
        schema_version="2026-04-06",
        case_count=len(cases),
        cases=cases,
    ).model_dump()
