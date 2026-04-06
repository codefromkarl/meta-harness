from __future__ import annotations

from pathlib import Path
from typing import Any

from meta_harness.archive import load_run_record
from meta_harness.failure_index import load_or_extract_failure_signatures


def extract_failure_dataset(
    runs_root: Path,
    *,
    profile_name: str | None = None,
    project_name: str | None = None,
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    if not runs_root.exists():
        return {
            "dataset_id": "failure-signatures",
            "version": "v1",
            "case_count": 0,
            "cases": cases,
        }

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
                {
                    "run_id": record["run_id"],
                    "profile": record["profile"],
                    "project": record["project"],
                    "task_id": failure["task_id"],
                    "phase": failure["phase"],
                    "step_id": failure["step_id"],
                    "raw_error": failure["raw_error"],
                    "failure_signature": failure["signature"],
                }
            )

    return {
        "dataset_id": "failure-signatures",
        "version": "v1",
        "case_count": len(cases),
        "cases": cases,
    }
