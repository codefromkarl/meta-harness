from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meta_harness.archive import list_run_records
from meta_harness.observation_strategies import (
    ObservationStrategy,
    resolve_observation_strategy,
)


def _parse_created_at(raw: Any) -> datetime:
    if not raw:
        return datetime.min.replace(tzinfo=UTC)
    text = str(raw).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)


def _score_or_empty(run: dict[str, Any] | None) -> dict[str, Any]:
    if not run:
        return {}
    return run.get("score") or {}


def _composite(score: dict[str, Any] | None) -> float:
    if not score:
        return 0.0
    return float(score.get("composite", 0.0))


def _sort_key(run: dict[str, Any]) -> tuple[datetime, str]:
    return (_parse_created_at(run.get("created_at")), str(run.get("run_id", "")))


def _run_summary_item(
    run: dict[str, Any],
    *,
    strategy: ObservationStrategy,
    thresholds: dict[str, dict[str, float]],
) -> dict[str, Any]:
    score = _score_or_empty(run)
    return {
        "run_id": run.get("run_id"),
        "created_at": run.get("created_at"),
        "composite": _composite(score),
        "needs_optimization": strategy.needs_optimization(score, thresholds),
        "recommended_focus": strategy.recommended_focus(score, thresholds),
    }


def _select_reference_runs(
    runs: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not runs:
        return None, None

    latest_run = max(
        runs,
        key=lambda run: (
            _parse_created_at(run.get("created_at")),
            run.get("run_id", ""),
        ),
    )
    best_run = max(
        runs,
        key=lambda run: (
            _composite(_score_or_empty(run)),
            _parse_created_at(run.get("created_at")),
            str(run.get("run_id", "")),
        ),
    )
    return latest_run, best_run


def list_observation_runs(
    runs_root: Path,
    profile_name: str,
    project_name: str,
) -> list[dict[str, Any]]:
    runs = [
        record
        for record in list_run_records(runs_root)
        if record.get("profile") == profile_name
        and record.get("project") == project_name
    ]
    return sorted(runs, key=_sort_key, reverse=True)


def load_metric_thresholds(
    config_root: Path,
    profile_name: str,
    project_name: str,
) -> dict[str, dict[str, float]]:
    strategy = resolve_observation_strategy(config_root, profile_name, project_name)
    return strategy.load_thresholds(config_root, profile_name, project_name)


def summarize_observation(
    runs_root: Path,
    profile_name: str,
    project_name: str,
    *,
    config_root: Path = Path("configs"),
    limit: int | None = None,
) -> dict[str, Any]:
    runs = list_observation_runs(runs_root, profile_name, project_name)
    latest_run, best_run = _select_reference_runs(runs)
    strategy = resolve_observation_strategy(config_root, profile_name, project_name)
    thresholds = load_metric_thresholds(config_root, profile_name, project_name)

    latest_score = _score_or_empty(latest_run)
    best_score = _score_or_empty(best_run)

    recommended_focus = strategy.recommended_focus(latest_score, thresholds)
    needs_optimization = strategy.needs_optimization(latest_score, thresholds)
    architecture_recommendation = strategy.architecture_recommendation(
        latest_score,
        thresholds,
    )

    summary: dict[str, Any] = {
        "run_count": len(runs),
        "latest_run_id": latest_run.get("run_id") if latest_run else None,
        "best_run_id": best_run.get("run_id") if best_run else None,
        "latest_score": latest_score if latest_score else None,
        "best_score": best_score if best_score else None,
        "composite_delta_from_best": _composite(latest_score) - _composite(best_score),
        "maintainability": latest_score.get("maintainability", {})
        if latest_score
        else {},
        "architecture": latest_score.get("architecture", {}) if latest_score else {},
        "retrieval": latest_score.get("retrieval", {}) if latest_score else {},
        "needs_optimization": needs_optimization,
        "recommended_focus": recommended_focus,
        "architecture_recommendation": architecture_recommendation,
    }

    if limit is not None:
        summary["history"] = [
            _run_summary_item(
                run,
                strategy=strategy,
                thresholds=thresholds,
            )
            for run in runs[: max(limit, 0)]
        ]

    return summary
