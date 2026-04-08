from __future__ import annotations

import json
from abc import ABC
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text


def _score_composite(run: dict[str, Any]) -> float:
    score = run.get("score")
    if not isinstance(score, dict):
        score = run.get("score_report")
    if not isinstance(score, dict):
        return float(run.get("composite", 0.0) or 0.0)
    return float(score.get("composite", run.get("composite", 0.0)) or 0.0)


def _task_items(task_set_path: Path) -> list[dict[str, Any]]:
    payload = _read_json(task_set_path)
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        return []
    return [task for task in tasks if isinstance(task, dict)]


def _summarize_task(task: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "task_id": _normalize_text(task.get("task_id")) or task.get("task_id"),
        "scenario": task.get("scenario"),
    }
    for key in ("difficulty", "weight", "expectations", "binding", "workdir"):
        if key in task and task.get(key) is not None:
            summary[key] = task.get(key)
    phase_count = task.get("phases")
    if isinstance(phase_count, list):
        summary["phase_count"] = len(phase_count)
    return summary


def _summarize_run(run: dict[str, Any]) -> dict[str, Any]:
    score = run.get("score")
    if not isinstance(score, dict):
        score = run.get("score_report")
    summary = {
        "run_id": run.get("run_id"),
        "profile": run.get("profile"),
        "project": run.get("project"),
        "created_at": run.get("created_at"),
        "composite": _score_composite(run),
        "candidate_id": run.get("candidate_id"),
    }
    if isinstance(score, dict):
        summary["score"] = score
    if run.get("run_context") is not None:
        summary["run_context"] = run.get("run_context")
    return summary


@runtime_checkable
class TaskPlugin(Protocol):
    plugin_id: str

    def assemble_objective(
        self,
        *,
        profile_name: str,
        project_name: str,
        task_set_path: Path,
        effective_config: dict[str, Any],
    ) -> dict[str, Any]: ...

    def assemble_experience(
        self,
        *,
        runs_root: Path,
        candidates_root: Path,
        selected_runs: list[dict[str, Any]],
        objective: dict[str, Any],
    ) -> dict[str, Any]: ...

    def build_evaluation_plan(
        self,
        *,
        objective: dict[str, Any],
        effective_config: dict[str, Any],
    ) -> dict[str, Any]: ...

    def build_experience_query(
        self,
        *,
        objective: dict[str, Any],
        effective_config: dict[str, Any],
    ) -> dict[str, Any]: ...

    def build_proposal_constraints(
        self,
        *,
        objective: dict[str, Any],
        effective_config: dict[str, Any],
        experience: dict[str, Any],
        evaluation_plan: dict[str, Any],
    ) -> dict[str, Any]: ...

    def build_stopping_policy(
        self,
        *,
        objective: dict[str, Any],
        effective_config: dict[str, Any],
        evaluation_plan: dict[str, Any],
    ) -> dict[str, Any]: ...

    def summarize_iteration(
        self,
        *,
        benchmark_payload: dict[str, Any],
        selected_variant: dict[str, Any],
    ) -> dict[str, Any]: ...


