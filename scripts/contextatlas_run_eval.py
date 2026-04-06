from __future__ import annotations

import json
import re
from pathlib import Path


def read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def read_phase_output(task_dir: Path, phase: str) -> str:
    stdout = read_text_if_exists(task_dir / f"{phase}.stdout.txt")
    stderr = read_text_if_exists(task_dir / f"{phase}.stderr.txt")
    return "\n".join(part for part in [stdout, stderr] if part)


def parse_json_maybe(raw: str) -> dict:
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


def extract_catalog_stats(raw: str) -> dict[str, int]:
    module_match = re.search(r'"moduleCount"\s*:\s*(\d+)', raw)
    scope_match = re.search(r'"scopeCount"\s*:\s*(\d+)', raw)
    stats: dict[str, int] = {}
    if module_match:
        stats["memory_module_count"] = int(module_match.group(1))
    if scope_match:
        stats["memory_scope_count"] = int(scope_match.group(1))
    return stats


def _record_metric_sample(
    samples: dict[str, list[float]],
    key: str,
    value: int | float,
) -> None:
    samples.setdefault(key, []).append(float(value))


def _finalize_metric_samples(
    metrics: dict[str, float | int],
    samples: dict[str, list[float]],
) -> None:
    for key, values in samples.items():
        if not values:
            continue
        if key == "task_case_count":
            metrics[key] = int(sum(values))
            continue
        averaged = sum(values) / len(values)
        if all(float(value).is_integer() for value in values):
            metrics[key] = int(round(averaged))
        else:
            metrics[key] = round(averaged, 6)


