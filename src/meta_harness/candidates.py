from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from typing import Any

from meta_harness.config_loader import load_effective_config, merge_dicts
from meta_harness.schemas import CandidateMetadata


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = _read_json(path)
    return payload if isinstance(payload, dict) else {}


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _candidate_fingerprint(
    *,
    profile_name: str,
    project_name: str,
    effective_config: dict[str, Any],
    code_patch_text: str | None,
    proposal: dict[str, Any] | None,
    parent_candidate_id: str | None,
) -> str:
    payload = {
        "profile": profile_name,
        "project": project_name,
        "effective_config": effective_config,
        "code_patch": code_patch_text,
        "proposal": proposal,
        "parent_candidate_id": parent_candidate_id,
    }
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _fingerprint_path(candidate_dir: Path) -> Path:
    return candidate_dir / "candidate_fingerprint.txt"


def _existing_candidate_fingerprint(candidate_dir: Path) -> str | None:
    fingerprint_path = _fingerprint_path(candidate_dir)
    if fingerprint_path.exists():
        return fingerprint_path.read_text(encoding="utf-8").strip() or None

    metadata_path = candidate_dir / "candidate.json"
    effective_config_path = candidate_dir / "effective_config.json"
    if not metadata_path.exists() or not effective_config_path.exists():
        return None

    metadata = _read_json(metadata_path)
    effective_config = _read_json(effective_config_path)
    proposal_path = candidate_dir / "proposal.json"
    proposal = _read_json(proposal_path) if proposal_path.exists() else None
    code_patch_text = None
    code_patch_artifact = metadata.get("code_patch_artifact")
    if code_patch_artifact:
        patch_path = candidate_dir / str(code_patch_artifact)
        if patch_path.exists():
            code_patch_text = patch_path.read_text(encoding="utf-8")

    return _candidate_fingerprint(
        profile_name=str(metadata.get("profile", "")),
        project_name=str(metadata.get("project", "")),
        effective_config=effective_config,
        code_patch_text=code_patch_text,
        proposal=proposal if isinstance(proposal, dict) else None,
        parent_candidate_id=(
            str(metadata["parent_candidate_id"])
            if metadata.get("parent_candidate_id") is not None
            else None
        ),
    )


def _find_existing_candidate_id(candidates_root: Path, fingerprint: str) -> str | None:
    if not candidates_root.exists():
        return None
    for candidate_dir in sorted(path for path in candidates_root.iterdir() if path.is_dir()):
        existing = _existing_candidate_fingerprint(candidate_dir)
        if existing != fingerprint:
            continue
        metadata_path = candidate_dir / "candidate.json"
        if not metadata_path.exists():
            continue
        metadata = _read_json(metadata_path)
        return str(metadata.get("candidate_id", candidate_dir.name))
    return None


