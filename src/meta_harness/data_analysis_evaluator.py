from __future__ import annotations

from pathlib import Path
from typing import Any

from meta_harness.evaluator_runtime import (
    average_numeric,
    flatten_signal_payload,
    iter_task_dirs,
    load_benchmark_probe,
    load_step_events,
    load_task_result,
    read_json_if_exists,
    read_text_if_exists,
    task_total_latency_ms,
)
from meta_harness.signal_validation import validate_expected_signals


def _round(value: float) -> float:
    return round(float(value), 4)


def _normalize_text(text: str) -> str:
    return " ".join(str(text).casefold().split())


def _flatten_scalar_fields(payload: Any, prefix: str = "") -> dict[str, str]:
    flattened: dict[str, str] = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            dotted = f"{prefix}.{key}" if prefix else str(key)
            flattened.update(_flatten_scalar_fields(value, dotted))
        return flattened
    if isinstance(payload, list):
        for index, value in enumerate(payload):
            dotted = f"{prefix}[{index}]"
            flattened.update(_flatten_scalar_fields(value, dotted))
        return flattened
    if isinstance(payload, (str, int, float, bool)) and prefix:
        flattened[prefix] = str(payload)
    return flattened


def _lookup_field(payload: Any, dotted_path: str) -> Any:
    current = payload
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _required_fields(expectations: dict[str, Any], summary: Any) -> list[str]:
    configured = expectations.get("required_fields")
    if isinstance(configured, list):
        return [str(item) for item in configured if str(item)]
    if isinstance(summary, dict):
        return sorted(_flatten_scalar_fields(summary))
    return []


def _filled_required_field_rate(required_fields: list[str], summary: Any) -> float:
    if not required_fields:
        return 0.0
    filled = 0
    for field in required_fields:
        value = _lookup_field(summary, field)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        filled += 1
    return filled / len(required_fields)


def _grounded_field_rate(required_fields: list[str], summary: Any, report_text: str) -> float:
    if not report_text:
        return 0.0
    normalized_report = _normalize_text(report_text)
    present_values: list[str] = []
    for field in required_fields:
        value = _lookup_field(summary, field)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        present_values.append(str(value))
    if not present_values:
        return 0.0
    grounded = 0
    for value in present_values:
        normalized_value = _normalize_text(value)
        if normalized_value and normalized_value in normalized_report:
            grounded += 1
    return grounded / len(present_values)


def _probe_value(payload: dict[str, Any], key: str) -> float | None:
    probes = payload.get("probes")
    if not isinstance(probes, dict):
        return None
    flattened = flatten_signal_payload(probes)
    value = flattened.get(key)
    if not isinstance(value, (int, float)):
        return None
    return float(value)


def _merge_signal_values(values: list[Any]) -> Any:
    if not values:
        return None
    if all(isinstance(value, (int, float)) for value in values):
        return average_numeric([float(value) for value in values])
    first = values[0]
    if all(value == first for value in values):
        return first
    unique: list[Any] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique


