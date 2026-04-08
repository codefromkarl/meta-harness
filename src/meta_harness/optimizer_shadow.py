from __future__ import annotations

from pathlib import Path

from meta_harness.candidates import load_candidate_record
from meta_harness.runtime_execution import execute_managed_run


def shadow_run_candidate(
    candidates_root: Path,
    runs_root: Path,
    candidate_id: str,
    task_set_path: Path,
) -> str:
    candidate = load_candidate_record(candidates_root, candidate_id)
    execution = execute_managed_run(
        runs_root=runs_root,
        profile_name=candidate["profile"],
        project_name=candidate["project"],
        effective_config=candidate["effective_config"],
        task_set_path=task_set_path,
        candidate_id=candidate_id,
        code_patch_path=Path(candidate["code_patch_path"])
        if candidate.get("code_patch_path") is not None
        else None,
    )
    return str(execution["run_id"])