@dataclass(slots=True)
class BaseTaskPlugin(ABC):
    plugin_id: str
    objective_label: str
    default_focus: str
    default_goal: str
    default_evaluators: tuple[str, ...] = ("basic",)

    def assemble_objective(
        self,
        *,
        profile_name: str,
        project_name: str,
        task_set_path: Path,
        effective_config: dict[str, Any],
    ) -> dict[str, Any]:
        tasks = [_summarize_task(task) for task in _task_items(task_set_path)]
        task_ids = [
            str(item.get("task_id"))
            for item in tasks
            if str(item.get("task_id") or "")
        ]
        scenarios = [
            item.get("scenario")
            for item in tasks
            if item.get("scenario") is not None
        ]
        objective = {
            "plugin_id": self.plugin_id,
            "objective_label": self.objective_label,
            "focus": self.default_focus,
            "goal": self.default_goal,
            "profile_name": profile_name,
            "project_name": project_name,
            "task_set_path": str(task_set_path),
            "task_count": len(tasks),
            "task_ids": task_ids,
            "task_summaries": tasks,
            "scenarios": scenarios,
            "default_evaluators": list(self.default_evaluators),
            "evaluation_hint": self._evaluation_hint(effective_config, tasks),
            "constraints": self._objective_constraints(effective_config, tasks),
        }
        objective.update(self._objective_overrides(effective_config, tasks))
        return objective

    def assemble_experience(
        self,
        *,
        runs_root: Path,
        candidates_root: Path,
        selected_runs: list[dict[str, Any]],
        objective: dict[str, Any],
    ) -> dict[str, Any]:
        run_summaries = [_summarize_run(run) for run in selected_runs]
        best_run = max(run_summaries, key=lambda run: (float(run["composite"]), str(run.get("run_id") or "")), default=None)
        recent_run = run_summaries[-1] if run_summaries else None
        average_composite = (
            sum(float(run["composite"]) for run in run_summaries) / len(run_summaries)
            if run_summaries
            else 0.0
        )
        experience = {
            "plugin_id": self.plugin_id,
            "objective": objective,
            "history": {
                "run_count": len(run_summaries),
                "run_ids": [run.get("run_id") for run in run_summaries if run.get("run_id")],
                "runs": run_summaries,
                "best_run": best_run,
                "recent_run": recent_run,
                "average_composite": average_composite,
            },
            "repository": {
                "runs_root": str(runs_root),
                "candidates_root": str(candidates_root),
            },
        }
        experience.update(self._experience_overrides(runs_root, candidates_root, run_summaries, objective))
        return experience

    def build_evaluation_plan(
        self,
        *,
        objective: dict[str, Any],
        effective_config: dict[str, Any],
    ) -> dict[str, Any]:
        evaluation_config = effective_config.get("evaluation")
        evaluators = []
        if isinstance(evaluation_config, dict):
            evaluators = evaluation_config.get("evaluators") or []
        selected_evaluators = [str(item) for item in evaluators if str(item)]
        if not selected_evaluators:
            selected_evaluators = list(self.default_evaluators)
        plan = {
            "plugin_id": self.plugin_id,
            "objective": objective,
            "mode": "benchmark",
            "evaluators": selected_evaluators,
            "selection_policy": "best_by_score",
            "stopping_policy": "max_iterations_or_plateau",
            "notes": self._evaluation_plan_notes(objective, effective_config, selected_evaluators),
        }
        if isinstance(evaluation_config, dict):
            validation_command = evaluation_config.get("validation_command")
            if isinstance(validation_command, list):
                plan["validation_command"] = [str(item) for item in validation_command]
            validation_workdir = evaluation_config.get("validation_workdir")
            if validation_workdir is not None:
                plan["validation_workdir"] = str(validation_workdir)
        return plan

    def build_experience_query(
        self,
        *,
        objective: dict[str, Any],
        effective_config: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "focus": objective.get("focus"),
        }

    def build_proposal_constraints(
        self,
        *,
        objective: dict[str, Any],
        effective_config: dict[str, Any],
        experience: dict[str, Any],
        evaluation_plan: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "focus": objective.get("focus"),
            "default_evaluators": objective.get("default_evaluators") or [],
        }

    def build_stopping_policy(
        self,
        *,
        objective: dict[str, Any],
        effective_config: dict[str, Any],
        evaluation_plan: dict[str, Any],
    ) -> dict[str, Any]:
        return {}

    def summarize_iteration(
        self,
        *,
        benchmark_payload: dict[str, Any],
        selected_variant: dict[str, Any],
    ) -> dict[str, Any]:
        variants = benchmark_payload.get("variants")
        if not isinstance(variants, list):
            variants = []
        selected_run_ids = selected_variant.get("run_ids")
        if not isinstance(selected_run_ids, list):
            selected_run_ids = []
        score = selected_variant.get("score")
        if not isinstance(score, dict):
            score = {}
        return {
            "plugin_id": self.plugin_id,
            "experiment": benchmark_payload.get("experiment"),
            "selected_variant": selected_variant.get("name"),
            "selected_candidate_id": selected_variant.get("candidate_id"),
            "selected_run_id": selected_variant.get("run_id"),
            "selected_run_ids": [str(item) for item in selected_run_ids if str(item)],
            "best_by_quality": benchmark_payload.get("best_by_quality"),
            "best_by_stability": benchmark_payload.get("best_by_stability"),
            "variant_count": len(variants),
            "composite": float(score.get("composite", 0.0) or 0.0),
            "stability": selected_variant.get("stability") or {},
            "capability_gains": selected_variant.get("capability_gains") or {},
            "summary": self._iteration_summary_notes(benchmark_payload, selected_variant),
        }

    def _objective_overrides(
        self,
        effective_config: dict[str, Any],
        tasks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {}

    def _objective_constraints(
        self,
        effective_config: dict[str, Any],
        tasks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "max_tasks": len(tasks),
            "allowed_evaluators": list(self.default_evaluators),
        }

    def _evaluation_hint(
        self,
        effective_config: dict[str, Any],
        tasks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "task_count": len(tasks),
            "task_set_mode": "json",
        }

    def _experience_overrides(
        self,
        runs_root: Path,
        candidates_root: Path,
        run_summaries: list[dict[str, Any]],
        objective: dict[str, Any],
    ) -> dict[str, Any]:
        return {}

    def _evaluation_plan_notes(
        self,
        objective: dict[str, Any],
        effective_config: dict[str, Any],
        evaluators: list[str],
    ) -> list[str]:
        return [
            f"plugin={self.plugin_id}",
            f"evaluators={','.join(evaluators)}",
        ]

    def _iteration_summary_notes(
        self,
        benchmark_payload: dict[str, Any],
        selected_variant: dict[str, Any],
    ) -> list[str]:
        notes = [f"experiment={benchmark_payload.get('experiment')}"]
        if selected_variant.get("name"):
            notes.append(f"selected_variant={selected_variant.get('name')}")
        if selected_variant.get("candidate_id"):
            notes.append(f"candidate_id={selected_variant.get('candidate_id')}")
        return notes
