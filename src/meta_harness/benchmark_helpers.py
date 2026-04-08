from __future__ import annotations

import json
import shutil
import statistics
from pathlib import Path
from typing import Any
from uuid import uuid4

from meta_harness.candidates import create_candidate, load_candidate_record
from meta_harness.config_loader import load_effective_config, merge_dicts
from meta_harness.runtime_execution import execute_managed_run
from meta_harness.runtime_workspace import freeze_workspace_source
from meta_harness.signal_validation import validate_expected_signals


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
        stability_penalty += float(stability.get("cost_weighted_range", 0.0))
        stability_penalty += float(stability.get("cost_weighted_stddev", 0.0))

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

def _transfer_dashboard(results: list[dict[str, Any]]) -> dict[str, Any]:
    experiments: list[dict[str, Any]] = []
    primitive_buckets: dict[str, list[dict[str, Any]]] = {}

    for payload in results:
        focus = str(payload.get("focus", "all"))
        variants = payload.get("variants") or []
        if not isinstance(variants, list) or not variants:
            continue
        best_variant_name = str(payload.get("best_variant", ""))
        best_variant = next(
            (item for item in variants if str(item.get("name")) == best_variant_name),
            None,
        )
        if not isinstance(best_variant, dict):
            continue

        score = best_variant.get("score") or {}
        capability_scores = score.get("capability_scores") or {}
        workflow_scores = score.get("workflow_scores") or {}
        if not isinstance(capability_scores, dict) or not isinstance(workflow_scores, dict):
            continue

        primitive_id, primitive_metrics = _transfer_primitive_metrics(
            capability_scores,
            focus=focus,
        )
        if primitive_id is None or not isinstance(primitive_metrics, dict):
            continue

        experiment_item = {
            "experiment": str(payload.get("experiment", "")),
            "primitive_id": primitive_id,
            "best_variant": best_variant_name,
            "binding_id": best_variant.get("binding_id"),
            "focus": focus,
            "binding_execution_rate": _round(
                float(workflow_scores.get("binding_execution_rate", 0.0))
            ),
            "method_trace_coverage_rate": _round(
                float(workflow_scores.get("method_trace_coverage_rate", 0.0))
            ),
            "binding_payload_rate": _round(
                float(primitive_metrics.get("binding_payload_rate", 0.0))
            ),
            "assistant_reply_rate": _round(
                float(primitive_metrics.get("assistant_reply_rate", 0.0))
            ),
            "artifact_coverage_rate": _round(
                float(primitive_metrics.get("artifact_coverage_rate", 0.0))
            ),
        }
        experiments.append(experiment_item)
        primitive_buckets.setdefault(primitive_id, []).append(experiment_item)

    ordered_experiments = sorted(
        experiments,
        key=lambda item: (str(item["primitive_id"]), str(item["experiment"])),
    )
    by_primitive: dict[str, Any] = {}
    for primitive_id, items in sorted(primitive_buckets.items()):
        bindings = sorted(
            {
                str(item["binding_id"])
                for item in items
                if isinstance(item.get("binding_id"), str) and item.get("binding_id")
            }
        )
        by_primitive[primitive_id] = {
            "experiment_count": len(items),
            "bindings": bindings,
            "average_binding_execution_rate": _round(
                sum(float(item["binding_execution_rate"]) for item in items) / len(items)
            ),
            "average_method_trace_coverage_rate": _round(
                sum(float(item["method_trace_coverage_rate"]) for item in items) / len(items)
            ),
            "average_binding_payload_rate": _round(
                sum(float(item["binding_payload_rate"]) for item in items) / len(items)
            ),
            "average_assistant_reply_rate": _round(
                sum(float(item["assistant_reply_rate"]) for item in items) / len(items)
            ),
            "average_artifact_coverage_rate": _round(
                sum(float(item["artifact_coverage_rate"]) for item in items) / len(items)
            ),
        }

    return {
        "experiment_count": len(ordered_experiments),
        "experiments": ordered_experiments,
        "by_primitive": by_primitive,
    }

def _transfer_primitive_metrics(
    capability_scores: dict[str, Any],
    *,
    focus: str,
) -> tuple[str | None, dict[str, Any] | None]:
    for primitive_id, payload in capability_scores.items():
        if not isinstance(payload, dict):
            continue
        if any(
            key in payload
            for key in (
                "binding_payload_rate",
                "assistant_reply_rate",
                "artifact_coverage_rate",
            )
        ):
            return str(primitive_id), payload
    if focus == "binding" and capability_scores:
        primitive_id = sorted(capability_scores.keys())[0]
        payload = capability_scores.get(primitive_id)
        if isinstance(payload, dict):
            return str(primitive_id), payload
    return None, None

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

