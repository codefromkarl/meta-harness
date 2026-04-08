from __future__ import annotations

from pathlib import Path
from typing import Any

from meta_harness.task_plugins.base import BaseTaskPlugin


class CodeRepairTaskPlugin(BaseTaskPlugin):
    def __init__(self) -> None:
        super().__init__(
            plugin_id="code_repair",
            objective_label="Code repair optimization",
            default_focus="code_repair",
            default_goal="reduce failure rate and improve fix stability",
            default_evaluators=("basic",),
        )

    def _objective_overrides(
        self,
        effective_config: dict[str, Any],
        tasks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        failure_heavy_tasks = sum(
            1
            for task in tasks
            if bool((task.get("expectations") or {}).get("requires_patch"))
            or "repair" in str(task.get("scenario", "")).lower()
        )
        return {
            "code_repair": {
                "failure_heavy_task_count": failure_heavy_tasks,
                "patch_strategy_hint": effective_config.get("optimization", {}).get("patch_strategy")
                if isinstance(effective_config.get("optimization"), dict)
                else None,
            }
        }

    def _experience_overrides(
        self,
        runs_root: Path,
        candidates_root: Path,
        run_summaries: list[dict[str, Any]],
        objective: dict[str, Any],
    ) -> dict[str, Any]:
        failure_runs = [
            run
            for run in run_summaries
            if float(run.get("composite", 0.0)) < max(0.0, len(run_summaries) / 2)
        ]
        return {
            "code_repair": {
                "failure_runs": failure_runs,
                "repair_candidates": [
                    run.get("candidate_id")
                    for run in failure_runs
                    if run.get("candidate_id")
                ],
            }
        }

    def build_experience_query(
        self,
        *,
        objective: dict[str, Any],
        effective_config: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "focus": "code_repair",
            "best_k": 4,
            "dedupe_failure_families": True,
        }

    def build_proposal_constraints(
        self,
        *,
        objective: dict[str, Any],
        effective_config: dict[str, Any],
        experience: dict[str, Any],
        evaluation_plan: dict[str, Any],
    ) -> dict[str, Any]:
        optimization = effective_config.get("optimization")
        repair_context = experience.get("code_repair") or {}
        return {
            "patch_strategy_hint": (
                optimization.get("patch_strategy")
                if isinstance(optimization, dict)
                else None
            ),
            "repair_candidates": list(repair_context.get("repair_candidates") or []),
        }

    def build_stopping_policy(
        self,
        *,
        objective: dict[str, Any],
        effective_config: dict[str, Any],
        evaluation_plan: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "regression_tolerance": 0.2,
            "no_improvement_limit": 2,
        }

    def _evaluation_plan_notes(
        self,
        objective: dict[str, Any],
        effective_config: dict[str, Any],
        evaluators: list[str],
    ) -> list[str]:
        notes = super()._evaluation_plan_notes(objective, effective_config, evaluators)
        notes.append("prefer regression reduction over exploratory breadth")
        return notes

    def _iteration_summary_notes(
        self,
        benchmark_payload: dict[str, Any],
        selected_variant: dict[str, Any],
    ) -> list[str]:
        notes = super()._iteration_summary_notes(benchmark_payload, selected_variant)
        notes.append("repair_iteration")
        return notes
