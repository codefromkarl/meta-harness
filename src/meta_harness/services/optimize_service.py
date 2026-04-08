from __future__ import annotations

from pathlib import Path
from typing import Any

from meta_harness.optimizer_generation import build_proposal_from_failures
from meta_harness.optimizer_shadow import shadow_run_candidate
from meta_harness.proposals import (
    create_proposal_record,
    list_proposal_records,
    load_proposal_record,
    materialize_candidate_from_proposal,
)


def propose_candidate_payload(
    *,
    profile_name: str,
    project_name: str,
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    proposals_root: Path | None = None,
    proposal_only: bool = False,
) -> dict[str, Any]:
    resolved_proposals_root = proposals_root or (candidates_root.parent / "proposals")
    generated = build_proposal_from_failures(
        config_root=config_root,
        runs_root=runs_root,
        profile_name=profile_name,
        project_name=project_name,
    )
    proposal = generated.get("proposal")
    proposal_id = create_proposal_record(
        proposals_root=resolved_proposals_root,
        profile_name=profile_name,
        project_name=project_name,
        proposer_kind=str(generated.get("proposer_kind", "unknown")),
        proposal=proposal if isinstance(proposal, dict) else {},
        config_patch=(
            generated.get("config_patch")
            if isinstance(generated.get("config_patch"), dict)
            else None
        ),
        code_patch_content=(
            str(generated["code_patch"]) if generated.get("code_patch") is not None else None
        ),
        notes=str(generated.get("notes", "")),
        source_run_ids=[
            str(item) for item in generated.get("source_run_ids", []) if str(item)
        ],
        proposal_evaluation={
            "selected": True,
            "selection_reason": "proposal_only" if proposal_only else "materialized",
            "proposal_rank": 1,
            "rejected_proposals": [],
        },
    )
    payload: dict[str, Any] = {"proposal_id": proposal_id}
    if proposal_only:
        return payload
    materialized = materialize_candidate_from_proposal(
        proposals_root=resolved_proposals_root,
        proposal_id=proposal_id,
        candidates_root=candidates_root,
        config_root=config_root,
    )
    payload["candidate_id"] = materialized["candidate_id"]
    return payload


def materialize_proposal_payload(
    *,
    proposal_id: str,
    proposals_root: Path,
    candidates_root: Path,
    config_root: Path,
) -> dict[str, Any]:
    return materialize_candidate_from_proposal(
        proposals_root=proposals_root,
        proposal_id=proposal_id,
        candidates_root=candidates_root,
        config_root=config_root,
    )


def shadow_run_candidate_payload(
    *,
    candidate_id: str,
    task_set_path: Path,
    candidates_root: Path,
    runs_root: Path,
) -> dict[str, Any]:
    run_id = shadow_run_candidate(
        candidates_root=candidates_root,
        runs_root=runs_root,
        candidate_id=candidate_id,
        task_set_path=task_set_path,
    )
    return {"run_id": run_id}


def run_optimize_loop_payload(
    *,
    profile_name: str,
    project_name: str,
    task_set_path: Path,
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    reports_root: Path,
    proposals_root: Path | None = None,
    plugin_id: str,
    proposer_id: str,
    max_iterations: int = 8,
    focus: str | None = None,
) -> dict[str, Any]:
    from meta_harness.services.optimize_loop_service import optimize_loop_payload

    return optimize_loop_payload(
        profile_name=profile_name,
        project_name=project_name,
        task_set_path=task_set_path,
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        reports_root=reports_root,
        proposals_root=proposals_root,
        plugin_id=plugin_id,
        proposer_id=proposer_id,
        max_iterations=max_iterations,
        focus=focus,
    )


def list_proposals_payload(
    *,
    proposals_root: Path,
    profile_name: str | None = None,
    project_name: str | None = None,
    status: str | None = None,
    proposer_kind: str | None = None,
    strategy: str | None = None,
) -> list[dict[str, Any]]:
    items = list_proposal_records(proposals_root)
    filtered: list[dict[str, Any]] = []
    for item in items:
        if profile_name is not None and item.get("profile") != profile_name:
            continue
        if project_name is not None and item.get("project") != project_name:
            continue
        if status is not None and item.get("status") != status:
            continue
        if proposer_kind is not None and item.get("proposer_kind") != proposer_kind:
            continue
        if strategy is not None and item.get("strategy") != strategy:
            continue
        filtered.append(item)
    return filtered


def load_proposal_payload(
    *,
    proposals_root: Path,
    proposal_id: str,
) -> dict[str, Any]:
    return load_proposal_record(proposals_root, proposal_id)
