from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from meta_harness.archive import list_run_records
from meta_harness.config_loader import load_effective_config
from meta_harness.candidates import create_candidate, load_candidate_record
from meta_harness.failure_index import load_or_extract_failure_signatures
from meta_harness.optimizer_workflow import get_run_context_strategy
from meta_harness.runtime import execute_managed_run


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
    sources = history_sources or [{"profile": profile_name, "project": project_name}]
    source_pairs = {
        (source["profile"], source["project"])
        for source in sources
        if source.get("profile") and source.get("project")
    }
    matching_runs = [
        record
        for record in list_run_records(runs_root)
        if (record["profile"], record["project"]) in source_pairs
    ]

    failure_records: list[dict[str, Any]] = []
    for record in matching_runs:
        run_dir = runs_root / record["run_id"]
        record["run_context"] = _collect_run_context(run_dir, record["profile"])
        for failure in load_or_extract_failure_signatures(run_dir):
            tokens = failure["signature"].split()
            family = " ".join(tokens[:2]) if len(tokens) >= 2 else failure["signature"]
            failure_records.append(
                {
                    "run_id": record["run_id"],
                    "family": family,
                    **failure,
                }
            )

    return matching_runs, failure_records


def _run_proposal_command(
    command: list[str],
    payload: dict[str, Any],
    effective_config: dict[str, Any],
) -> dict[str, Any]:
    optimization_config = effective_config.get("optimization", {})
    workdir = optimization_config.get("proposal_workdir")
    if workdir is None:
        workdir = (
            effective_config.get("runtime", {}).get("workspace", {}).get("source_repo")
        )
    if workdir is None:
        workdir = "."

    completed = subprocess.run(
        command,
        cwd=Path(workdir),
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"proposal command failed: {completed.stderr.strip() or completed.stdout.strip()}"
        )

    try:
        return json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("proposal command returned invalid JSON") from exc


def propose_candidate_from_architecture_recommendation(
    *,
    config_root: Path,
    candidates_root: Path,
    profile_name: str,
    project_name: str,
    source_run_ids: list[str],
    architecture_recommendation: dict[str, Any],
    runs_root: Path | None = None,
) -> str:
    focus = str(architecture_recommendation.get("focus", "retrieval"))
    effective_config = load_effective_config(
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
    )
    proposal_strategy = str(
        architecture_recommendation.get(
            "proposal_strategy", f"explore_{focus}_method_family"
        )
    )
    hypothesis = str(architecture_recommendation.get("hypothesis", "")).strip()

    expected_signals = architecture_recommendation.get("expected_signals")
    if not isinstance(expected_signals, dict):
        if focus == "retrieval":
            expected_signals = {"probes": {"retrieval.retrieval_budget": {"min": 1}}}
        elif focus == "memory":
            expected_signals = {
                "probes": {"memory.routing_confidence": {"min": 0.5}}
            }
        else:
            expected_signals = {"probes": {"indexing.chunk_profile": {"min": 1}}}

    tags = architecture_recommendation.get("tags")
    if not isinstance(tags, list):
        tags = ["auto-propose", "method-family", focus]

    config_patch = _default_architecture_config_patch(
        focus=focus,
        architecture_recommendation=architecture_recommendation,
        effective_config=effective_config,
        reference_config=_best_reference_config(
            runs_root=runs_root,
            profile_name=profile_name,
            project_name=project_name,
            source_run_ids=source_run_ids,
        ),
        history_configs=_historical_reference_configs(
            runs_root=runs_root,
            profile_name=profile_name,
            project_name=project_name,
            source_run_ids=source_run_ids,
            focus=focus,
        ),
    )
    proposal = {
        "strategy": proposal_strategy,
        "variant_type": str(
            architecture_recommendation.get("variant_type", "method_family")
        ),
        "hypothesis": hypothesis,
        "source_runs": source_run_ids,
        "architecture_recommendation": architecture_recommendation,
        "expected_signals": expected_signals,
        "tags": tags,
    }

    return create_candidate(
        candidates_root=candidates_root,
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
        config_patch=config_patch,
        notes=f"architecture recommendation proposal: {proposal_strategy}",
        proposal=proposal,
    )


