from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


def prepare_proposer_context(
    *,
    iteration_dir: Path,
    objective: dict[str, Any],
    experience: dict[str, Any],
    runs_root: Path,
    candidates_root: Path,
    proposals_root: Path | None = None,
) -> dict[str, Any]:
    bundle_dir = iteration_dir / "proposer_context"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    objective_path = bundle_dir / "objective.json"
    experience_path = bundle_dir / "experience.json"
    manifest_path = bundle_dir / "manifest.json"
    selected_runs_dir = bundle_dir / "selected_runs"
    selected_candidates_dir = bundle_dir / "selected_candidates"
    selected_proposals_dir = bundle_dir / "selected_proposals"

    _write_json(objective_path, objective if isinstance(objective, dict) else {})
    _write_json(experience_path, experience if isinstance(experience, dict) else {})

    selected_runs = []
    for record in experience.get("matching_runs", []):
        if not isinstance(record, dict):
            continue
        run_id = str(record.get("run_id") or "").strip()
        if not run_id:
            continue
        source_run_dir = runs_root / run_id
        target_run_dir = selected_runs_dir / run_id
        linked_files = _materialize_run_context(source_run_dir, target_run_dir)
        selected_runs.append(
            {
                "run_id": run_id,
                "path": str(target_run_dir.resolve()),
                "candidate_id": record.get("candidate_id"),
                "linked_files": linked_files,
            }
        )

    selected_candidate_ids = _candidate_ids_from_experience(experience)
    selected_candidates = []
    for candidate_id in selected_candidate_ids:
        source_candidate_dir = candidates_root / candidate_id
        target_candidate_dir = selected_candidates_dir / candidate_id
        linked_files = _materialize_candidate_context(
            source_candidate_dir,
            target_candidate_dir,
        )
        if not linked_files:
            continue
        selected_candidates.append(
            {
                "candidate_id": candidate_id,
                "path": str(target_candidate_dir.resolve()),
                "linked_files": linked_files,
            }
        )

    selected_proposals = []
    if proposals_root is not None:
        selected_proposal_ids = _proposal_ids_from_experience(experience)
        for proposal_id in selected_proposal_ids:
            source_proposal_dir = proposals_root / proposal_id
            target_proposal_dir = selected_proposals_dir / proposal_id
            linked_files = _materialize_proposal_context(
                source_proposal_dir,
                target_proposal_dir,
            )
            if not linked_files:
                continue
            selected_proposals.append(
                {
                    "proposal_id": proposal_id,
                    "path": str(target_proposal_dir.resolve()),
                    "linked_files": linked_files,
                }
            )

    manifest = {
        "bundle_dir": str(bundle_dir.resolve()),
        "objective_path": str(objective_path.resolve()),
        "experience_path": str(experience_path.resolve()),
        "selected_runs": selected_runs,
        "selected_candidates": selected_candidates,
        "selected_proposals": selected_proposals,
    }
    _write_json(manifest_path, manifest)
    return {
        "bundle_dir": str(bundle_dir.resolve()),
        "manifest_path": str(manifest_path.resolve()),
        "objective_path": str(objective_path.resolve()),
        "experience_path": str(experience_path.resolve()),
        "selected_runs_dir": str(selected_runs_dir.resolve()),
        "selected_candidates_dir": str(selected_candidates_dir.resolve()),
        "selected_proposals_dir": str(selected_proposals_dir.resolve()),
    }


def _candidate_ids_from_experience(experience: dict[str, Any]) -> list[str]:
    candidate_ids: list[str] = []
    seen: set[str] = set()
    best_candidate_id = str(experience.get("best_candidate_id") or "").strip()
    if best_candidate_id:
        candidate_ids.append(best_candidate_id)
        seen.add(best_candidate_id)
    for record in experience.get("matching_runs", []):
        if not isinstance(record, dict):
            continue
        candidate_id = str(record.get("candidate_id") or "").strip()
        if not candidate_id or candidate_id in seen:
            continue
        seen.add(candidate_id)
        candidate_ids.append(candidate_id)
    return candidate_ids


def _proposal_ids_from_experience(experience: dict[str, Any]) -> list[str]:
    proposal_ids: list[str] = []
    seen: set[str] = set()
    for record in experience.get("matching_runs", []):
        if not isinstance(record, dict):
            continue
        proposal_id = str(record.get("proposal_id") or "").strip()
        if not proposal_id or proposal_id in seen:
            continue
        seen.add(proposal_id)
        proposal_ids.append(proposal_id)
    return proposal_ids


def _materialize_run_context(source_dir: Path, target_dir: Path) -> list[str]:
    if not source_dir.exists():
        return []
    linked_files = []
    for relative_path in (
        "run_metadata.json",
        "effective_config.json",
        "score_report.json",
    ):
        linked_files.extend(_link_file_if_exists(source_dir, target_dir, relative_path))
    tasks_dir = source_dir / "tasks"
    if tasks_dir.exists():
        for task_dir in sorted(path for path in tasks_dir.iterdir() if path.is_dir()):
            for name in ("task_result.json", "stdout.txt", "stderr.txt", "steps.jsonl"):
                linked_files.extend(
                    _link_file_if_exists(
                        source_dir,
                        target_dir,
                        Path("tasks") / task_dir.name / name,
                    )
                )
    return linked_files


def _materialize_candidate_context(source_dir: Path, target_dir: Path) -> list[str]:
    if not source_dir.exists():
        return []
    linked_files = []
    for relative_path in ("candidate.json", "effective_config.json", "proposal.json", "code.patch"):
        linked_files.extend(_link_file_if_exists(source_dir, target_dir, relative_path))
    return linked_files


def _materialize_proposal_context(source_dir: Path, target_dir: Path) -> list[str]:
    if not source_dir.exists():
        return []
    linked_files = []
    for relative_path in ("proposal.json", "proposal_evaluation.json", "code.patch"):
        linked_files.extend(_link_file_if_exists(source_dir, target_dir, relative_path))
    return linked_files


def _link_file_if_exists(source_root: Path, target_root: Path, relative_path: str | Path) -> list[str]:
    source_path = source_root / relative_path
    if not source_path.exists():
        return []
    target_path = target_root / relative_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    _link_or_copy(source_path, target_path)
    return [str(Path(relative_path))]


def _link_or_copy(source_path: Path, target_path: Path) -> None:
    if target_path.exists() or target_path.is_symlink():
        target_path.unlink()
    try:
        target_path.symlink_to(source_path.resolve())
    except OSError:
        shutil.copy2(source_path, target_path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
