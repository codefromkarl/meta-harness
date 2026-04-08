from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from meta_harness.archive import list_run_records
from meta_harness.candidates import load_candidate_record
from meta_harness.failure_index import load_or_extract_failure_signatures


def list_experience_runs(
    *,
    runs_root: Path,
    profile_name: str,
    project_name: str,
    history_sources: list[dict[str, str]] | None = None,
    max_history: int | None = None,
    best_k: int | None = None,
) -> list[dict[str, Any]]:
    sources = history_sources or [{"profile": profile_name, "project": project_name}]
    source_pairs = {
        (str(source.get("profile") or ""), str(source.get("project") or ""))
        for source in sources
        if source.get("profile") and source.get("project")
    }
    matching_runs = [
        record
        for record in list_run_records(runs_root)
        if (str(record.get("profile") or ""), str(record.get("project") or "")) in source_pairs
    ]
    ordered = _sort_runs(matching_runs)
    if best_k is not None:
        ordered = _best_runs(ordered, best_k)
    if max_history is None:
        return ordered
    return ordered[-max_history:] if best_k is None else ordered[:max_history]


def assemble_experience_context(
    *,
    runs_root: Path,
    candidates_root: Path,
    profile_name: str,
    project_name: str,
    objective: dict[str, Any] | None = None,
    max_history: int = 25,
    history_sources: list[dict[str, str]] | None = None,
    run_context_builder: Callable[[Path, dict[str, Any]], dict[str, Any]] | None = None,
    best_k: int | None = None,
    focus: str | None = None,
    dedupe_failure_families: bool = False,
) -> dict[str, Any]:
    matching_runs = list_experience_runs(
        runs_root=runs_root,
        profile_name=profile_name,
        project_name=project_name,
        history_sources=history_sources,
        max_history=max_history,
        best_k=best_k,
    )

    failure_records: list[dict[str, Any]] = []
    scored_runs: list[dict[str, Any]] = []
    candidate_records: list[dict[str, Any]] = []
    enriched_runs: list[dict[str, Any]] = []
    representative_artifacts = {
        "trace_refs": [],
        "stdout_refs": [],
        "stderr_refs": [],
    }

    for record in matching_runs:
        enriched_record = dict(record)
        run_id = str(record["run_id"])
        run_dir = runs_root / run_id
        task_summary = _collect_task_summary(run_dir)
        enriched_record["task_summary"] = task_summary
        if run_context_builder is not None:
            enriched_record["run_context"] = run_context_builder(run_dir, enriched_record)
        if focus and not _matches_focus(enriched_record, focus):
            continue
        run_score = record.get("score") or {}
        if isinstance(run_score, dict):
            scored_runs.append(
                {
                    "run_id": run_id,
                    "profile": record.get("profile"),
                    "project": record.get("project"),
                    "score": run_score,
                }
            )
        for failure in load_or_extract_failure_signatures(run_dir):
            failure_records.append(
                {
                    "run_id": run_id,
                    "candidate_id": record.get("candidate_id"),
                    "family": _failure_family(failure),
                    **failure,
                }
            )
        candidate_id = record.get("candidate_id")
        if isinstance(candidate_id, str) and candidate_id:
            try:
                candidate_records.append(load_candidate_record(candidates_root, candidate_id))
            except FileNotFoundError:
                continue
        artifact_refs = _collect_artifact_refs(run_dir)
        for key, values in artifact_refs.items():
            representative_artifacts[key].extend(values)
        enriched_runs.append(enriched_record)

    if dedupe_failure_families:
        failure_records = _dedupe_failure_records(failure_records)

    representative_artifacts = {
        key: _dedupe_strings(values)
        for key, values in representative_artifacts.items()
    }
    best_run = _best_run(enriched_runs)
    source_run_ids = [str(record["run_id"]) for record in enriched_runs if record.get("run_id")]
    best_candidate_id = best_run.get("candidate_id") if best_run else None
    best_score = float((best_run.get("score") or {}).get("composite", 0.0)) if best_run else 0.0
    representative_failures = failure_records[: min(3, len(failure_records))]
    representative_successes = sorted(
        [
            {
                "run_id": record.get("run_id"),
                "candidate_id": record.get("candidate_id"),
                "score": record.get("score"),
            }
            for record in enriched_runs
            if float((record.get("score") or {}).get("composite", 0.0)) > 0.0
        ],
        key=lambda record: float((record.get("score") or {}).get("composite", 0.0)),
        reverse=True,
    )[:3]
    score_series = [
        float((record.get("score") or {}).get("composite", 0.0))
        for record in enriched_runs
    ]
    latest_score = score_series[-1] if score_series else 0.0
    earliest_score = score_series[0] if score_series else 0.0
    stability_summary = {
        "observed_run_count": len(score_series),
        "score_range": (max(score_series) - min(score_series)) if score_series else 0.0,
        "latest_score": latest_score,
        "best_score": best_score,
    }
    focus_summary = _focus_summary(enriched_runs, focus)
    capability_gaps = _capability_gaps(enriched_runs, focus)

    return {
        "objective": objective or {},
        "matching_runs": enriched_runs,
        "source_run_ids": source_run_ids,
        "failure_records": failure_records,
        "scored_runs": scored_runs,
        "candidate_records": candidate_records,
        "best_run": best_run,
        "best_candidate_id": best_candidate_id,
        "best_score": best_score,
        "score_delta": round(latest_score - earliest_score, 6),
        "stability_summary": stability_summary,
        "representative_failures": representative_failures,
        "representative_successes": representative_successes,
        "recent_run_ids": source_run_ids[-max_history:],
        "focus_summary": focus_summary,
        "representative_artifacts": representative_artifacts,
        "capability_gaps": capability_gaps,
    }