def _default_architecture_config_patch(
    *,
    focus: str,
    architecture_recommendation: dict[str, Any],
    effective_config: dict[str, Any],
    reference_config: dict[str, Any] | None = None,
    history_configs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    gap_signals = architecture_recommendation.get("gap_signals")
    gap_signals = gap_signals if isinstance(gap_signals, list) else []
    metric_thresholds = architecture_recommendation.get("metric_thresholds")
    metric_thresholds = metric_thresholds if isinstance(metric_thresholds, dict) else {}

    config_patch: dict[str, Any] = {
        "optimization": {
            "focus": focus,
            "architecture_recommendation": architecture_recommendation,
        }
    }

    if focus == "retrieval":
        is_strong_gap = len(gap_signals) >= 3 or (
            float(metric_thresholds.get("retrieval_hit_rate", 0.7)) >= 0.8
            and float(metric_thresholds.get("retrieval_mrr", 0.5)) >= 0.6
        )
        retrieval_candidates = [
            {"top_k": 12, "rerank_k": 24},
            {"top_k": 16, "rerank_k": 32},
            {"top_k": 20, "rerank_k": 40},
        ]
        candidate_index = 1 if is_strong_gap else 0
        selected, avoided_existing_band = _select_exploration_candidate(
            retrieval_candidates,
            candidate_index,
            current_config=effective_config.get("retrieval"),
            reference_config=(reference_config or {}).get("retrieval"),
        )
        config_patch["retrieval"] = (
            selected
            if avoided_existing_band
            else _nearest_historical_candidate(
                selected,
                current_config=effective_config.get("retrieval"),
                history_configs=history_configs,
            )
            or selected
        )
        return config_patch

    if focus == "memory":
        is_strong_gap = len(gap_signals) >= 3 or (
            float(metric_thresholds.get("memory_completeness", 0.8)) >= 0.85
            and float(metric_thresholds.get("memory_freshness", 0.85)) >= 0.9
        )
        memory_candidates = [
            {
                "enabled": True,
                "routing_mode": "freshness-biased",
                "freshness_bias": 0.8,
                "stale_prune_threshold": 0.12,
            },
            {
                "enabled": True,
                "routing_mode": "freshness-biased",
                "freshness_bias": 0.9,
                "stale_prune_threshold": 0.08,
            },
            {
                "enabled": True,
                "routing_mode": "strict-pruning",
                "freshness_bias": 0.95,
                "stale_prune_threshold": 0.05,
            },
        ]
        candidate_index = 1 if is_strong_gap else 0
        selected, avoided_existing_band = _select_exploration_candidate(
            memory_candidates,
            candidate_index,
            current_config=((effective_config.get("contextatlas") or {}).get("memory")),
            reference_config=(
                ((reference_config or {}).get("contextatlas") or {}).get("memory")
            ),
        )
        config_patch["contextatlas"] = {
            "memory": (
                selected
                if avoided_existing_band
                else _nearest_historical_candidate(
                    selected,
                    current_config=((effective_config.get("contextatlas") or {}).get("memory")),
                    history_configs=history_configs,
                )
                or selected
            ),
        }
        return config_patch

    if focus == "indexing":
        is_strong_gap = len(gap_signals) >= 2 or (
            float(metric_thresholds.get("vector_coverage_ratio", 0.9)) >= 0.95
            and float(metric_thresholds.get("index_freshness_ratio", 0.85)) >= 0.9
        )
        indexing_candidates = [
            {"chunk_size": 1200, "chunk_overlap": 160},
            {"chunk_size": 1400, "chunk_overlap": 200},
            {"chunk_size": 1600, "chunk_overlap": 240},
        ]
        candidate_index = 1 if is_strong_gap else 0
        selected, avoided_existing_band = _select_exploration_candidate(
            indexing_candidates,
            candidate_index,
            current_config=effective_config.get("indexing"),
            reference_config=(reference_config or {}).get("indexing"),
        )
        config_patch["indexing"] = (
            selected
            if avoided_existing_band
            else _nearest_historical_candidate(
                selected,
                current_config=effective_config.get("indexing"),
                history_configs=history_configs,
            )
            or selected
        )
        return config_patch

    return config_patch


def _select_exploration_candidate(
    candidates: list[dict[str, Any]],
    candidate_index: int,
    *,
    current_config: Any,
    reference_config: Any,
) -> tuple[dict[str, Any], bool]:
    candidate_index = max(0, min(candidate_index, len(candidates) - 1))
    selected = candidates[candidate_index]
    normalized_current = current_config if isinstance(current_config, dict) else {}
    normalized_reference = reference_config if isinstance(reference_config, dict) else {}
    avoided_existing_band = False

    while (
        candidate_index < len(candidates) - 1
        and (
            _is_same_candidate(selected, normalized_current)
            or _is_same_candidate(selected, normalized_reference)
        )
    ):
        avoided_existing_band = True
        candidate_index += 1
        selected = candidates[candidate_index]
    return selected, avoided_existing_band


def _is_same_candidate(candidate: dict[str, Any], config: dict[str, Any]) -> bool:
    if not config:
        return False
    for key, value in candidate.items():
        if config.get(key) != value:
            return False
    return True


def _nearest_historical_candidate(
    default_candidate: dict[str, Any],
    *,
    current_config: Any,
    history_configs: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if not history_configs:
        return None
    normalized_current = current_config if isinstance(current_config, dict) else {}
    available = [
        config
        for config in history_configs
        if isinstance(config, dict) and not _is_same_candidate(config, normalized_current)
    ]
    if not available:
        return None
    ranked = sorted(
        available,
        key=lambda config: (
            _candidate_distance(config, normalized_current),
            0 if not _is_same_candidate(config, default_candidate) else 1,
        ),
    )
    selected = ranked[0]
    if _is_same_candidate(selected, default_candidate):
        return None
    return selected


def _candidate_distance(candidate: dict[str, Any], config: dict[str, Any]) -> float:
    keys = sorted(set(candidate) | set(config))
    distance = 0.0
    for key in keys:
        left = candidate.get(key)
        right = config.get(key)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            distance += abs(float(left) - float(right))
        elif left != right:
            distance += 1.0
    return distance


def _best_reference_config(
    *,
    runs_root: Path | None,
    profile_name: str,
    project_name: str,
    source_run_ids: list[str],
) -> dict[str, Any] | None:
    if runs_root is None or not runs_root.exists():
        return None
    source_ids = set(source_run_ids)
    matching_runs = [
        record
        for record in list_run_records(runs_root)
        if record.get("profile") == profile_name
        and record.get("project") == project_name
        and record.get("run_id") in source_ids
        and isinstance(record.get("score"), dict)
    ]
    if not matching_runs:
        return None
    best = max(
        matching_runs,
        key=lambda record: float((record.get("score") or {}).get("composite", 0.0)),
    )
    config = best.get("config")
    return config if isinstance(config, dict) else None


def _historical_reference_configs(
    *,
    runs_root: Path | None,
    profile_name: str,
    project_name: str,
    source_run_ids: list[str],
    focus: str,
) -> list[dict[str, Any]]:
    if runs_root is None or not runs_root.exists():
        return []
    source_ids = set(source_run_ids)
    records = [
        record
        for record in list_run_records(runs_root)
        if record.get("profile") == profile_name
        and record.get("project") == project_name
        and record.get("run_id") in source_ids
    ]
    history: list[dict[str, Any]] = []
    for record in records:
        config = record.get("config")
        if not isinstance(config, dict):
            continue
        if focus == "retrieval":
            section = config.get("retrieval")
        elif focus == "indexing":
            section = config.get("indexing")
        else:
            section = (config.get("contextatlas") or {}).get("memory")
        if isinstance(section, dict):
            history.append(section)
    return history


def propose_candidate_from_failures(
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    profile_name: str,
    project_name: str,
) -> str:
    effective_config = load_effective_config(
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
    )
    matching_runs, failure_records = _collect_failure_context(
        runs_root=runs_root,
        profile_name=profile_name,
        project_name=project_name,
        history_sources=effective_config.get("optimization", {}).get("history_sources"),
    )

    proposal_command = effective_config.get("optimization", {}).get("proposal_command")
    if proposal_command:
        payload = {
            "profile": profile_name,
            "project": project_name,
            "effective_config": effective_config,
            "matching_runs": matching_runs,
            "failure_records": failure_records,
        }
        generated = _run_proposal_command(
            command=proposal_command,
            payload=payload,
            effective_config=effective_config,
        )
        return create_candidate(
            candidates_root=candidates_root,
            config_root=config_root,
            profile_name=profile_name,
            project_name=project_name,
            config_patch=generated.get("config_patch"),
            code_patch_content=generated.get("code_patch"),
            notes=generated.get("notes", "optimizer proposal from command"),
            proposal=generated.get("proposal"),
        )

    families: dict[str, list[dict[str, Any]]] = {}
    for failure in failure_records:
        families.setdefault(failure["family"], []).append(failure)

    best_family = ""
    best_records: list[dict[str, Any]] = []
    for family, records in families.items():
        if len(records) > len(best_records):
            best_family = family
            best_records = records

    source_runs = sorted({record["run_id"] for record in best_records})
    max_turns = 12
    if matching_runs:
        base_config = matching_runs[0]["config"]
        max_turns = int(base_config.get("budget", {}).get("max_turns", 12))

    config_patch = {"budget": {"max_turns": max_turns + 2}}
    proposal = {
        "strategy": "increase_budget_on_repeated_failures",
        "query": best_family,
        "source_runs": source_runs,
        "failure_count": len(best_records),
        "config_patch": config_patch,
    }

    notes = f"optimizer proposal from failures: {best_family}".strip()
    return create_candidate(
        candidates_root=candidates_root,
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
        config_patch=config_patch,
        notes=notes,
        proposal=proposal,
    )


def shadow_run_candidate(
    candidates_root: Path,
    runs_root: Path,
    candidate_id: str,
    task_set_path: Path,
) -> str:
    candidate = load_candidate_record(candidates_root, candidate_id)
    execution = execute_managed_run(
        runs_root=runs_root,
        profile_name=candidate["profile"],
        project_name=candidate["project"],
        effective_config=candidate["effective_config"],
        task_set_path=task_set_path,
        candidate_id=candidate_id,
        code_patch_path=Path(candidate["code_patch_path"])
        if candidate.get("code_patch_path") is not None
        else None,
    )
    return str(execution["run_id"])