def evaluate_data_analysis_run(run_dir: Path) -> dict[str, Any]:
    relevant_tasks: list[dict[str, Any]] = []
    for task_dir in iter_task_dirs(run_dir):
        task_result = load_task_result(task_dir)
        expectations = task_result.get("expectations")
        expectations = expectations if isinstance(expectations, dict) else {}
        primitive_id = expectations.get("primitive_id") or task_result.get("scenario")
        if primitive_id != "data_analysis":
            continue
        relevant_tasks.append(
            {
                "task_dir": task_dir,
                "task_result": task_result,
                "expectations": expectations,
            }
        )

    if not relevant_tasks:
        return {
            "correctness": {},
            "cost": {},
            "capability_scores": {},
            "workflow_scores": {},
            "probes": {},
            "composite_adjustment": 0.0,
        }

    success_flags: list[float] = []
    grounded_success_flags: list[float] = []
    summary_valid_rates: list[float] = []
    completeness_rates: list[float] = []
    grounded_rates: list[float] = []
    latency_values: list[float] = []
    retry_values: list[float] = []
    plan_step_values: list[float] = []
    hot_path_successes: list[float] = []
    fallback_invocations = 0
    latency_budgets: list[float] = []
    fingerprint_values: dict[str, list[Any]] = {}
    expected_signals: dict[str, Any] = {}
    binding_payload_rates: list[float] = []
    assistant_reply_rates: list[float] = []
    artifact_coverage_rates: list[float] = []
    binding_execution_rates: list[float] = []
    method_trace_coverage_rates: list[float] = []
    binding_token_totals: list[float] = []
    has_transfer_tasks = False

    for item in relevant_tasks:
        task_dir = item["task_dir"]
        task_result = item["task_result"]
        expectations = item["expectations"]
        role = str(expectations.get("role", "hot_path"))
        success = bool(task_result.get("success", False))
        success_flags.append(1.0 if success else 0.0)
        if role == "hot_path":
            hot_path_successes.append(1.0 if success else 0.0)
        if role == "fallback_path":
            fallback_invocations += 1

        summary = read_json_if_exists(task_dir / "analysis_summary.json")
        report_text = read_text_if_exists(task_dir / "analysis_report.md")
        summary_valid = isinstance(summary, dict) and bool(summary)
        summary_valid_rates.append(1.0 if summary_valid else 0.0)

        required_fields = _required_fields(expectations, summary)
        completeness = (
            _filled_required_field_rate(required_fields, summary) if summary_valid else 0.0
        )
        grounded = (
            _grounded_field_rate(required_fields, summary, report_text) if summary_valid else 0.0
        )
        completeness_rates.append(completeness)
        grounded_rates.append(grounded)

        thresholds = expectations.get("quality_thresholds")
        thresholds = thresholds if isinstance(thresholds, dict) else {}
        completeness_threshold = float(thresholds.get("field_completeness", 0.8))
        grounded_threshold = float(thresholds.get("grounded_field_rate", 0.75))
        grounded_success = (
            success
            and summary_valid
            and completeness >= completeness_threshold
            and grounded >= grounded_threshold
        )
        grounded_success_flags.append(1.0 if grounded_success else 0.0)

        latency_values.append(task_total_latency_ms(task_dir))
        latency_budget = expectations.get("latency_budget_ms", 8000)
        latency_budgets.append(float(latency_budget))

        probe_payload = load_benchmark_probe(task_dir)
        fingerprint_payload = probe_payload.get("fingerprints")
        if isinstance(fingerprint_payload, dict):
            for key, value in flatten_signal_payload(fingerprint_payload).items():
                fingerprint_values.setdefault(key, []).append(value)
        plan_step_value = _probe_value(probe_payload, "analysis.plan_step_count")
        retry_value = _probe_value(probe_payload, "analysis.retry_count")
        if plan_step_value is not None:
            plan_step_values.append(plan_step_value)
        if retry_value is not None:
            retry_values.append(retry_value)

        task_expected_signals = expectations.get("expected_signals")
        if isinstance(task_expected_signals, dict):
            for section in ("fingerprints", "probes"):
                section_payload = task_expected_signals.get(section)
                if not isinstance(section_payload, dict):
                    continue
                target = expected_signals.setdefault(section, {})
                if isinstance(target, dict):
                    target.update(section_payload)

        transfer_task = any(
            task_result.get(key)
            for key in ("method_id", "binding_id", "binding_payload", "binding_artifacts")
        )
        if transfer_task:
            has_transfer_tasks = True
            binding_payload = task_result.get("binding_payload")
            binding_payload_present = (
                1.0 if isinstance(binding_payload, dict) and binding_payload else 0.0
            )
            binding_payload_rates.append(binding_payload_present)

            binding_artifacts = task_result.get("binding_artifacts")
            binding_artifacts = (
                [str(item) for item in binding_artifacts if str(item)]
                if isinstance(binding_artifacts, list)
                else []
            )
            if binding_artifacts:
                existing_artifacts = sum(
                    1 for artifact in binding_artifacts if (task_dir / artifact).exists()
                )
                artifact_coverage_rates.append(existing_artifacts / len(binding_artifacts))
            else:
                artifact_coverage_rates.append(0.0)

            step_events = load_step_events(task_dir)
            assistant_reply_present = any(
                str(event.get("phase")) == "assistant_reply"
                and str(event.get("status")) == "completed"
                for event in step_events
            )
            assistant_reply_rates.append(1.0 if assistant_reply_present else 0.0)
            binding_execution_rates.append(
                1.0 if binding_payload_present or assistant_reply_present else 0.0
            )
            method_trace_coverage_rates.append(
                1.0 if assistant_reply_present and (artifact_coverage_rates[-1] > 0.0) else 0.0
            )
            event_token_totals = [
                float((event.get("token_usage") or {}).get("total"))
                for event in step_events
                if isinstance(event.get("token_usage"), dict)
                and isinstance((event.get("token_usage") or {}).get("total"), (int, float))
            ]
            if event_token_totals:
                binding_token_totals.append(max(event_token_totals))
            elif isinstance(binding_payload, dict):
                usage = binding_payload.get("usage")
                if isinstance(usage, dict) and isinstance(usage.get("totalTokens"), (int, float)):
                    binding_token_totals.append(float(usage["totalTokens"]))

    task_success_rate = average_numeric(success_flags)
    task_grounded_success_rate = average_numeric(grounded_success_flags)
    summary_valid_rate = average_numeric(summary_valid_rates)
    field_completeness = average_numeric(completeness_rates)
    grounded_field_rate = average_numeric(grounded_rates)
    latency_ms = average_numeric(latency_values)
    retry_count = average_numeric(retry_values)
    plan_step_count = average_numeric(plan_step_values)
    hot_path_success_rate = average_numeric(hot_path_successes) if hot_path_successes else 0.0
    fallback_rate = _round(fallback_invocations / len(relevant_tasks))
    observed_fingerprints = {
        key: _merge_signal_values(values)
        for key, values in sorted(fingerprint_values.items())
    }
    observed_probes: dict[str, Any] = {}
    if plan_step_values:
        observed_probes["analysis.plan_step_count"] = plan_step_count
    if retry_values:
        observed_probes["analysis.retry_count"] = retry_count
    mechanism: dict[str, Any] = {}
    if observed_fingerprints:
        mechanism["fingerprints"] = observed_fingerprints
    if observed_probes:
        mechanism["probes"] = observed_probes
    signal_validation = validate_expected_signals(expected_signals or None, mechanism)

    average_latency_budget = average_numeric(latency_budgets) or 8000.0
    latency_ratio = latency_ms / average_latency_budget if average_latency_budget > 0 else 1.0
    latency_score = 1.0 if latency_ratio <= 1.0 else max(0.0, 1.0 - (latency_ratio - 1.0))
    retry_score = 1.0 / (1.0 + retry_count) if retry_values else 1.0
    quality_score = (
        task_success_rate * 0.35
        + task_grounded_success_rate * 0.25
        + summary_valid_rate * 0.15
        + field_completeness * 0.15
        + grounded_field_rate * 0.1
    )
    efficiency_score = latency_score * 0.7 + retry_score * 0.3
    composite_adjustment = _round((quality_score * 0.7) + (efficiency_score * 0.3) - 0.35)

    result = {
        "correctness": {
            "task_success_rate": task_success_rate,
            "task_grounded_success_rate": task_grounded_success_rate,
        },
        "cost": {
            "data_analysis_latency_ms": latency_ms,
        },
        "architecture": {},
        "capability_scores": {
            "data_analysis": {
                "success_rate": task_success_rate,
                "latency_ms": latency_ms,
                "summary_valid_rate": summary_valid_rate,
                "field_completeness": field_completeness,
                "grounded_field_rate": grounded_field_rate,
            }
        },
        "workflow_scores": {
            "hot_path_success_rate": hot_path_success_rate,
            "fallback_rate": fallback_rate,
        },
        "probes": {
            **observed_fingerprints,
            **observed_probes,
        },
        "composite_adjustment": composite_adjustment,
    }
    if expected_signals:
        result["architecture"]["expected_signal_validation"] = signal_validation
    if has_transfer_tasks:
        binding_payload_rate = average_numeric(binding_payload_rates)
        assistant_reply_rate = average_numeric(assistant_reply_rates)
        artifact_coverage_rate = average_numeric(artifact_coverage_rates)
        binding_execution_rate = average_numeric(binding_execution_rates)
        method_trace_coverage_rate = average_numeric(method_trace_coverage_rates)
        binding_token_total = average_numeric(binding_token_totals)
        result["capability_scores"]["data_analysis"].update(
            {
                "binding_payload_rate": binding_payload_rate,
                "assistant_reply_rate": assistant_reply_rate,
                "artifact_coverage_rate": artifact_coverage_rate,
                "binding_token_total": binding_token_total,
            }
        )
        result["workflow_scores"].update(
            {
                "binding_execution_rate": binding_execution_rate,
                "method_trace_coverage_rate": method_trace_coverage_rate,
            }
        )
        result["probes"].update(
            {
                "data_analysis.binding_payload_present_rate": binding_payload_rate,
                "data_analysis.assistant_reply_rate": assistant_reply_rate,
                "data_analysis.artifact_coverage_rate": artifact_coverage_rate,
                "data_analysis.binding_token_total": binding_token_total,
            }
        )
    return result
