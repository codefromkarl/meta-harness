from __future__ import annotations

from pathlib import Path
from typing import Any

from meta_harness.archive import initialize_run
from meta_harness.candidates import load_candidate_record
from meta_harness.config_loader import load_effective_config


def initialize_run_record(
    *,
    config_root: Path,
    candidates_root: Path,
    runs_root: Path,
    profile_name: str | None = None,
    project_name: str | None = None,
    candidate_id: str | None = None,
) -> dict[str, Any]:
    if candidate_id:
        candidate = load_candidate_record(candidates_root, candidate_id)
        resolved_profile = str(candidate["profile"])
        resolved_project = str(candidate["project"])
        effective_config = candidate["effective_config"]
    else:
        if not profile_name or not project_name:
            raise ValueError(
                "either candidate_id or both profile_name/project_name are required"
            )
        resolved_profile = profile_name
        resolved_project = project_name
        effective_config = load_effective_config(
            config_root=config_root,
            profile_name=resolved_profile,
            project_name=resolved_project,
        )

    run_id = initialize_run(
        runs_root=runs_root,
        profile_name=resolved_profile,
        project_name=resolved_project,
        effective_config=effective_config,
        candidate_id=candidate_id,
    )
    return {
        "run_id": run_id,
        "profile": resolved_profile,
        "project": resolved_project,
        "candidate_id": candidate_id,
    }