def merge_structured_metrics(
    payload: dict,
    *,
    maintainability_metrics: dict[str, float | int],
    architecture_metrics: dict[str, float | int],
    retrieval_metrics: dict[str, float],
    correctness_metrics: dict[str, float | int],
    cost_metrics: dict[str, float | int],
    maintainability_samples: dict[str, list[float]],
    architecture_samples: dict[str, list[float]],
    retrieval_samples: dict[str, list[float]],
    correctness_samples: dict[str, list[float]],
    cost_samples: dict[str, list[float]],
) -> None:
    indexing = payload.get("indexing") or {}
    if "documentCount" in indexing:
        _record_metric_sample(
            architecture_samples, "index_document_count", int(indexing["documentCount"])
        )
    if "chunkCount" in indexing:
        _record_metric_sample(
            architecture_samples, "index_chunk_count", int(indexing["chunkCount"])
        )
    coverage_ratio = _normalize_ratio(indexing.get("coverageRatio"))
    if coverage_ratio is not None:
        _record_metric_sample(
            architecture_samples, "vector_coverage_ratio", coverage_ratio
        )
    freshness_ratio = _normalize_ratio(indexing.get("freshnessRatio"))
    if freshness_ratio is not None:
        _record_metric_sample(
            architecture_samples, "index_freshness_ratio", freshness_ratio
        )

    memory = payload.get("memory") or {}
    if "moduleCount" in memory:
        _record_metric_sample(
            maintainability_samples, "memory_module_count", int(memory["moduleCount"])
        )
    if "scopeCount" in memory:
        _record_metric_sample(
            maintainability_samples, "memory_scope_count", int(memory["scopeCount"])
        )
    completeness = _normalize_ratio(memory.get("completeness"))
    if completeness is not None:
        _record_metric_sample(
            maintainability_samples, "memory_completeness", completeness
        )
    freshness = _normalize_ratio(memory.get("freshness"))
    if freshness is not None:
        _record_metric_sample(maintainability_samples, "memory_freshness", freshness)
    stale_ratio = _normalize_ratio(memory.get("staleRatio"))
    if stale_ratio is not None:
        _record_metric_sample(
            maintainability_samples, "memory_stale_ratio", stale_ratio
        )

    retrieval = payload.get("retrieval") or {}
    hit_rate = _normalize_ratio(retrieval.get("hitRate"))
    if hit_rate is not None:
        _record_metric_sample(retrieval_samples, "retrieval_hit_rate", hit_rate)
    mrr = _normalize_ratio(retrieval.get("mrr"))
    if mrr is not None:
        _record_metric_sample(retrieval_samples, "retrieval_mrr", mrr)
    grounded_answer_rate = _normalize_ratio(retrieval.get("groundedAnswerRate"))
    if grounded_answer_rate is not None:
        _record_metric_sample(
            retrieval_samples, "grounded_answer_rate", grounded_answer_rate
        )

    task_quality = payload.get("taskQuality") or {}
    task_success_rate = _normalize_ratio(task_quality.get("taskSuccessRate"))
    if task_success_rate is not None:
        _record_metric_sample(
            correctness_samples, "task_success_rate", task_success_rate
        )
    task_grounded_success_rate = _normalize_ratio(
        task_quality.get("taskGroundedSuccessRate")
    )
    if task_grounded_success_rate is not None:
        _record_metric_sample(
            correctness_samples,
            "task_grounded_success_rate",
            task_grounded_success_rate,
        )
    if "taskCaseCount" in task_quality and isinstance(
        task_quality.get("taskCaseCount"), (int, float)
    ):
        _record_metric_sample(
            correctness_samples, "task_case_count", int(task_quality["taskCaseCount"])
        )

    cost = payload.get("cost") or {}
    if "indexBuildLatencyMs" in cost:
        _record_metric_sample(
            cost_samples, "index_build_latency_ms", float(cost["indexBuildLatencyMs"])
        )
    if "indexPeakMemoryMb" in cost:
        _record_metric_sample(
            cost_samples, "index_peak_memory_mb", float(cost["indexPeakMemoryMb"])
        )
    if "indexSizeBytes" in cost:
        _record_metric_sample(
            cost_samples, "index_size_bytes", int(cost["indexSizeBytes"])
        )
    if "indexEmbeddingCalls" in cost:
        _record_metric_sample(
            cost_samples, "index_embedding_calls", int(cost["indexEmbeddingCalls"])
        )
    if "indexFilesScannedCount" in cost:
        _record_metric_sample(
            cost_samples,
            "index_files_scanned_count",
            int(cost["indexFilesScannedCount"]),
        )
    if "indexFilesReindexedCount" in cost:
        _record_metric_sample(
            cost_samples,
            "index_files_reindexed_count",
            int(cost["indexFilesReindexedCount"]),
        )
    if "indexQueryP50Ms" in cost:
        _record_metric_sample(
            cost_samples, "index_query_p50_ms", float(cost["indexQueryP50Ms"])
        )
    if "indexQueryP95Ms" in cost:
        _record_metric_sample(
            cost_samples, "index_query_p95_ms", float(cost["indexQueryP95Ms"])
        )


def _normalize_ratio(raw: object) -> float | None:
    if isinstance(raw, (int, float)):
        return float(raw)
    return None


def _threshold_bonus(metrics: dict[str, float]) -> float:
    bonus = 0.0
    if metrics.get("memory_completeness", 0.0) >= 0.8:
        bonus += 0.25
    if metrics.get("memory_stale_ratio", 1.0) <= 0.1:
        bonus += 0.25
    if metrics.get("vector_coverage_ratio", 0.0) >= 0.9:
        bonus += 0.25
    if metrics.get("retrieval_hit_rate", 0.0) >= 0.7:
        bonus += 0.25
    if metrics.get("retrieval_mrr", 0.0) >= 0.5:
        bonus += 0.25
    if metrics.get("grounded_answer_rate", 0.0) >= 0.8:
        bonus += 0.25
    if metrics.get("task_success_rate", 0.0) >= 0.7:
        bonus += 0.25
    if metrics.get("task_grounded_success_rate", 0.0) >= 0.5:
        bonus += 0.25
    return bonus


