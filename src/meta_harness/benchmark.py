from __future__ import annotations

import json
import shutil
import statistics
from pathlib import Path
from typing import Any
from uuid import uuid4

from meta_harness.candidates import create_candidate, load_candidate_record
from meta_harness.config_loader import load_effective_config
from meta_harness.runtime import execute_managed_run, freeze_workspace_source


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _round(value: float) -> float:
    return round(value, 6)


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _extract_task_scenarios(task_set_path: Path) -> list[dict[str, Any]]:
    task_set = _read_json(task_set_path)
    scenarios: list[dict[str, Any]] = []
    for task in task_set.get("tasks", []):
        if not isinstance(task, dict):
            continue
        scenario = task.get("scenario")
        difficulty = task.get("difficulty")
        weight = task.get("weight")
        if scenario is None and difficulty is None and weight is None:
            continue
        item: dict[str, Any] = {
            "task_id": str(task.get("task_id", "")),
            "scenario": scenario,
        }
        if difficulty is not None:
            item["difficulty"] = difficulty
        if weight is not None:
            item["weight"] = weight
        scenarios.append(item)
    return scenarios


def _resolve_code_patch_path(spec_path: Path, code_patch: Any) -> Path | None:
    if not isinstance(code_patch, str) or not code_patch.strip():
        return None
    candidate = Path(code_patch)
    if not candidate.is_absolute():
        candidate = (spec_path.parent / candidate).resolve()
    return candidate