def _sort_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        runs,
        key=lambda record: (
            str(record.get("created_at") or ""),
            str(record.get("run_id") or ""),
        ),
    )


def _best_run(runs: list[dict[str, Any]]) -> dict[str, Any]:
    if not runs:
        return {}
    return max(
        runs,
        key=lambda record: float((record.get("score") or {}).get("composite", 0.0)),
    )


def _best_runs(runs: list[dict[str, Any]], best_k: int) -> list[dict[str, Any]]:
    if best_k <= 0:
        return []
    ranked = sorted(
        runs,
        key=lambda record: (
            float((record.get("score") or {}).get("composite", 0.0)),
            str(record.get("created_at") or ""),
            str(record.get("run_id") or ""),
        ),
        reverse=True,
    )
    return ranked[:best_k]


def _collect_task_summary(run_dir: Path) -> list[dict[str, Any]]:
    tasks_dir = run_dir / "tasks"
    if not tasks_dir.exists():
        return []
    summaries: list[dict[str, Any]] = []
    for task_dir in sorted(path for path in tasks_dir.iterdir() if path.is_dir()):
        task_result_path = task_dir / "task_result.json"
        if not task_result_path.exists():
            continue
        task_result = json.loads(task_result_path.read_text(encoding="utf-8"))
        summaries.append(
            {
                "task_id": task_result.get("task_id", task_dir.name),
                "scenario": task_result.get("scenario"),
                "success": bool(task_result.get("success", False)),
                "failed_phase": task_result.get("failed_phase"),
            }
        )
    return summaries


def _matches_focus(record: dict[str, Any], focus: str) -> bool:
    normalized_focus = focus.strip().lower()
    if not normalized_focus:
        return True
    score = record.get("score") or {}
    if isinstance(score, dict):
        for key, value in score.items():
            if str(key).strip().lower() != normalized_focus:
                continue
            if isinstance(value, dict) and _has_meaningful_signal(value):
                return True
            if isinstance(value, (int, float)) and float(value) != 0.0:
                return True
    for task in record.get("task_summary", []):
        if not isinstance(task, dict):
            continue
        scenario = str(task.get("scenario") or "").strip().lower()
        failed_phase = str(task.get("failed_phase") or "").strip().lower()
        if normalized_focus in {scenario, failed_phase}:
            return True
    run_context = record.get("run_context") or {}
    benchmark = run_context.get("benchmark") if isinstance(run_context, dict) else {}
    capability_gains = benchmark.get("capability_gains") if isinstance(benchmark, dict) else {}
    return normalized_focus in {
        str(key).strip().lower()
        for key in capability_gains.keys()
    }


def _has_meaningful_signal(payload: dict[str, Any]) -> bool:
    for value in payload.values():
        if isinstance(value, dict) and _has_meaningful_signal(value):
            return True
        if isinstance(value, (int, float)) and float(value) != 0.0:
            return True
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, bool) and value:
            return True
    return False


def _failure_family(failure: dict[str, Any]) -> str:
    signature = str(failure.get("signature") or "").strip()
    tokens = signature.split()
    if len(tokens) >= 2:
        return " ".join(tokens[:2])
    return signature


def _dedupe_failure_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for record in records:
        family = str(record.get("family") or "")
        if family in seen:
            continue
        seen.add(family)
        deduped.append(record)
    return deduped


def _collect_artifact_refs(run_dir: Path) -> dict[str, list[str]]:
    refs = {
        "trace_refs": [],
        "stdout_refs": [],
        "stderr_refs": [],
    }
    for task_dir in sorted((run_dir / "tasks").iterdir()) if (run_dir / "tasks").exists() else []:
        if not task_dir.is_dir():
            continue
        base = f"runs/{run_dir.name}/tasks/{task_dir.name}"
        if (task_dir / "steps.jsonl").exists():
            refs["trace_refs"].append(f"{base}/steps.jsonl")
        if (task_dir / "stdout.txt").exists():
            refs["stdout_refs"].append(f"{base}/stdout.txt")
        stderr_path = task_dir / "stderr.txt"
        if stderr_path.exists() and stderr_path.read_text(encoding="utf-8").strip():
            refs["stderr_refs"].append(f"{base}/stderr.txt")
    return refs


def _focus_summary(runs: list[dict[str, Any]], focus: str | None) -> dict[str, Any]:
    return {
        "focus": focus,
        "matching_run_count": len(runs),
    }


def _capability_gaps(runs: list[dict[str, Any]], focus: str | None) -> list[dict[str, Any]]:
    if not focus:
        return []
    scores: dict[str, list[float]] = {}
    for run in runs:
        score = run.get("score") or {}
        focus_payload = score.get(focus) if isinstance(score, dict) else None
        if not isinstance(focus_payload, dict):
            continue
        for key, value in focus_payload.items():
            if isinstance(value, (int, float)):
                scores.setdefault(str(key), []).append(float(value))
    gaps: list[dict[str, Any]] = []
    for metric, values in sorted(scores.items()):
        if not values:
            continue
        gaps.append(
            {
                "focus": focus,
                "metric": metric,
                "current": values[-1],
                "best": max(values),
                "gap": round(max(values) - min(values), 6),
            }
        )
    return gaps


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
