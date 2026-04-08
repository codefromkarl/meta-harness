from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from meta_harness.candidates import create_candidate
from meta_harness.schemas import ProposalRecord


def create_proposal_record(
    *,
    proposals_root: Path,
    profile_name: str,
    project_name: str,
    proposer_kind: str,
    proposal: dict[str, Any],
    config_patch: dict[str, Any] | None = None,
    code_patch_content: str | None = None,
    notes: str = "",
    source_run_ids: list[str] | None = None,
    proposal_evaluation: dict[str, Any] | None = None,
) -> str:
    proposal_id = uuid4().hex[:12]
    proposal_dir = proposals_root / proposal_id
    proposal_dir.mkdir(parents=True, exist_ok=False)

    code_patch_artifact = None
    if code_patch_content is not None:
        code_patch_artifact = "code.patch"
        (proposal_dir / code_patch_artifact).write_text(
            code_patch_content,
            encoding="utf-8",
        )

    record = ProposalRecord(
        proposal_id=proposal_id,
        profile=profile_name,
        project=project_name,
        proposer_kind=proposer_kind,
        strategy=str(proposal.get("strategy", proposer_kind)),
        notes=notes,
        source_run_ids=[str(item) for item in (source_run_ids or []) if str(item)],
        proposal=proposal,
        config_patch=config_patch,
        code_patch_artifact=code_patch_artifact,
        evaluation_artifact="proposal_evaluation.json",
    )
    (proposal_dir / "proposal.json").write_text(
        record.model_dump_json(indent=2),
        encoding="utf-8",
    )
    (proposal_dir / "proposal_evaluation.json").write_text(
        json.dumps(proposal_evaluation or {}, indent=2),
        encoding="utf-8",
    )
    return proposal_id


def load_proposal_record(proposals_root: Path, proposal_id: str) -> dict[str, Any]:
    proposal_dir = (proposals_root / proposal_id).resolve()
    payload = ProposalRecord.model_validate_json(
        (proposal_dir / "proposal.json").read_text(encoding="utf-8")
    ).model_dump(mode="json")
    payload["proposal_dir"] = str(proposal_dir)
    if payload.get("code_patch_artifact"):
        payload["code_patch_path"] = str(
            (proposal_dir / str(payload["code_patch_artifact"])).resolve()
        )
    else:
        payload["code_patch_path"] = None
    evaluation_artifact = payload.get("evaluation_artifact")
    if evaluation_artifact:
        evaluation_path = proposal_dir / str(evaluation_artifact)
        payload["proposal_evaluation_path"] = str(evaluation_path.resolve())
        if evaluation_path.exists():
            payload["proposal_evaluation"] = json.loads(
                evaluation_path.read_text(encoding="utf-8")
            )
    else:
        payload["proposal_evaluation_path"] = None
    return payload


def materialize_candidate_from_proposal(
    *,
    proposals_root: Path,
    proposal_id: str,
    candidates_root: Path,
    config_root: Path,
) -> dict[str, Any]:
    proposal_record = load_proposal_record(proposals_root, proposal_id)
    proposal_dir = Path(str(proposal_record["proposal_dir"]))
    proposal_payload = dict(proposal_record.get("proposal") or {})

    code_patch_content = None
    code_patch_path = proposal_record.get("code_patch_path")
    if isinstance(code_patch_path, str) and code_patch_path:
        code_patch_content = Path(code_patch_path).read_text(encoding="utf-8")

    candidate_id = create_candidate(
        candidates_root=candidates_root,
        config_root=config_root,
        profile_name=str(proposal_record["profile"]),
        project_name=str(proposal_record["project"]),
        config_patch=proposal_record.get("config_patch"),
        code_patch_content=code_patch_content,
        notes=str(proposal_record.get("notes", "proposal materialization")),
        proposal=proposal_payload,
        reuse_existing=True,
    )

    candidate_proposal_path = (
        candidates_root / candidate_id / "proposal.json"
    )
    if candidate_proposal_path.exists():
        candidate_proposal = dict(proposal_payload)
        candidate_proposal["proposal_id"] = proposal_id
        candidate_proposal_path.write_text(
            json.dumps(candidate_proposal, indent=2),
            encoding="utf-8",
        )

    updated = ProposalRecord.model_validate_json(
        (proposal_dir / "proposal.json").read_text(encoding="utf-8")
    )
    updated.candidate_id = candidate_id
    updated.status = "materialized"
    updated.materialized_at = datetime.now(UTC)
    (proposal_dir / "proposal.json").write_text(
        updated.model_dump_json(indent=2),
        encoding="utf-8",
    )
    _update_proposal_evaluation(
        proposal_dir=proposal_dir,
        updates={
            "selected": True,
            "selection_reason": "materialized",
            "materialized_candidate_id": candidate_id,
        },
    )
    return {
        "proposal_id": proposal_id,
        "candidate_id": candidate_id,
    }


def list_proposal_records(proposals_root: Path) -> list[dict[str, Any]]:
    if not proposals_root.exists():
        return []
    records: list[dict[str, Any]] = []
    for proposal_dir in sorted(path for path in proposals_root.iterdir() if path.is_dir()):
        proposal_path = proposal_dir / "proposal.json"
        if not proposal_path.exists():
            continue
        records.append(
            ProposalRecord.model_validate_json(
                proposal_path.read_text(encoding="utf-8")
            ).model_dump(mode="json")
        )
    return sorted(
        records,
        key=lambda item: (
            str(item.get("created_at") or ""),
            str(item.get("proposal_id") or ""),
        ),
        reverse=True,
    )


def _update_proposal_evaluation(
    *,
    proposal_dir: Path,
    updates: dict[str, Any],
) -> None:
    evaluation_path = proposal_dir / "proposal_evaluation.json"
    payload = (
        json.loads(evaluation_path.read_text(encoding="utf-8"))
        if evaluation_path.exists()
        else {}
    )
    payload.update(updates)
    evaluation_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