def _weighted_cost_measure(
    score: dict[str, Any], policy: dict[str, Any]
) -> float | None:
    raw_weights = policy.get("cost_weights")
    if not isinstance(raw_weights, dict):
        return None

    current_cost = score.get("cost")
    if not isinstance(current_cost, dict):
        return None

    total = 0.0
    has_numeric = False
    for key, weight in raw_weights.items():
        if not isinstance(weight, (int, float)):
            continue
        current_value = current_cost.get(key)
        if not isinstance(current_value, (int, float)):
            continue
        total += float(current_value) * float(weight)
        has_numeric = True
    if not has_numeric:
        return None
    return _round(total)

def _stability_metrics(
    scores: list[dict[str, Any]], *, policy: dict[str, Any] | None = None
) -> dict[str, Any]:
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
    metrics = {
        "repeat_count": len(composites),
        "composite_min": _round(min(composites)),
        "composite_max": _round(max(composites)),
        "composite_range": _round(max(composites) - min(composites)),
        "composite_stddev": _round(stddev),
    }

    effective_policy = policy or {}
    weighted_costs = [
        value
        for score in scores
        if (value := _weighted_cost_measure(score, effective_policy)) is not None
    ]
    if weighted_costs:
        cost_stddev = statistics.pstdev(weighted_costs) if len(weighted_costs) > 1 else 0.0
        metrics.update(
            {
                "cost_weighted_min": _round(min(weighted_costs)),
                "cost_weighted_max": _round(max(weighted_costs)),
                "cost_weighted_range": _round(max(weighted_costs) - min(weighted_costs)),
                "cost_weighted_stddev": _round(cost_stddev),
            }
        )
    return metrics

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
    if "max_cost_weighted_range" in stability:
        policy["max_cost_weighted_range"] = float(
            stability.get("max_cost_weighted_range", 0.0)
        )
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
    is_cost_stable = True
    if "max_cost_weighted_range" in policy:
        is_cost_stable = float(stability.get("cost_weighted_range", 0.0)) <= float(
            policy["max_cost_weighted_range"]
        )
    is_stable = composite_range <= float(policy["max_composite_range"]) and is_cost_stable
    result = {
        "meets_min_repeats": repeat_count >= int(policy["min_repeats"]),
        "is_stable": is_stable,
        "is_high_score_unstable": composite >= float(policy["high_score_threshold"])
        and not is_stable,
    }
    if "max_cost_weighted_range" in policy:
        result["is_cost_stable"] = is_cost_stable
    return result

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

def _candidate_harness_payload(variant: dict[str, Any]) -> dict[str, Any] | None:
    candidate_harness = variant.get("candidate_harness")
    if isinstance(candidate_harness, dict):
        return dict(candidate_harness)
    harness = variant.get("harness")
    if isinstance(harness, dict):
        return dict(harness)
    return None

def _candidate_harness_proposal_payload(
    *,
    experiment: str,
    variant_name: str,
    candidate_harness: dict[str, Any],
) -> dict[str, Any]:
    proposal = {
        "strategy": "benchmark_variant",
        "experiment": experiment,
        "variant": variant_name,
        "variant_type": "harness",
        "candidate_harness": {
            key: value
            for key, value in candidate_harness.items()
            if key != "candidate_id"
        },
    }
    return proposal

def _candidate_harness_effective_config(
    *,
    base_effective_config: dict[str, Any],
    candidate_harness: dict[str, Any],
) -> dict[str, Any]:
    effective_config = dict(base_effective_config)
    config_patch = candidate_harness.get("config_patch")
    if isinstance(config_patch, dict):
        effective_config = merge_dicts(effective_config, config_patch)

    runtime = candidate_harness.get("runtime")
    if isinstance(runtime, dict):
        effective_config = merge_dicts(effective_config, {"runtime": runtime})

    inline_effective_config = candidate_harness.get("effective_config")
    if isinstance(inline_effective_config, dict):
        effective_config = merge_dicts(effective_config, inline_effective_config)

    return effective_config

def _candidate_harness_result_payload(
    *,
    candidate_id: str,
    candidate_harness: dict[str, Any],
) -> dict[str, Any]:
    result = dict(candidate_harness)
    result.setdefault("candidate_harness_id", result.get("candidate_id") or candidate_id)
    result["candidate_id"] = candidate_id
    return result
