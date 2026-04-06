from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4
from typing import Any

from meta_harness.config_loader import load_effective_config, merge_dicts
from meta_harness.schemas import CandidateMetadata


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def create_candidate(
    candidates_root: Path,
    config_root: Path,
    profile_name: str,
    project_name: str,
    config_patch: dict[str, Any] | None = None,
    code_patch_path: Path | None = None,
    code_patch_content: str | None = None,
    notes: str = "",
    parent_candidate_id: str | None = None,
    proposal: dict[str, Any] | None = None,
) -> str:
    candidate_id = uuid4().hex[:12]
    candidate_dir = candidates_root / candidate_id
    candidate_dir.mkdir(parents=True, exist_ok=False)

    effective_config = load_effective_config(
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
    )
    if config_patch:
        effective_config = merge_dicts(effective_config, config_patch)

    code_patch_artifact = None
    code_patch_text = None
    if code_patch_content is not None:
        code_patch_text = code_patch_content
    elif code_patch_path is not None:
        code_patch_text = code_patch_path.read_text(encoding="utf-8")

    if code_patch_text is not None:
        code_patch_artifact = "code.patch"
        (candidate_dir / code_patch_artifact).write_text(
            code_patch_text,
            encoding="utf-8",
        )

    metadata = CandidateMetadata(
        candidate_id=candidate_id,
        profile=profile_name,
        project=project_name,
        notes=notes,
        parent_candidate_id=parent_candidate_id,
        code_patch_artifact=code_patch_artifact,
    )

    (candidate_dir / "candidate.json").write_text(
        metadata.model_dump_json(indent=2),
        encoding="utf-8",
    )
    (candidate_dir / "effective_config.json").write_text(
        json.dumps(effective_config, indent=2),
        encoding="utf-8",
    )

    if proposal is not None:
        (candidate_dir / "proposal.json").write_text(
            json.dumps(proposal, indent=2),
            encoding="utf-8",
        )

    return candidate_id


def load_candidate_record(candidates_root: Path, candidate_id: str) -> dict[str, Any]:
    candidate_dir = (candidates_root / candidate_id).resolve()
    metadata = _read_json(candidate_dir / "candidate.json")
    effective_config = _read_json(candidate_dir / "effective_config.json")
    proposal = None
    proposal_path = candidate_dir / "proposal.json"
    if proposal_path.exists():
        proposal = _read_json(proposal_path)
    code_patch_path = None
    code_patch_artifact = metadata.get("code_patch_artifact")
    if code_patch_artifact:
        patch_path = candidate_dir / code_patch_artifact
        if patch_path.exists():
            code_patch_path = str(patch_path.resolve())

    return {
        **metadata,
        "effective_config": effective_config,
        "proposal": proposal,
        "candidate_dir": str(candidate_dir),
        "code_patch_path": code_patch_path,
    }


def promote_candidate(candidates_root: Path, candidate_id: str) -> dict[str, str]:
    record = load_candidate_record(candidates_root, candidate_id)
    champions_path = candidates_root / "champions.json"
    champions: dict[str, str] = {}
    if champions_path.exists():
        champions = _read_json(champions_path)

    champions[f"{record['profile']}:{record['project']}"] = candidate_id
    champions_path.parent.mkdir(parents=True, exist_ok=True)
    champions_path.write_text(json.dumps(champions, indent=2), encoding="utf-8")
    return champions


def load_champion_candidate_id(
    candidates_root: Path,
    profile_name: str,
    project_name: str,
) -> str | None:
    champions_path = candidates_root / "champions.json"
    if not champions_path.exists():
        return None
    champions = _read_json(champions_path)
    return champions.get(f"{profile_name}:{project_name}")
