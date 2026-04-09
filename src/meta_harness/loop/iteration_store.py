from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from meta_harness.loop.schemas import LoopExperienceSummary, LoopIterationArtifact, LoopSummary


def loop_root_path(reports_root: Path, loop_id: str) -> Path:
    return reports_root / "loops" / loop_id


def iteration_path(loop_dir: Path, iteration_id: str) -> Path:
    return loop_dir / "iterations" / iteration_id


def write_loop_summary(loop_dir: Path, summary: LoopSummary) -> Path:
    loop_dir.mkdir(parents=True, exist_ok=True)
    path = loop_dir / "loop.json"
    path.write_text(json.dumps(summary.model_dump(), indent=2), encoding="utf-8")
    return path


def write_iteration_artifact(loop_dir: Path, artifact: LoopIterationArtifact) -> dict[str, Path]:
    iteration_dir = iteration_path(loop_dir, artifact.iteration_id)
    iteration_dir.mkdir(parents=True, exist_ok=True)

    paths = {
        "iteration_dir": iteration_dir,
        "iteration_json": iteration_dir / "iteration.json",
        "proposal_input_json": iteration_dir / "proposal_input.json",
        "proposal_output_json": iteration_dir / "proposal_output.json",
        "selected_candidate_json": iteration_dir / "selected_candidate.json",
        "benchmark_summary_json": iteration_dir / "benchmark_summary.json",
        "validation_summary_json": iteration_dir / "validation_summary.json",
        "experience_summary_json": iteration_dir / "experience_summary.json",
        "next_round_context_json": iteration_dir / "next_round_context.json",
    }

    payload = artifact.model_dump()
    paths["iteration_json"].write_text(json.dumps(payload, indent=2), encoding="utf-8")
    paths["proposal_input_json"].write_text(
        json.dumps(
            {
                "objective": artifact.objective,
                "experience": artifact.experience,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    paths["proposal_output_json"].write_text(
        json.dumps(
            {
                "proposal": artifact.proposal,
                "proposal_id": artifact.proposal_id,
                "proposal_evaluation": artifact.proposal_evaluation,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    paths["selected_candidate_json"].write_text(
        json.dumps(
            {
                "candidate_id": artifact.candidate_id,
                "candidate_path": artifact.candidate_path,
                "selection": artifact.selection.model_dump() if artifact.selection else None,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    paths["benchmark_summary_json"].write_text(
        json.dumps(
            {
                "run_id": artifact.run_id,
                "run_path": artifact.run_path,
                "evaluation": artifact.evaluation,
                "summary": artifact.summary,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    validation_summary = {}
    if isinstance(artifact.evaluation, dict):
        validation_payload = artifact.evaluation.get("validation")
        if isinstance(validation_payload, dict):
            validation_summary = validation_payload
    paths["validation_summary_json"].write_text(
        json.dumps(validation_summary, indent=2),
        encoding="utf-8",
    )
    experience_summary = build_experience_summary(artifact)
    paths["experience_summary_json"].write_text(
        json.dumps(experience_summary.model_dump(), indent=2),
        encoding="utf-8",
    )
    paths["next_round_context_json"].write_text(
        json.dumps(
            {
                "stop_decision": artifact.stop_decision.model_dump() if artifact.stop_decision else None,
                "artifacts": {
                    **(artifact.artifacts if isinstance(artifact.artifacts, dict) else {}),
                    **{name: str(path) for name, path in paths.items()},
                },
                "experience_summary_path": str(paths["experience_summary_json"]),
                "validation_summary_path": str(paths["validation_summary_json"]),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return paths


def candidate_lineage_artifact_paths(paths: dict[str, Path]) -> list[str]:
    return [
        str(paths["iteration_json"]),
        str(paths["proposal_input_json"]),
        str(paths["proposal_output_json"]),
        str(paths["selected_candidate_json"]),
        str(paths["benchmark_summary_json"]),
        str(paths["experience_summary_json"]),
        str(paths["validation_summary_json"]),
        str(paths["next_round_context_json"]),
        str(paths["iteration_dir"] / "proposer_context"),
    ]


def append_iteration_history(loop_dir: Path, artifact: LoopIterationArtifact) -> Path:
    loop_dir.mkdir(parents=True, exist_ok=True)
    history_path = loop_dir / "iteration_history.jsonl"
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(artifact.model_dump()))
        handle.write("\n")
    return history_path


def build_experience_summary(artifact: LoopIterationArtifact) -> LoopExperienceSummary:
    experience = artifact.experience if isinstance(artifact.experience, dict) else {}
    objective = artifact.objective if isinstance(artifact.objective, dict) else {}
    summary = artifact.summary if isinstance(artifact.summary, dict) else {}
    next_actions = summary.get("next_actions") if isinstance(summary, dict) else None
    focus_summary = experience.get("focus_summary") if isinstance(experience, dict) else {}
    return LoopExperienceSummary(
        iteration_id=artifact.iteration_id,
        focus=(
            focus_summary.get("focus")
            if isinstance(focus_summary, dict) and focus_summary.get("focus") is not None
            else objective.get("focus")
        ),
        selected_candidate_id=artifact.candidate_id,
        selected_run_id=artifact.run_id,
        score_delta=float(experience.get("score_delta", 0.0) or 0.0),
        best_score=float(experience.get("best_score", 0.0) or 0.0),
        representative_failures=list(experience.get("representative_failures") or []),
        representative_successes=list(experience.get("representative_successes") or []),
        capability_gaps=list(experience.get("capability_gaps") or []),
        representative_artifacts=dict(experience.get("representative_artifacts") or {}),
        next_actions=[str(item) for item in next_actions] if isinstance(next_actions, list) else [],
    )
