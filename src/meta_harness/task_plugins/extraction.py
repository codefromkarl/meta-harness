from __future__ import annotations

from pathlib import Path
from typing import Any

from meta_harness.task_plugins.base import BaseTaskPlugin


class ExtractionTaskPlugin(BaseTaskPlugin):
    def __init__(self) -> None:
        super().__init__(
            plugin_id="extraction",
            objective_label="Extraction optimization",
            default_focus="extraction",
            default_goal="improve field extraction completeness and format stability",
            default_evaluators=("basic",),
        )

    def _objective_overrides(
        self,
        effective_config: dict[str, Any],
        tasks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        required_fields: set[str] = set()
        artifact_requirements: set[str] = set()
        schema_stability_counts: dict[str, int] = {}

        for task in tasks:
            expectations = task.get("expectations")
            if not isinstance(expectations, dict):
                continue
            for field in expectations.get("required_fields") or []:
                text = str(field).strip()
                if text:
                    required_fields.add(text)
            for artifact in expectations.get("artifact_requirements") or []:
                text = str(artifact).strip()
                if text:
                    artifact_requirements.add(text)
            page_profile = expectations.get("page_profile")
            if isinstance(page_profile, dict):
                stability = str(page_profile.get("schema_stability") or "").strip()
                if stability:
                    schema_stability_counts[stability] = (
                        schema_stability_counts.get(stability, 0) + 1
                    )

        return {
            "extraction": {
                "task_count": len(tasks),
                "required_fields": sorted(required_fields),
                "artifact_requirements": sorted(artifact_requirements),
                "schema_stability_counts": dict(sorted(schema_stability_counts.items())),
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
            key=lambda run: (
                float(run.get("composite", 0.0)),
                str(run.get("run_id") or ""),
            ),
            reverse=True,
        )
        return {
            "extraction": {
                "best_references": score_ranked[:3],
                "required_fields": list(
                    (objective.get("extraction") or {}).get("required_fields") or []
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
        notes.append("prioritize field completeness and schema stability")
        return notes