def _parse_json_maybe(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if not raw:
        return {}
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {}
    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return {}


def _flatten_signals(payload: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in payload.items():
        dotted = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flat.update(_flatten_signals(value, dotted))
        else:
            flat[dotted] = value
    return flat


def _merge_signal_values(values: list[Any]) -> Any:
    if not values:
        return None
    if all(isinstance(value, (int, float)) for value in values):
        return _round(sum(float(value) for value in values) / len(values))
    first = values[0]
    if all(value == first for value in values):
        return first
    unique = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique


def _extract_run_mechanism(run_dir: Path) -> dict[str, Any]:
    fingerprints: dict[str, list[Any]] = {}
    probes: dict[str, list[Any]] = {}
    validations: list[dict[str, Any]] = []

    tasks_dir = run_dir / "tasks"
    if not tasks_dir.exists():
        return {}

    for task_dir in sorted(path for path in tasks_dir.iterdir() if path.is_dir()):
        payload = _parse_json_maybe(_read_text(task_dir / "benchmark_probe.stdout.txt"))
        if not payload:
            continue

        fingerprint_payload = payload.get("fingerprints")
        if isinstance(fingerprint_payload, dict):
            for key, value in _flatten_signals(fingerprint_payload).items():
                fingerprints.setdefault(key, []).append(value)

        probe_payload = payload.get("probes")
        if isinstance(probe_payload, dict):
            for key, value in _flatten_signals(probe_payload).items():
                probes.setdefault(key, []).append(value)

        validation_payload = payload.get("validation")
        if isinstance(validation_payload, dict):
            validations.append(validation_payload)

    mechanism: dict[str, Any] = {}
    if fingerprints:
        mechanism["fingerprints"] = {
            key: _merge_signal_values(values)
            for key, values in sorted(fingerprints.items())
        }
    if probes:
        mechanism["probes"] = {
            key: _merge_signal_values(values) for key, values in sorted(probes.items())
        }
    if validations:
        mechanism["validation"] = (
            validations[0] if len(validations) == 1 else validations
        )
    return mechanism


def _summarize_mechanisms(mechanisms: list[dict[str, Any]]) -> dict[str, Any]:
    fingerprints: dict[str, list[Any]] = {}
    probes: dict[str, list[Any]] = {}
    validations: list[Any] = []
    for mechanism in mechanisms:
        fingerprint_payload = mechanism.get("fingerprints")
        if isinstance(fingerprint_payload, dict):
            for key, value in fingerprint_payload.items():
                fingerprints.setdefault(key, []).append(value)
        probe_payload = mechanism.get("probes")
        if isinstance(probe_payload, dict):
            for key, value in probe_payload.items():
                probes.setdefault(key, []).append(value)
        validation_payload = mechanism.get("validation")
        if validation_payload is not None:
            validations.append(validation_payload)

    summary: dict[str, Any] = {}
    if fingerprints:
        summary["fingerprints"] = {
            key: _merge_signal_values(values)
            for key, values in sorted(fingerprints.items())
        }
    if probes:
        summary["probes"] = {
            key: _merge_signal_values(values) for key, values in sorted(probes.items())
        }
    if validations:
        summary["probe_validation"] = _merge_signal_values(validations)
    return summary


def _probe_condition_matches(expected: Any, observed: Any) -> bool:
    if isinstance(expected, dict):
        if observed is None:
            return False
        if "equals" in expected:
            return observed == expected["equals"]
        if "min" in expected:
            if not isinstance(observed, (int, float)):
                return False
            if float(observed) < float(expected["min"]):
                return False
        if "max" in expected:
            if not isinstance(observed, (int, float)):
                return False
            if float(observed) > float(expected["max"]):
                return False
        return True
    return observed == expected


def _validate_expected_signals(
    expected_signals: dict[str, Any] | None,
    mechanism: dict[str, Any],
) -> dict[str, Any]:
    if not expected_signals:
        return {
            "expected_signals_satisfied": True,
            "missing_signals": [],
            "mismatch_signals": [],
        }

    missing_signals: list[str] = []
    mismatch_signals: list[str] = []

    for section in ("fingerprints", "probes"):
        expected_section = expected_signals.get(section)
        observed_section = mechanism.get(section)
        if not isinstance(expected_section, dict):
            continue
        observed_section = (
            observed_section if isinstance(observed_section, dict) else {}
        )
        for key, expected in expected_section.items():
            if key not in observed_section:
                missing_signals.append(f"{section}.{key}")
                continue
            if not _probe_condition_matches(expected, observed_section[key]):
                mismatch_signals.append(f"{section}.{key}")

    return {
        "expected_signals_satisfied": not missing_signals and not mismatch_signals,
        "missing_signals": missing_signals,
        "mismatch_signals": mismatch_signals,
    }


def _load_task_results(run_dir: Path) -> list[dict[str, Any]]:
    tasks_dir = run_dir / "tasks"
    if not tasks_dir.exists():
        return []
    results: list[dict[str, Any]] = []
    for task_dir in sorted(path for path in tasks_dir.iterdir() if path.is_dir()):
        path = task_dir / "task_result.json"
        if path.exists():
            results.append(_read_json(path))
    return results


def _capability_summary(task_results: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    for task_result in task_results:
        scenario = task_result.get("scenario")
        if not isinstance(scenario, str) or not scenario:
            continue
        entry = grouped.setdefault(
            scenario,
            {
                "task_ids": set(),
                "invocations": 0,
                "successful_invocations": 0,
                "total_weight": 0.0,
                "successful_weight": 0.0,
            },
        )
        task_id = str(task_result.get("task_id", ""))
        entry["task_ids"].add(task_id)
        entry["invocations"] += 1
        success = bool(task_result.get("success"))
        if success:
            entry["successful_invocations"] += 1
        weight = float(task_result.get("weight", 1.0) or 1.0)
        entry["total_weight"] += weight
        if success:
            entry["successful_weight"] += weight

    summary: dict[str, Any] = {}
    for scenario, values in sorted(grouped.items()):
        invocation_count = max(1, int(values["invocations"]))
        task_count = max(1, len(values["task_ids"]))
        total_weight = float(values["total_weight"])
        successful_weight = float(values["successful_weight"])
        summary[scenario] = {
            "task_count": task_count,
            "repeat_count": int(invocation_count / task_count),
            "success_rate": _round(
                float(values["successful_invocations"]) / invocation_count
            ),
            "weighted_success_rate": _round(
                successful_weight / total_weight if total_weight > 0 else 0.0
            ),
        }
    return summary


def _apply_capability_deltas(
    capability_summary: dict[str, Any],
    baseline_summary: dict[str, Any],
) -> dict[str, Any]:
    scenarios = sorted(set(capability_summary) | set(baseline_summary))
    result: dict[str, Any] = {}
    for scenario in scenarios:
        current = capability_summary.get(scenario) or {
            "task_count": 0,
            "repeat_count": 0,
            "success_rate": 0.0,
            "weighted_success_rate": 0.0,
        }
        baseline = baseline_summary.get(scenario) or {
            "success_rate": 0.0,
            "weighted_success_rate": 0.0,
        }
        result[scenario] = {
            **current,
            "delta_from_baseline": {
                "success_rate": _round(
                    float(current.get("success_rate", 0.0))
                    - float(baseline.get("success_rate", 0.0))
                ),
                "weighted_success_rate": _round(
                    float(current.get("weighted_success_rate", 0.0))
                    - float(baseline.get("weighted_success_rate", 0.0))
                ),
            },
        }
    return result


def _best_by_stability(results: list[dict[str, Any]]) -> str:
    ranked = max(
        results,
        key=lambda item: (
            bool((item.get("stability_assessment") or {}).get("meets_min_repeats")),
            bool((item.get("stability_assessment") or {}).get("is_stable")),
            -float((item.get("stability") or {}).get("composite_range", 0.0)),
            -float((item.get("stability") or {}).get("composite_stddev", 0.0)),
            float((item.get("score") or {}).get("composite", 0.0)),
        ),
    )
    return str(ranked["name"])


def _ranking_score(
    *,
    score: dict[str, Any],
    baseline_score: dict[str, Any],
    stability: dict[str, Any],
    stability_assessment: dict[str, Any],
    policy: dict[str, Any],
) -> tuple[float, float, float, float]:
    composite = float(score.get("composite", 0.0))
    stability_penalty = 0.0
    if stability_assessment.get("is_high_score_unstable"):
        base_penalty = float(policy.get("unstable_high_score_penalty", 0.0))
        range_weight = float(policy.get("range_weight", 1.0))
        stddev_weight = float(policy.get("stddev_weight", 1.0))
        composite_range = float(stability.get("composite_range", 0.0))
        composite_stddev = float(stability.get("composite_stddev", 0.0))
        stability_penalty = composite * base_penalty
        stability_penalty += composite_range * range_weight
        stability_penalty += composite_stddev * stddev_weight

    cost_penalty = _cost_penalty(
        score=score,
        baseline_score=baseline_score,
        policy=policy,
    )
    total_penalty = stability_penalty + cost_penalty
    composite -= total_penalty
    return (
        _round(composite),
        _round(max(0.0, total_penalty)),
        _round(max(0.0, stability_penalty)),
        _round(max(0.0, cost_penalty)),
    )


def _cost_penalty(
    *,
    score: dict[str, Any],
    baseline_score: dict[str, Any],
    policy: dict[str, Any],
) -> float:
    raw_weights = policy.get("cost_weights")
    if not isinstance(raw_weights, dict):
        return 0.0

    current_cost = score.get("cost")
    baseline_cost = baseline_score.get("cost")
    if not isinstance(current_cost, dict) or not isinstance(baseline_cost, dict):
        return 0.0

    penalty = 0.0
    for key, weight in raw_weights.items():
        if not isinstance(weight, (int, float)):
            continue
        current_value = current_cost.get(key)
        baseline_value = baseline_cost.get(key)
        if not isinstance(current_value, (int, float)) or not isinstance(
            baseline_value, (int, float)
        ):
            continue
        penalty += max(0.0, float(current_value) - float(baseline_value)) * float(
            weight
        )
    return penalty


def _report_summary(payload: dict[str, Any]) -> dict[str, Any]:
    variants = payload.get("variants") or []
    ranked = sorted(
        variants,
        key=lambda item: (
            float(item.get("ranking_score", 0.0)),
            float((item.get("score") or {}).get("composite", 0.0)),
        ),
        reverse=True,
    )
    return {
        "best_variant": payload.get("best_variant"),
        "best_by_quality": payload.get("best_by_quality"),
        "best_by_stability": payload.get("best_by_stability"),
        "top_variants_by_ranking_score": [
            {
                "name": item.get("name"),
                "ranking_score": item.get("ranking_score"),
                "ranking_penalty": item.get("ranking_penalty", 0.0),
                "stability_penalty": item.get("stability_penalty", 0.0),
                "cost_penalty": item.get("cost_penalty", 0.0),
                "composite": (item.get("score") or {}).get("composite", 0.0),
            }
            for item in ranked[:3]
        ],
    }


def _generate_run_id_with_parity(parity: int) -> str:
    parity = parity % 2
    while True:
        candidate = uuid4().hex[:12]
        if int(candidate[-1], 16) % 2 == parity:
            return candidate


def _summarize_scores(scores: list[dict[str, Any]]) -> dict[str, Any]:
    if not scores:
        return {"composite": 0.0}

    summary = json.loads(json.dumps(scores[0]))
    if len(scores) == 1:
        return summary

    for section in (
        "correctness",
        "cost",
        "maintainability",
        "architecture",
        "retrieval",
        "human_collaboration",
    ):
        merged_section = summary.get(section)
        if not isinstance(merged_section, dict):
            continue
        keys = set()
        for score in scores:
            section_payload = score.get(section)
            if isinstance(section_payload, dict):
                keys.update(section_payload.keys())
        averaged: dict[str, Any] = {}
        for key in sorted(keys):
            values = []
            for score in scores:
                section_payload = score.get(section)
                value = (
                    section_payload.get(key)
                    if isinstance(section_payload, dict)
                    else None
                )
                if isinstance(value, (int, float)):
                    values.append(float(value))
            if values:
                averaged[key] = _round(sum(values) / len(values))
        summary[section] = averaged

    summary["composite"] = _round(
        max(float(score.get("composite", 0.0)) for score in scores)
    )
    return summary


def _stability_metrics(scores: list[dict[str, Any]]) -> dict[str, Any]:
    composites = [float(score.get("composite", 0.0)) for score in scores]
    if not composites:
        return {
            "repeat_count": 0,
            "composite_min": 0.0,
            "composite_max": 0.0,
            "composite_range": 0.0,
            "composite_stddev": 0.0,
        }

    stddev = statistics.pstdev(composites) if len(composites) > 1 else 0.0
    return {
        "repeat_count": len(composites),
        "composite_min": _round(min(composites)),
        "composite_max": _round(max(composites)),
        "composite_range": _round(max(composites) - min(composites)),
        "composite_stddev": _round(stddev),
    }


def _stability_policy(effective_config: dict[str, Any]) -> dict[str, Any]:
    evaluation = effective_config.get("evaluation")
    if not isinstance(evaluation, dict):
        evaluation = {}
    stability = evaluation.get("stability")
    if not isinstance(stability, dict):
        stability = {}
    policy: dict[str, Any] = {
        "min_repeats": max(1, int(stability.get("min_repeats", 1))),
        "max_composite_range": float(stability.get("max_composite_range", 1.0)),
        "high_score_threshold": float(stability.get("high_score_threshold", 0.0)),
        "range_weight": float(stability.get("range_weight", 1.0)),
        "stddev_weight": float(stability.get("stddev_weight", 1.0)),
    }
    if "unstable_high_score_penalty" in stability:
        policy["unstable_high_score_penalty"] = float(
            stability.get("unstable_high_score_penalty", 0.0)
        )
    cost_weights = stability.get("cost_weights")
    if isinstance(cost_weights, dict):
        policy["cost_weights"] = {
            str(key): float(value)
            for key, value in cost_weights.items()
            if isinstance(value, (int, float))
        }
    return policy


def _stability_assessment(
    *,
    score: dict[str, Any],
    stability: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, bool]:
    repeat_count = int(stability.get("repeat_count", 0))
    composite_range = float(stability.get("composite_range", 0.0))
    composite = float(score.get("composite", 0.0))
    is_stable = composite_range <= float(policy["max_composite_range"])
    return {
        "meets_min_repeats": repeat_count >= int(policy["min_repeats"]),
        "is_stable": is_stable,
        "is_high_score_unstable": composite >= float(policy["high_score_threshold"])
        and not is_stable,
    }


def _metric_keys_for_focus(focus: str | None) -> dict[str, set[str]]:
    if focus == "memory":
        return {
            "maintainability": {
                "memory_completeness",
                "memory_freshness",
                "memory_stale_ratio",
            }
        }
    if focus == "indexing":
        return {
            "architecture": {
                "vector_coverage_ratio",
                "index_freshness_ratio",
                "index_document_count",
                "index_chunk_count",
            },
            "cost": {
                "index_build_latency_ms",
                "index_peak_memory_mb",
                "index_size_bytes",
                "index_embedding_calls",
                "index_files_scanned_count",
                "index_files_reindexed_count",
                "index_query_p50_ms",
                "index_query_p95_ms",
            },
        }
    if focus == "retrieval":
        return {
            "retrieval": {
                "retrieval_hit_rate",
                "retrieval_mrr",
                "grounded_answer_rate",
            }
        }
    return {}


def _score_delta(
    baseline: dict[str, Any],
    current: dict[str, Any],
    *,
    focus: str | None = None,
) -> dict[str, Any]:
    delta: dict[str, Any] = {
        "composite": _round(
            float(current.get("composite", 0.0)) - float(baseline.get("composite", 0.0))
        )
    }
    allowed = _metric_keys_for_focus(focus)

    for section in ("maintainability", "architecture", "retrieval", "cost"):
        baseline_section = baseline.get(section) or {}
        current_section = current.get(section) or {}
        keys = set(baseline_section) | set(current_section)
        if focus is not None and section in allowed:
            keys &= allowed[section]
        elif focus is not None:
            continue

        section_delta: dict[str, float] = {}
        for key in sorted(keys):
            left = baseline_section.get(key)
            right = current_section.get(key)
            if not isinstance(left, (int, float)) or not isinstance(
                right, (int, float)
            ):
                continue
            section_delta[key] = _round(float(right) - float(left))
        if section_delta:
            delta[section] = section_delta

    return delta


def _focus_tiebreak_bonus(
    delta_from_baseline: dict[str, Any],
    *,
    focus: str | None,
) -> float:
    if focus == "indexing":
        architecture = delta_from_baseline.get("architecture") or {}
        if not isinstance(architecture, dict):
            return 0.0
        bonus = max(0.0, float(architecture.get("vector_coverage_ratio", 0.0)))
        bonus += max(0.0, float(architecture.get("index_freshness_ratio", 0.0)))
        return _round(bonus / 1000.0)

    if focus == "memory":
        maintainability = delta_from_baseline.get("maintainability") or {}
        if not isinstance(maintainability, dict):
            return 0.0
        bonus = max(0.0, float(maintainability.get("memory_completeness", 0.0)))
        bonus += max(0.0, float(maintainability.get("memory_freshness", 0.0)))
        bonus += max(0.0, -float(maintainability.get("memory_stale_ratio", 0.0)))
        return _round(bonus / 1000.0)

    if focus == "retrieval":
        retrieval = delta_from_baseline.get("retrieval") or {}
        if not isinstance(retrieval, dict):
            return 0.0
        bonus = max(0.0, float(retrieval.get("retrieval_hit_rate", 0.0)))
        bonus += max(0.0, float(retrieval.get("retrieval_mrr", 0.0)))
        bonus += max(0.0, float(retrieval.get("grounded_answer_rate", 0.0)))
        return _round(bonus / 1000.0)

    return 0.0


def run_benchmark(
    *,
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    profile_name: str,
    project_name: str,
    task_set_path: Path,
    spec_path: Path,
    focus: str | None = None,
    workspace_source_override: Path | None = None,
    effective_config_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spec = _read_json(spec_path)
    experiment = str(spec.get("experiment", spec_path.stem))
    analysis_mode = str(spec.get("analysis_mode", "parameter"))
    report = spec.get("report") or {}
    scenarios = spec.get("scenarios") or []
    task_scenarios = _extract_task_scenarios(task_set_path)
    variants = spec.get("variants") or []
    if not variants:
        raise ValueError("benchmark spec must include at least one variant")
    repeats = max(1, int(spec.get("repeats", 1)))

    baseline_name = str(spec.get("baseline") or variants[0]["name"])
    results: list[dict[str, Any]] = []
    benchmark_workspace_source = workspace_source_override
    benchmark_snapshot_dir: Path | None = None

    if benchmark_workspace_source is None:
        base_effective_config = (
            dict(effective_config_override)
            if isinstance(effective_config_override, dict)
            else load_effective_config(
                config_root=config_root,
                profile_name=profile_name,
                project_name=project_name,
            )
        )
        snapshot_root = runs_root / "_benchmark_sources"
        snapshot_root.mkdir(parents=True, exist_ok=True)
        benchmark_snapshot_dir = snapshot_root / f"{experiment}-{uuid4().hex[:12]}"
        benchmark_workspace_source = freeze_workspace_source(
            snapshot_dir=benchmark_snapshot_dir,
            effective_config=base_effective_config,
        )
    else:
        base_effective_config = (
            dict(effective_config_override)
            if isinstance(effective_config_override, dict)
            else load_effective_config(
                config_root=config_root,
                profile_name=profile_name,
                project_name=project_name,
            )
        )

    stability_policy = _stability_policy(base_effective_config)

    try:
        for variant in variants:
            variant_name = str(variant["name"])
            config_patch = variant.get("config_patch")
            variant_type = str(variant.get("variant_type", "parameter"))
            hypothesis = variant.get("hypothesis")
            implementation_id = variant.get("implementation_id")
            expected_signals = variant.get("expected_signals")
            tags = variant.get("tags")
            code_patch_path = _resolve_code_patch_path(
                spec_path, variant.get("code_patch")
            )
            candidate_id = create_candidate(
                candidates_root=candidates_root,
                config_root=config_root,
                profile_name=profile_name,
                project_name=project_name,
                effective_config_override=base_effective_config,
                config_patch=config_patch,
                code_patch_path=code_patch_path,
                notes=f"benchmark:{experiment}:{variant_name}",
                proposal={
                    "strategy": "benchmark_variant",
                    "experiment": experiment,
                    "variant": variant_name,
                    "variant_type": variant_type,
                    "hypothesis": hypothesis,
                    "implementation_id": implementation_id,
                },
                reuse_existing=True,
            )
            candidate = load_candidate_record(candidates_root, candidate_id)
            executions: list[dict[str, Any]] = []
            previous_run_dir: Path | None = None
            for repeat_index in range(repeats):
                execution = execute_managed_run(
                    runs_root=runs_root,
                    profile_name=profile_name,
                    project_name=project_name,
                    effective_config=candidate["effective_config"],
                    task_set_path=task_set_path,
                    candidate_id=candidate_id,
                    code_patch_path=Path(candidate["code_patch_path"])
                    if candidate.get("code_patch_path") is not None
                    else None,
                    workspace_source_override=benchmark_workspace_source,
                    run_id=_generate_run_id_with_parity(repeat_index)
                    if repeats > 1
                    else None,
                    seed_root_state_from=previous_run_dir,
                )
                executions.append(execution)
                previous_run_dir = runs_root / str(execution["run_id"])
            run_ids = [execution["run_id"] for execution in executions]
            summarized_score = _summarize_scores(
                [execution["score"] for execution in executions]
            )
            summarized_mechanism = _summarize_mechanisms(
                [_extract_run_mechanism(runs_root / run_id) for run_id in run_ids]
            )
            capability_summary = _capability_summary(
                [
                    task_result
                    for run_id in run_ids
                    for task_result in _load_task_results(runs_root / run_id)
                ]
            )
            variant_stability_policy = _stability_policy(candidate["effective_config"])

            result_item: dict[str, Any] = {
                "name": variant_name,
                "variant_type": variant_type,
                "candidate_id": candidate_id,
                "run_id": executions[0]["run_id"],
                "run_ids": run_ids,
                "score": summarized_score,
                "stability": _stability_metrics(
                    [execution["score"] for execution in executions]
                ),
                "mechanism": {
                    **summarized_mechanism,
                    "validation": _validate_expected_signals(
                        expected_signals
                        if isinstance(expected_signals, dict)
                        else None,
                        summarized_mechanism,
                    ),
                },
                "capability_gains": capability_summary,
                "stability_policy": variant_stability_policy,
            }
            if hypothesis is not None:
                result_item["hypothesis"] = hypothesis
            if implementation_id is not None:
                result_item["implementation_id"] = implementation_id
            if expected_signals is not None:
                result_item["expected_signals"] = expected_signals
            if tags is not None:
                result_item["tags"] = tags
            if code_patch_path is not None:
                result_item["code_patch"] = str(code_patch_path)
            results.append(result_item)
    finally:
        if benchmark_snapshot_dir is not None and benchmark_snapshot_dir.exists():
            shutil.rmtree(benchmark_snapshot_dir, ignore_errors=True)

    baseline = next((item for item in results if item["name"] == baseline_name), None)
    if baseline is None:
        raise ValueError(f"baseline variant '{baseline_name}' not found")

    best_by_quality = max(
        results, key=lambda item: float((item.get("score") or {}).get("composite", 0.0))
    )["name"]
    for item in results:
        item["delta_from_baseline"] = _score_delta(
            baseline["score"],
            item["score"],
            focus=focus,
        )
        item["stability_assessment"] = _stability_assessment(
            score=item["score"],
            stability=item["stability"],
            policy=item.get("stability_policy") or stability_policy,
        )
        ranking_score, ranking_penalty, stability_penalty, cost_penalty = (
            _ranking_score(
                score=item["score"],
                baseline_score=baseline["score"],
                stability=item["stability"],
                stability_assessment=item["stability_assessment"],
                policy=item.get("stability_policy") or stability_policy,
            )
        )
        focus_tiebreak_bonus = _focus_tiebreak_bonus(
            item["delta_from_baseline"],
            focus=focus,
        )
        item["focus_tiebreak_bonus"] = focus_tiebreak_bonus
        item["ranking_score"] = _round(ranking_score + focus_tiebreak_bonus)
        item["ranking_penalty"] = ranking_penalty
        item["stability_penalty"] = stability_penalty
        item["cost_penalty"] = cost_penalty
        item["capability_gains"] = _apply_capability_deltas(
            item.get("capability_gains") or {},
            baseline.get("capability_gains") or {},
        )

    best = max(results, key=lambda item: float(item.get("ranking_score", 0.0)))
    best_by_stability = _best_by_stability(results)

    payload = {
        "experiment": experiment,
        "baseline": baseline_name,
        "analysis_mode": analysis_mode,
        "report": report,
        "scenarios": scenarios,
        "task_scenarios": task_scenarios,
        "best_by_quality": best_by_quality,
        "best_by_stability": best_by_stability,
        "best_variant": best["name"],
        "stability_policy": stability_policy,
        "repeat_count": repeats,
        "focus": focus or "all",
        "variants": results,
    }
    payload["report_summary"] = _report_summary(payload)
    return payload


def run_benchmark_suite(
    *,
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    profile_name: str,
    project_name: str,
    task_set_path: Path,
    suite_path: Path,
) -> dict[str, Any]:
    suite = _read_json(suite_path)
    suite_name = str(suite.get("suite", suite_path.stem))
    benchmarks = suite.get("benchmarks") or []
    if not benchmarks:
        raise ValueError("benchmark suite must include at least one benchmark entry")

    results: list[dict[str, Any]] = []
    best_by_experiment: dict[str, str] = {}
    best_by_quality_by_experiment: dict[str, str] = {}
    best_by_stability_by_experiment: dict[str, str] = {}
    workspace_source_override: Path | None = None
    snapshot_dir: Path | None = None

    base_effective_config = load_effective_config(
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
    )
    snapshot_root = runs_root / "_suite_sources"
    snapshot_root.mkdir(parents=True, exist_ok=True)
    snapshot_dir = snapshot_root / f"{suite_name}-{uuid4().hex[:12]}"
    workspace_source_override = freeze_workspace_source(
        snapshot_dir=snapshot_dir,
        effective_config=base_effective_config,
    )

    try:
        for benchmark in benchmarks:
            spec_path = Path(str(benchmark["spec"]))
            focus = benchmark.get("focus")
            benchmark_task_set = benchmark.get("task_set")
            resolved_task_set = (
                Path(str(benchmark_task_set))
                if benchmark_task_set is not None
                else task_set_path
            )
            payload = run_benchmark(
                config_root=config_root,
                runs_root=runs_root,
                candidates_root=candidates_root,
                profile_name=profile_name,
                project_name=project_name,
                task_set_path=resolved_task_set,
                spec_path=spec_path,
                focus=str(focus) if focus is not None else None,
                workspace_source_override=workspace_source_override,
            )
            results.append(payload)
            best_by_experiment[payload["experiment"]] = payload["best_variant"]
            best_by_quality_by_experiment[payload["experiment"]] = payload[
                "best_by_quality"
            ]
            best_by_stability_by_experiment[payload["experiment"]] = payload[
                "best_by_stability"
            ]
    finally:
        if snapshot_dir is not None and snapshot_dir.exists():
            shutil.rmtree(snapshot_dir, ignore_errors=True)

    return {
        "suite": suite_name,
        "benchmark_count": len(results),
        "best_by_experiment": best_by_experiment,
        "best_by_quality_by_experiment": best_by_quality_by_experiment,
        "best_by_stability_by_experiment": best_by_stability_by_experiment,
        "benchmarks": results,
    }
