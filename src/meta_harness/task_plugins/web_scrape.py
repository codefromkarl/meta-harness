from __future__ import annotations

from pathlib import Path
from typing import Any

from meta_harness.task_plugins.base import BaseTaskPlugin


class WebScrapeTaskPlugin(BaseTaskPlugin):
    def __init__(self) -> None:
        super().__init__(
            plugin_id="web_scrape",
            objective_label="Web scrape optimization",
            default_focus="web_scrape",
            default_goal="improve scraping reliability, extraction fidelity, and cost control",
            default_evaluators=("basic",),
        )

    def _objective_overrides(
        self,
        effective_config: dict[str, Any],
        tasks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        dynamic_tasks = sum(
            1
            for task in tasks
            if "render" in str(task.get("scenario", "")).lower()
            or bool((task.get("expectations") or {}).get("requires_rendering"))
        )
        return {
            "web_scrape": {
                "dynamic_task_count": dynamic_tasks,
                "page_profile_hint": effective_config.get("page_profile")
                if isinstance(effective_config.get("page_profile"), dict)
                else {},
            }
        }

    def _experience_overrides(
        self,
        runs_root: Path,
        candidates_root: Path,
        run_summaries: list[dict[str, Any]],
        objective: dict[str, Any],
    ) -> dict[str, Any]:
        score_ranked = sorted(
            run_summaries,
            key=lambda run: (float(run.get("composite", 0.0)), str(run.get("run_id") or "")),
            reverse=True,
        )
        return {
            "web_scrape": {
                "best_references": score_ranked[:3],
                "recent_failure_runs": [
                    run
                    for run in run_summaries
                    if float(run.get("composite", 0.0)) <= 0.0
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
            "focus": "web_scrape",
            "best_k": 5,
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
        page_profile = effective_config.get("page_profile")
        scrape_objective = objective.get("web_scrape") or {}
        return {
            "rendering_required": bool(scrape_objective.get("dynamic_task_count", 0)),
            "anti_bot_level": (
                page_profile.get("anti_bot_level")
                if isinstance(page_profile, dict)
                else None
            ),
            "recent_failure_families": [
                item.get("family")
                for item in experience.get("representative_failures", [])
                if isinstance(item, dict) and item.get("family")
            ],
        }

    def build_stopping_policy(
        self,
        *,
        objective: dict[str, Any],
        effective_config: dict[str, Any],
        evaluation_plan: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "no_improvement_limit": 1,
        }

    def _evaluation_plan_notes(
        self,
        objective: dict[str, Any],
        effective_config: dict[str, Any],
        evaluators: list[str],
    ) -> list[str]:
        notes = super()._evaluation_plan_notes(objective, effective_config, evaluators)
        notes.append("prefer signal fidelity over raw task count")
        return notes

    def _iteration_summary_notes(
        self,
        benchmark_payload: dict[str, Any],
        selected_variant: dict[str, Any],
    ) -> list[str]:
        notes = super()._iteration_summary_notes(benchmark_payload, selected_variant)
        if selected_variant.get("stability"):
            notes.append("stability_tracked")
        return notes
