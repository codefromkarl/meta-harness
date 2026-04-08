from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from meta_harness.loop.experience import assemble_experience_context
from meta_harness.optimizer_workflow import get_run_context_strategy


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))

def _read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")

def _collect_shared_run_context(run_dir: Path) -> dict[str, Any]:
    tasks_dir = run_dir / "tasks"
    task_summaries: list[dict[str, Any]] = []

    if not tasks_dir.exists():
        return {"tasks": task_summaries}

    for task_dir in sorted(path for path in tasks_dir.iterdir() if path.is_dir()):
        task_result = _read_json_if_exists(task_dir / "task_result.json")
        task_summaries.append(
            {
                "task_id": task_result.get("task_id", task_dir.name),
                "scenario": task_result.get("scenario"),
                "difficulty": task_result.get("difficulty"),
                "weight": task_result.get("weight"),
                "expectations": task_result.get("expectations"),
                "success": bool(task_result.get("success", False)),
                "completed_phases": int(task_result.get("completed_phases", 0)),
                "failed_phase": task_result.get("failed_phase"),
            }
        )

    context: dict[str, Any] = {"tasks": task_summaries}
    benchmark_context = _collect_benchmark_context(run_dir, task_summaries=task_summaries)
    if benchmark_context:
        context["benchmark"] = benchmark_context
    return context

def _flatten_signal_payload(payload: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, value in payload.items():
        dotted = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flattened.update(_flatten_signal_payload(value, dotted))
        else:
            flattened[dotted] = value
    return flattened

def _collect_benchmark_context(
    run_dir: Path,
    *,
    task_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    tasks_dir = run_dir / "tasks"
    if not tasks_dir.exists():
        return {}

    fingerprint_values: dict[str, list[Any]] = {}
    probe_values: dict[str, list[Any]] = {}
    validation: dict[str, Any] | None = None
    capability_gains: dict[str, dict[str, Any]] = {}

    for task_dir in sorted(path for path in tasks_dir.iterdir() if path.is_dir()):
        benchmark_probe = _read_json_if_exists(task_dir / "benchmark_probe.stdout.txt")
        fingerprint_payload = benchmark_probe.get("fingerprints")
        if isinstance(fingerprint_payload, dict):
            for key, value in _flatten_signal_payload(fingerprint_payload).items():
                fingerprint_values.setdefault(key, []).append(value)
        probe_payload = benchmark_probe.get("probes")
        if isinstance(probe_payload, dict):
            for key, value in _flatten_signal_payload(probe_payload).items():
                probe_values.setdefault(key, []).append(value)
        validation_payload = benchmark_probe.get("validation")
        if validation is None and isinstance(validation_payload, dict):
            validation = validation_payload

    for task in task_summaries:
        scenario = task.get("scenario")
        if not isinstance(scenario, str) or not scenario:
            continue
        entry = capability_gains.setdefault(
            scenario,
            {
                "task_count": 0,
                "repeat_count": 0,
                "success_count": 0,
                "weight_total": 0.0,
                "weight_success": 0.0,
            },
        )
        entry["task_count"] += 1
        entry["repeat_count"] += 1
        weight = float(task.get("weight", 1.0) or 1.0)
        entry["weight_total"] += weight
        if bool(task.get("success")):
            entry["success_count"] += 1
            entry["weight_success"] += weight

    summarized_capability: dict[str, Any] = {}
    for scenario, values in capability_gains.items():
        task_count = max(1, int(values["task_count"]))
        summarized_capability[scenario] = {
            "task_count": task_count,
            "repeat_count": int(values["repeat_count"] / task_count),
            "success_rate": float(values["success_count"]) / float(values["repeat_count"]),
            "weighted_success_rate": (
                float(values["weight_success"]) / float(values["weight_total"])
                if values["weight_total"] > 0
                else 0.0
            ),
        }

    mechanism: dict[str, Any] = {}
    if fingerprint_values:
        mechanism["fingerprints"] = {
            key: values[0] if len(set(map(str, values))) == 1 else values
            for key, values in sorted(fingerprint_values.items())
        }
    if probe_values:
        mechanism["probes"] = {}
        for key, values in sorted(probe_values.items()):
            if all(isinstance(value, (int, float)) for value in values):
                mechanism["probes"][key] = sum(float(value) for value in values) / len(values)
            else:
                mechanism["probes"][key] = values[0] if len(set(map(str, values))) == 1 else values
    if validation is not None:
        mechanism["validation"] = validation

    score_report = _read_json_if_exists(run_dir / "score_report.json")
    context: dict[str, Any] = {}
    if mechanism:
        context["mechanism"] = mechanism
    if summarized_capability:
        context["capability_gains"] = summarized_capability
    if score_report:
        context["ranking_score"] = float(score_report.get("composite", 0.0))
    return context

def _collect_run_context(run_dir: Path, profile_name: str) -> dict[str, Any]:
    return {
        **_collect_shared_run_context(run_dir),
        **get_run_context_strategy(profile_name).collect_run_context(run_dir),
    }

def _collect_failure_context(
    runs_root: Path,
    profile_name: str,
    project_name: str,
    history_sources: list[dict[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    payload = assemble_experience_context(
        runs_root=runs_root,
        candidates_root=runs_root.parent / "candidates",
        profile_name=profile_name,
        project_name=project_name,
        history_sources=history_sources,
        run_context_builder=lambda run_dir, record: _collect_run_context(
            run_dir,
            str(record.get("profile") or profile_name),
        ),
    )
    matching_runs = [
        dict(record)
        for record in payload.get("matching_runs", [])
        if isinstance(record, dict)
    ]
    failure_records: list[dict[str, Any]] = []
    for failure in payload.get("failure_records", []):
        if not isinstance(failure, dict):
            continue
        signature = str(failure.get("signature") or "")
        tokens = signature.split()
        family = " ".join(tokens[:2]) if len(tokens) >= 2 else signature
        failure_records.append(
            {
                **failure,
                "family": family,
            }
        )

    return matching_runs, failure_records