def _normalize_source_artifacts(source_artifacts: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for item in source_artifacts or []:
        value = str(item).strip()
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def _normalize_source_run_ids(source_run_ids: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for item in source_run_ids or []:
        value = str(item).strip()
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def _normalize_source_iteration_ids(source_iteration_ids: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for item in source_iteration_ids or []:
        value = str(item).strip()
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def _normalize_source_proposal_ids(source_proposal_ids: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for item in source_proposal_ids or []:
        value = str(item).strip()
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def _backfill_candidate_lineage(
    *,
    candidate_dir: Path,
    proposal_id: str | None,
    iteration_id: str | None,
    source_run_ids: list[str] | None,
    source_artifacts: list[str] | None,
) -> None:
    metadata_path = candidate_dir / "candidate.json"
    if not metadata_path.exists():
        return
    metadata = CandidateMetadata.model_validate_json(
        metadata_path.read_text(encoding="utf-8")
    )
    changed = False
    if proposal_id and metadata.proposal_id is None:
        metadata.proposal_id = proposal_id
        changed = True
    merged_source_proposal_ids = list(metadata.source_proposal_ids)
    for item in _normalize_source_proposal_ids([proposal_id] if proposal_id else []):
        if item not in merged_source_proposal_ids:
            merged_source_proposal_ids.append(item)
            changed = True
    if iteration_id and metadata.iteration_id is None:
        metadata.iteration_id = iteration_id
        changed = True
    merged_source_iteration_ids = list(metadata.source_iteration_ids)
    for item in _normalize_source_iteration_ids([iteration_id] if iteration_id else []):
        if item not in merged_source_iteration_ids:
            merged_source_iteration_ids.append(item)
            changed = True
    merged_source_run_ids = list(metadata.source_run_ids)
    for item in _normalize_source_run_ids(source_run_ids):
        if item not in merged_source_run_ids:
            merged_source_run_ids.append(item)
            changed = True
    merged_source_artifacts = list(metadata.source_artifacts)
    for item in _normalize_source_artifacts(source_artifacts):
        if item not in merged_source_artifacts:
            merged_source_artifacts.append(item)
            changed = True
    if changed:
        metadata.source_proposal_ids = merged_source_proposal_ids
        metadata.source_iteration_ids = merged_source_iteration_ids
        metadata.source_run_ids = merged_source_run_ids
        metadata.source_artifacts = merged_source_artifacts
        metadata = CandidateMetadata.model_validate(metadata.model_dump())
        metadata_path.write_text(
            metadata.model_dump_json(indent=2),
            encoding="utf-8",
        )


def backfill_candidate_lineage(
    *,
    candidates_root: Path,
    candidate_id: str,
    proposal_id: str | None,
    iteration_id: str | None,
    source_run_ids: list[str] | None,
    source_artifacts: list[str] | None,
) -> None:
    _backfill_candidate_lineage(
        candidate_dir=candidates_root / candidate_id,
        proposal_id=proposal_id,
        iteration_id=iteration_id,
        source_run_ids=source_run_ids,
        source_artifacts=source_artifacts,
    )


def create_candidate(
    candidates_root: Path,
    config_root: Path,
    profile_name: str,
    project_name: str,
    effective_config_override: dict[str, Any] | None = None,
    config_patch: dict[str, Any] | None = None,
    code_patch_path: Path | None = None,
    code_patch_content: str | None = None,
    notes: str = "",
    parent_candidate_id: str | None = None,
    proposal_id: str | None = None,
    iteration_id: str | None = None,
    source_run_ids: list[str] | None = None,
    source_artifacts: list[str] | None = None,
    proposal: dict[str, Any] | None = None,
    reuse_existing: bool = False,
) -> str:
    effective_config = (
        dict(effective_config_override)
        if isinstance(effective_config_override, dict)
        else load_effective_config(
            config_root=config_root,
            profile_name=profile_name,
            project_name=project_name,
        )
    )
    if config_patch:
        effective_config = merge_dicts(effective_config, config_patch)

    code_patch_artifact = None
    code_patch_text = None
    if code_patch_content is not None:
        code_patch_text = code_patch_content
    elif code_patch_path is not None:
        code_patch_text = code_patch_path.read_text(encoding="utf-8")

    fingerprint = _candidate_fingerprint(
        profile_name=profile_name,
        project_name=project_name,
        effective_config=effective_config,
        code_patch_text=code_patch_text,
        proposal=proposal,
        parent_candidate_id=parent_candidate_id,
    )
    if reuse_existing:
        existing_candidate_id = _find_existing_candidate_id(candidates_root, fingerprint)
        if existing_candidate_id is not None:
            _backfill_candidate_lineage(
                candidate_dir=candidates_root / existing_candidate_id,
                proposal_id=proposal_id,
                iteration_id=iteration_id,
                source_run_ids=source_run_ids,
                source_artifacts=source_artifacts,
            )
            return existing_candidate_id

    candidate_id = uuid4().hex[:12]
    candidate_dir = candidates_root / candidate_id
    candidate_dir.mkdir(parents=True, exist_ok=False)

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
        proposal_id=proposal_id,
        source_proposal_ids=_normalize_source_proposal_ids(
            [proposal_id] if proposal_id else []
        ),
        iteration_id=iteration_id,
        source_iteration_ids=_normalize_source_iteration_ids(
            [iteration_id] if iteration_id else []
        ),
        source_run_ids=_normalize_source_run_ids(source_run_ids),
        source_artifacts=_normalize_source_artifacts(source_artifacts),
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
    _fingerprint_path(candidate_dir).write_text(fingerprint, encoding="utf-8")

    return candidate_id


def load_candidate_record(candidates_root: Path, candidate_id: str) -> dict[str, Any]:
    candidate_dir = (candidates_root / candidate_id).resolve()
    metadata = CandidateMetadata.model_validate_json(
        (candidate_dir / "candidate.json").read_text(encoding="utf-8")
    ).model_dump(mode="json")
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


def _build_promotion_target_payload(
    *,
    candidates_root: Path,
    candidate_id: str,
    evidence_run_ids: list[str],
    runs_root: Path | None,
    promoted_by: str | None,
    promotion_reason: str | None,
) -> dict[str, Any]:
    record = load_candidate_record(candidates_root, candidate_id)
    evidence_refs = [f"runs/{run_id}/score_report.json" for run_id in evidence_run_ids]
    evidence_runs: list[dict[str, Any]] = []
    completed_evidence_run_count = 0
    scored_evidence_run_count = 0
    if runs_root is not None:
        for run_id in evidence_run_ids:
            run_dir = runs_root / run_id
            run_metadata = _read_json_if_exists(run_dir / "run_metadata.json")
            score_report = _read_json_if_exists(run_dir / "score_report.json")
            status = run_metadata.get("status")
            if status == "completed":
                completed_evidence_run_count += 1
            if score_report:
                scored_evidence_run_count += 1
            evidence_runs.append(
                {
                    "run_id": run_id,
                    "run_metadata_path": f"runs/{run_id}/run_metadata.json",
                    "score_report_path": f"runs/{run_id}/score_report.json",
                    "status": status,
                    "candidate_id": run_metadata.get("candidate_id"),
                    "composite": score_report.get("composite"),
                }
            )

    evidence_run_count = len(evidence_run_ids)
    all_evidence_runs_completed = (
        evidence_run_count > 0 and completed_evidence_run_count == evidence_run_count
    )
    all_evidence_runs_scored = (
        evidence_run_count > 0 and scored_evidence_run_count == evidence_run_count
    )
    return {
        "candidate": {
            "candidate_id": record["candidate_id"],
            "profile": record["profile"],
            "project": record["project"],
            "notes": record.get("notes", ""),
        },
        "promotion_reason": promotion_reason or "",
        "promoted_by": promoted_by,
        "evidence_run_ids": evidence_run_ids,
        "evidence_refs": evidence_refs,
        "evidence_runs": evidence_runs,
        "promotion_summary": {
            "evidence_run_count": evidence_run_count,
            "completed_evidence_run_count": completed_evidence_run_count,
            "scored_evidence_run_count": scored_evidence_run_count,
            "all_evidence_runs_completed": all_evidence_runs_completed,
            "all_evidence_runs_scored": all_evidence_runs_scored,
        },
    }


def promote_candidate(
    candidates_root: Path,
    candidate_id: str,
    *,
    promoted_by: str | None = None,
    promotion_reason: str | None = None,
    evidence_run_ids: list[str] | None = None,
    runs_root: Path | None = None,
) -> dict[str, Any]:
    record = load_candidate_record(candidates_root, candidate_id)
    champions_path = candidates_root / "champions.json"
    champions: dict[str, str] = {}
    if champions_path.exists():
        champions = _read_json(champions_path)

    profile_project_key = f"{record['profile']}:{record['project']}"
    evidence_ids = [str(item) for item in (evidence_run_ids or []) if str(item)]

    champions[profile_project_key] = candidate_id
    champions_path.parent.mkdir(parents=True, exist_ok=True)
    champions_path.write_text(json.dumps(champions, indent=2), encoding="utf-8")

    champion_record = {
        "candidate_id": candidate_id,
        "profile": record["profile"],
        "project": record["project"],
        "promoted_at": datetime.now(UTC).isoformat(),
        "promoted_by": promoted_by,
        "promotion_reason": promotion_reason or "",
        "evidence_run_ids": evidence_ids,
    }
    champion_records_path = candidates_root / "champion_records.json"
    champion_records = _read_json_if_exists(champion_records_path)
    champion_records[profile_project_key] = champion_record
    champion_records_path.write_text(
        json.dumps(champion_records, indent=2), encoding="utf-8"
    )

    promotion_target = _build_promotion_target_payload(
        candidates_root=candidates_root,
        candidate_id=candidate_id,
        evidence_run_ids=evidence_ids,
        runs_root=runs_root,
        promoted_by=promoted_by,
        promotion_reason=promotion_reason,
    )
    candidate_dir = Path(str(record["candidate_dir"]))
    (candidate_dir / "promotion_target.json").write_text(
        json.dumps(promotion_target, indent=2),
        encoding="utf-8",
    )

    return {
        "champions": champions,
        "champion_record": champion_record,
        "promotion_target_path": str((candidate_dir / "promotion_target.json").resolve()),
    }


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
