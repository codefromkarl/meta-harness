from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from meta_harness.candidates import create_candidate, promote_candidate
from meta_harness.transfer import create_transfer_candidate


def create_candidate_record(
    *,
    profile_name: str,
    project_name: str,
    config_root: Path,
    candidates_root: Path,
    config_patch_path: Path | None = None,
    code_patch_path: Path | None = None,
    notes: str = "",
) -> dict[str, Any]:
    config_patch = None
    if config_patch_path is not None:
        config_patch = json.loads(config_patch_path.read_text(encoding="utf-8"))

    candidate_id = create_candidate(
        candidates_root=candidates_root,
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
        config_patch=config_patch,
        code_patch_path=code_patch_path,
        notes=notes,
    )
    return {
        "candidate_id": candidate_id,
        "candidate_dir": str((candidates_root / candidate_id).resolve()),
    }


def create_transfer_candidate_record(
    *,
    profile_name: str,
    project_name: str,
    config_root: Path,
    candidates_root: Path,
    method_id: str,
    source_binding_id: str,
    target_binding_id: str,
    method_patch_path: Path | None = None,
    binding_patch_path: Path | None = None,
    local_patch_path: Path | None = None,
    notes: str = "",
) -> dict[str, Any]:
    method_patch = None
    binding_patch = None
    local_patch = None
    if method_patch_path is not None:
        method_patch = json.loads(method_patch_path.read_text(encoding="utf-8"))
    if binding_patch_path is not None:
        binding_patch = json.loads(binding_patch_path.read_text(encoding="utf-8"))
    if local_patch_path is not None:
        local_patch = json.loads(local_patch_path.read_text(encoding="utf-8"))

    candidate_id = create_transfer_candidate(
        config_root=config_root,
        candidates_root=candidates_root,
        profile_name=profile_name,
        project_name=project_name,
        method_id=method_id,
        source_binding_id=source_binding_id,
        target_binding_id=target_binding_id,
        method_patch=method_patch,
        binding_patch=binding_patch,
        local_patch=local_patch,
        notes=notes,
    )
    return {
        "candidate_id": candidate_id,
        "candidate_dir": str((candidates_root / candidate_id).resolve()),
    }


def promote_candidate_record(
    candidates_root: Path,
    candidate_id: str,
    *,
    promoted_by: str | None = None,
    promotion_reason: str | None = None,
    evidence_run_ids: list[str] | None = None,
    runs_root: Path | None = None,
) -> dict[str, Any]:
    promotion = promote_candidate(
        candidates_root,
        candidate_id,
        promoted_by=promoted_by,
        promotion_reason=promotion_reason,
        evidence_run_ids=evidence_run_ids,
        runs_root=runs_root,
    )
    return {
        "candidate_id": candidate_id,
        "champions": promotion["champions"],
        "champion_record": promotion["champion_record"],
        "promotion_target_path": promotion["promotion_target_path"],
    }


def list_champions(candidates_root: Path) -> dict[str, str]:
    champions_path = candidates_root / "champions.json"
    if not champions_path.exists():
        return {}
    return json.loads(champions_path.read_text(encoding="utf-8"))