def main() -> None:
    run_dir = Path.cwd()
    tasks_dir = run_dir / "tasks"
    task_dirs = (
        sorted(path for path in tasks_dir.iterdir() if path.is_dir())
        if tasks_dir.exists()
        else []
    )

    profile_present = False
    memory_consistency_ok = False
    snapshot_ready = False
    vector_index_ready = False
    db_integrity_ok = False
    maintainability_metrics: dict[str, float | int] = {}
    architecture_metrics: dict[str, float | int] = {}
    retrieval_metrics: dict[str, float] = {}
    correctness_metrics: dict[str, float | int] = {}
    cost_metrics: dict[str, float | int] = {}
    maintainability_samples: dict[str, list[float]] = {}
    architecture_samples: dict[str, list[float]] = {}
    retrieval_samples: dict[str, list[float]] = {}
    correctness_samples: dict[str, list[float]] = {}
    cost_samples: dict[str, list[float]] = {}

    for task_dir in task_dirs:
        show_profile = read_phase_output(task_dir, "show_profile")
        if "项目：" in show_profile:
            profile_present = True

        check_memory = read_phase_output(task_dir, "check_memory")
        if (
            "memory consistency check: OK" in check_memory
            or "status: ok" in check_memory.lower()
        ):
            memory_consistency_ok = True
        maintainability_metrics.update(extract_catalog_stats(check_memory))

        health_payload = parse_json_maybe(read_phase_output(task_dir, "health_check"))
        snapshots = health_payload.get("snapshots", [])
        if snapshots:
            snapshot = snapshots[0]
            snapshot_ready = bool(snapshot.get("hasCurrentSnapshot"))
            vector_index_ready = bool(snapshot.get("hasVectorIndex"))
            db_integrity_ok = snapshot.get("dbIntegrity") == "ok"

        merge_structured_metrics(
            health_payload,
            maintainability_metrics=maintainability_metrics,
            architecture_metrics=architecture_metrics,
            retrieval_metrics=retrieval_metrics,
            correctness_metrics=correctness_metrics,
            cost_metrics=cost_metrics,
            maintainability_samples=maintainability_samples,
            architecture_samples=architecture_samples,
            retrieval_samples=retrieval_samples,
            correctness_samples=correctness_samples,
            cost_samples=cost_samples,
        )

        benchmark_probe_payload = parse_json_maybe(
            read_phase_output(task_dir, "benchmark_probe")
        )
        merge_structured_metrics(
            benchmark_probe_payload,
            maintainability_metrics=maintainability_metrics,
            architecture_metrics=architecture_metrics,
            retrieval_metrics=retrieval_metrics,
            correctness_metrics=correctness_metrics,
            cost_metrics=cost_metrics,
            maintainability_samples=maintainability_samples,
            architecture_samples=architecture_samples,
            retrieval_samples=retrieval_samples,
            correctness_samples=correctness_samples,
            cost_samples=cost_samples,
        )

    _finalize_metric_samples(maintainability_metrics, maintainability_samples)
    _finalize_metric_samples(architecture_metrics, architecture_samples)
    _finalize_metric_samples(retrieval_metrics, retrieval_samples)
    _finalize_metric_samples(correctness_metrics, correctness_samples)
    _finalize_metric_samples(cost_metrics, cost_samples)

    system_ready = snapshot_ready and vector_index_ready and db_integrity_ok

    composite_adjustment = 0.0
    if profile_present:
        composite_adjustment += 1.0
    if memory_consistency_ok:
        composite_adjustment += 1.0
    if system_ready:
        composite_adjustment += 1.0
    composite_adjustment += _threshold_bonus(
        {
            **{
                key: float(value)
                for key, value in maintainability_metrics.items()
                if isinstance(value, (int, float))
            },
            **{
                key: float(value)
                for key, value in architecture_metrics.items()
                if isinstance(value, (int, float))
            },
            **retrieval_metrics,
        }
    )

    print(
        json.dumps(
            {
                "maintainability": {
                    "profile_present": profile_present,
                    "memory_consistency_ok": memory_consistency_ok,
                    **maintainability_metrics,
                },
                "architecture": {
                    "snapshot_ready": snapshot_ready,
                    "vector_index_ready": vector_index_ready,
                    "db_integrity_ok": db_integrity_ok,
                    **architecture_metrics,
                },
                "retrieval": retrieval_metrics,
                "correctness": correctness_metrics,
                "cost": cost_metrics,
                "composite_adjustment": composite_adjustment,
            }
        )
    )


if __name__ == "__main__":
    main()
