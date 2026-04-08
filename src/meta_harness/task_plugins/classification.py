from __future__ import annotations

from pathlib import Path
from typing import Any

from meta_harness.task_plugins.base import BaseTaskPlugin


class ClassificationTaskPlugin(BaseTaskPlugin):
    def __init__(self) -> None:
        super().__init__(
            plugin_id="classification",
            objective_label="Classification optimization",
            default_focus="classification",
            default_goal="improve label accuracy and decision consistency",
            default_evaluators=("basic",),
        )

    def _objective_overrides(
        self,
        effective_config: dict[str, Any],
        tasks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        labels: set[str] = set()
        ambiguous_task_count = 0

        for task in tasks:
            expectations = task.get("expectations")
            if not isinstance(expectations, dict):
                expectations = {}
            for key in ("label_space", "allowed_labels", "labels", "classes"):
                values = expectations.get(key)
                if not isinstance(values, list):
                    continue
                for value in values:
                    text = str(value).strip()
                    if text:
                        labels.add(text)
            scenario = str(task.get("scenario") or "").lower()
            decision_mode = str(expectations.get("decision_mode") or "").lower()
            if "ambiguous" in scenario or "ambiguous" in decision_mode:
                ambiguous_task_count += 1

        return {
            "classification": {
                "task_count": len(tasks),
                "labels": sorted(labels),
                "label_count": len(labels),
                "ambiguous_task_count": ambiguous_task_count,
            }
        }

    def _experience_overrides(
        self,
        runs_root: Path,
        candidates_root: Path,
        run_summaries: list[dict[str, Any]],
        objective: dict[str, Any],
    ) -> dict[str, Any]:
        low_confidence_runs = sorted(
            run_summaries,
            key=lambda run: (
                float(run.get("composite", 0.0)),
                str(run.get("run_id") or ""),
            ),
        )
        candidate_ids = [
            str(run.get("candidate_id"))
            for run in run_summaries
            if str(run.get("candidate_id") or "")
        ]
        return {
            "classification": {
                "low_confidence_runs": low_confidence_runs[:3],
                "candidate_ids": candidate_ids,
                "labels": list(
                    (objective.get("classification") or {}).get("labels") or []
                ),
            }
        }

    def _evaluation_plan_notes(
        self,
        objective: dict[str, Any],
        effective_config: dict[str, Any],
        evaluators: list[str],
    ) -> list[str]:
        notes = super()._evaluation_plan_notes(objective, effective_config, evaluators)
        notes.append("prioritize decision consistency across the label space")
        return notes
