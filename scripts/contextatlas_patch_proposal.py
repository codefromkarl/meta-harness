from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import Any


OMC_IMPORT_PATCH = """--- a/src/memory/MemoryStore.ts
+++ b/src/memory/MemoryStore.ts
@@ -9,6 +9,7 @@
 import { generateProjectId } from '../db/index.js';
 import { logger } from '../utils/logger.js';
 import { importLegacyProjectMemoryIfNeeded } from './LegacyMemoryImporter.js';
+import { importOmcProjectProfileIfNeeded } from './OmcProjectMemoryImporter.js';
 import { type FeatureMemoryRow, MemoryHubDatabase } from './MemoryHubDatabase.js';
 import { MemoryRouter } from './MemoryRouter.js';
 import type {
@@ -107,6 +108,12 @@
       catalogMetaKey: CATALOG_META_KEY,
       globalMetaPrefix: GLOBAL_META_PREFIX,
     });
+
+    await importOmcProjectProfileIfNeeded({
+      projectRoot: this.projectRoot,
+      projectId: this.projectId,
+      hub: this.hub,
+    });
 
     this.writeInitialized = true;
     logger.info({ projectId: this.projectId }, 'Project Memory SQLite 存储初始化完成');
"""

DEFAULT_HEADROOM_DEFAULTS = {
    "indexing": {
        "retrieval": {
            "chunk_size": 1200,
            "chunk_overlap": 160,
        },
        "signals": [
            "snapshot_ready",
            "vector_index_ready",
            "db_integrity_ok",
        ],
        "checks": [
            "snapshot_health",
            "vector_index_health",
            "db_integrity",
        ],
    },
    "memory": {
        "budget": {
            "max_turns": 14,
            "max_retries": 2,
        },
        "signals": [
            "memory_completeness",
            "memory_freshness",
            "memory_stale_ratio",
        ],
        "checks": [
            "profile_import",
            "memory_consistency",
            "catalog_freshness",
        ],
    },
    "retrieval": {
        "retrieval": {
            "top_k": 12,
            "rerank_k": 24,
        },
        "signals": [
            "retrieval_hit_rate",
            "retrieval_mrr",
            "grounded_answer_rate",
        ],
        "checks": [
            "topk_sweep",
            "rerank_eval",
            "query_quality_eval",
        ],
    },
}

METRIC_THRESHOLDS = {
    "indexing": {
        "vector_coverage_ratio": 0.9,
        "index_freshness_ratio": 0.85,
    },
    "memory": {
        "memory_completeness": 0.8,
        "memory_freshness": 0.85,
        "memory_stale_ratio": 0.1,
    },
    "retrieval": {
        "retrieval_hit_rate": 0.7,
        "retrieval_mrr": 0.5,
        "grounded_answer_rate": 0.8,
    },
}


def _empty_quality_gaps() -> dict[str, bool]:
    return {
        "profile_gap": False,
        "memory_gap": False,
        "snapshot_gap": False,
        "vector_gap": False,
        "db_gap": False,
    }


def _parse_created_at(raw: Any) -> datetime:
    if not raw:
        return datetime.min.replace(tzinfo=UTC)
    text = str(raw).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _headroom_defaults(effective_config: dict[str, Any]) -> dict[str, Any]:
    config_defaults = (effective_config.get("optimization") or {}).get("headroom_defaults") or {}
    return _deep_merge(DEFAULT_HEADROOM_DEFAULTS, config_defaults)


def _metric_thresholds(effective_config: dict[str, Any]) -> dict[str, Any]:
    config_thresholds = (effective_config.get("optimization") or {}).get("headroom_thresholds") or {}
    return _deep_merge(METRIC_THRESHOLDS, config_thresholds)


def _run_contextatlas(run: dict[str, Any] | None) -> dict[str, Any]:
    if not run:
        return {}
    return (run.get("run_context") or {}).get("contextatlas") or {}


def _run_composite(run: dict[str, Any] | None) -> float:
    if not run:
        return 0.0
    return float((run.get("score") or {}).get("composite", 0.0))


def _run_is_healthy(run: dict[str, Any] | None) -> bool:
    return not any(summarize_run_quality(run).values())


def _score_section(run: dict[str, Any] | None, section: str) -> dict[str, Any]:
    if not run:
        return {}
    return (run.get("score") or {}).get(section) or {}


def _metric_gap_values(
    run: dict[str, Any] | None,
    *,
    section: str,
    thresholds: dict[str, float],
    reverse_lower_is_better: set[str] | None = None,
) -> tuple[list[str], dict[str, float]]:
    values = _score_section(run, section)
    gap_names: list[str] = []
    gap_values: dict[str, float] = {}
    reverse_lower_is_better = reverse_lower_is_better or set()

    for metric, threshold in thresholds.items():
        raw_value = values.get(metric)
        if not isinstance(raw_value, (int, float)):
            continue
        value = float(raw_value)
        is_gap = value > threshold if metric in reverse_lower_is_better else value < threshold
        if is_gap:
            gap_names.append(metric)
            gap_values[metric] = value
    return gap_names, gap_values


def _healthy_streak_runs(matching_runs: list[dict[str, Any]]) -> int:
    streak = 0
    for run in sorted(
        matching_runs,
        key=lambda item: (_parse_created_at(item.get("created_at")), item.get("run_id", "")),
        reverse=True,
    ):
        if not _run_is_healthy(run):
            break
        streak += 1
    return streak


def _count_runs_with_false_signal(
    matching_runs: list[dict[str, Any]],
    section: str,
    signal: str,
) -> int:
    count = 0
    for run in matching_runs:
        score = run.get("score") or {}
        values = score.get(section) or {}
        if values.get(signal) is False:
            count += 1
    return count


def _merge_numeric_floor(base_config: dict[str, Any], patch_defaults: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key, value in patch_defaults.items():
        current = base_config.get(key)
        if isinstance(value, (int, float)):
            if isinstance(current, (int, float)):
                merged[key] = max(current, value)
            else:
                merged[key] = value
        else:
            merged[key] = value
    return merged


def _indexing_headroom_metadata(
    effective_config: dict[str, Any],
    matching_runs: list[dict[str, Any]],
    latest_run: dict[str, Any] | None,
    best_run: dict[str, Any] | None,
) -> dict[str, Any]:
    thresholds = _metric_thresholds(effective_config)["indexing"]
    latest_quality_gaps = summarize_run_quality(latest_run)
    latest_gap_reasons: list[str] = []
    if latest_quality_gaps["snapshot_gap"]:
        latest_gap_reasons.append("snapshot_ready")
    if latest_quality_gaps["vector_gap"]:
        latest_gap_reasons.append("vector_index_ready")
    if latest_quality_gaps["db_gap"]:
        latest_gap_reasons.append("db_integrity_ok")
    metric_gap_reasons, metric_gap_values = _metric_gap_values(
        latest_run,
        section="architecture",
        thresholds=thresholds,
    )
    latest_gap_reasons.extend(
        reason for reason in metric_gap_reasons if reason not in latest_gap_reasons
    )

    metadata = {
        "category": "indexing",
        "latest_run_id": latest_run.get("run_id") if latest_run else None,
        "best_run_id": best_run.get("run_id") if best_run else None,
        "healthy_streak_runs": _healthy_streak_runs(matching_runs),
        "latest_gap_reasons": latest_gap_reasons,
        "historical_gap_counts": {
            "snapshot_ready": _count_runs_with_false_signal(
                matching_runs,
                "architecture",
                "snapshot_ready",
            ),
            "vector_index_ready": _count_runs_with_false_signal(
                matching_runs,
                "architecture",
                "vector_index_ready",
            ),
            "db_integrity_ok": _count_runs_with_false_signal(
                matching_runs,
                "architecture",
                "db_integrity_ok",
            ),
        },
        "metric_thresholds": thresholds,
    }
    if metric_gap_values:
        metadata["latest_metric_values"] = metric_gap_values
    return metadata


def _memory_headroom_metadata(
    effective_config: dict[str, Any],
    matching_runs: list[dict[str, Any]],
    latest_run: dict[str, Any] | None,
    best_run: dict[str, Any] | None,
) -> dict[str, Any]:
    latest_context = _run_contextatlas(latest_run)
    thresholds = _metric_thresholds(effective_config)["memory"]
    metric_gap_names, metric_gap_values = _metric_gap_values(
        latest_run,
        section="maintainability",
        thresholds=thresholds,
        reverse_lower_is_better={"memory_stale_ratio"},
    )
    metadata = {
        "category": "memory",
        "latest_run_id": latest_run.get("run_id") if latest_run else None,
        "best_run_id": best_run.get("run_id") if best_run else None,
        "healthy_streak_runs": _healthy_streak_runs(matching_runs),
        "historical_gap_counts": {
            "profile_present": _count_runs_with_false_signal(
                matching_runs,
                "maintainability",
                "profile_present",
            ),
            "memory_consistency_ok": _count_runs_with_false_signal(
                matching_runs,
                "maintainability",
                "memory_consistency_ok",
            ),
        },
        "metric_thresholds": thresholds,
    }
    if metric_gap_names:
        metadata["latest_metric_gaps"] = metric_gap_names
    if metric_gap_values:
        metadata["latest_metric_values"] = metric_gap_values
    if latest_context.get("latest_profile_source"):
        metadata["latest_profile_source"] = latest_context["latest_profile_source"]
    if latest_context.get("latest_profile_updated_at"):
        metadata["latest_profile_updated_at"] = latest_context["latest_profile_updated_at"]
    if latest_context.get("catalog_stats"):
        metadata["latest_catalog_stats"] = latest_context["catalog_stats"]
    return metadata


def _retrieval_headroom_metadata(
    effective_config: dict[str, Any],
    matching_runs: list[dict[str, Any]],
    latest_run: dict[str, Any] | None,
    best_run: dict[str, Any] | None,
) -> dict[str, Any]:
    thresholds = _metric_thresholds(effective_config)["retrieval"]
    metric_gap_names, metric_gap_values = _metric_gap_values(
        latest_run,
        section="retrieval",
        thresholds=thresholds,
    )
    metadata = {
        "category": "retrieval",
        "latest_run_id": latest_run.get("run_id") if latest_run else None,
        "best_run_id": best_run.get("run_id") if best_run else None,
        "healthy_streak_runs": _healthy_streak_runs(matching_runs),
        "composite_gap_to_best": max(0.0, _run_composite(best_run) - _run_composite(latest_run)),
        "metric_thresholds": thresholds,
    }
    if metric_gap_names:
        metadata["latest_metric_gaps"] = metric_gap_names
    if metric_gap_values:
        metadata["latest_metric_values"] = metric_gap_values
    return metadata


def summarize_quality_gaps(matching_runs: list[dict[str, Any]]) -> dict[str, bool]:
    profile_gap = False
    memory_gap = False
    snapshot_gap = False
    vector_gap = False
    db_gap = False

    for run in matching_runs:
        score = run.get("score") or {}
        maintainability = score.get("maintainability") or {}
        architecture = score.get("architecture") or {}

        if maintainability.get("profile_present") is False:
            profile_gap = True
        if maintainability.get("memory_consistency_ok") is False:
            memory_gap = True
        if architecture.get("snapshot_ready") is False:
            snapshot_gap = True
        if architecture.get("vector_index_ready") is False:
            vector_gap = True
        if architecture.get("db_integrity_ok") is False:
            db_gap = True

    return {
        "profile_gap": profile_gap,
        "memory_gap": memory_gap,
        "snapshot_gap": snapshot_gap,
        "vector_gap": vector_gap,
        "db_gap": db_gap,
    }


def summarize_run_quality(run: dict[str, Any] | None) -> dict[str, bool]:
    if not run:
        return _empty_quality_gaps()
    return summarize_quality_gaps([run])


def select_reference_runs(matching_runs: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not matching_runs:
        return None, None

    latest_run = max(matching_runs, key=lambda run: (_parse_created_at(run.get("created_at")), run.get("run_id", "")))
    best_run = max(matching_runs, key=lambda run: (float((run.get("score") or {}).get("composite", 0.0)), _parse_created_at(run.get("created_at"))))
    return latest_run, best_run


def select_relevant_failures(
    failure_records: list[dict[str, Any]],
    latest_run: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not latest_run:
        return failure_records

    latest_run_id = latest_run.get("run_id")
    latest_failures = [
        record for record in failure_records if record.get("run_id") == latest_run_id
    ]
    if latest_failures:
        return latest_failures
    return []


def build_headroom_config_patch(
    effective_config: dict[str, Any],
    *,
    focus: str,
    matching_runs: list[dict[str, Any]],
    latest_run: dict[str, Any] | None,
    best_run: dict[str, Any] | None,
) -> dict[str, Any]:
    defaults = _headroom_defaults(effective_config).get(focus, {})
    retrieval_config = effective_config.get("retrieval") or {}
    budget_config = effective_config.get("budget") or {}

    if focus == "indexing":
        retrieval_patch = _merge_numeric_floor(
            retrieval_config,
            defaults.get("retrieval") or DEFAULT_HEADROOM_DEFAULTS["indexing"]["retrieval"],
        )
        return {
            "retrieval": retrieval_patch,
            "optimization": {
                "focus": "indexing",
                "headroom": _indexing_headroom_metadata(
                    effective_config,
                    matching_runs,
                    latest_run,
                    best_run,
                ),
            },
            "contextatlas": {
                "headroom": {
                    "indexing": {
                        "signals": defaults.get("signals")
                        or DEFAULT_HEADROOM_DEFAULTS["indexing"]["signals"],
                        "checks": defaults.get("checks")
                        or DEFAULT_HEADROOM_DEFAULTS["indexing"]["checks"],
                    }
                }
            },
        }

    if focus == "memory":
        budget_patch = _merge_numeric_floor(
            budget_config,
            defaults.get("budget") or DEFAULT_HEADROOM_DEFAULTS["memory"]["budget"],
        )
        return {
            "budget": budget_patch,
            "optimization": {
                "focus": "memory",
                "headroom": _memory_headroom_metadata(
                    effective_config,
                    matching_runs,
                    latest_run,
                    best_run,
                ),
            },
            "contextatlas": {
                "headroom": {
                    "memory": {
                        "signals": defaults.get("signals")
                        or DEFAULT_HEADROOM_DEFAULTS["memory"]["signals"],
                        "checks": defaults.get("checks")
                        or DEFAULT_HEADROOM_DEFAULTS["memory"]["checks"],
                    }
                }
            },
        }

    retrieval_patch = _merge_numeric_floor(
        retrieval_config,
        defaults.get("retrieval") or DEFAULT_HEADROOM_DEFAULTS["retrieval"]["retrieval"],
    )
    return {
        "retrieval": retrieval_patch,
        "optimization": {
            "focus": "retrieval",
            "headroom": _retrieval_headroom_metadata(
                effective_config,
                matching_runs,
                latest_run,
                best_run,
            ),
        },
        "contextatlas": {
            "headroom": {
                "retrieval": {
                    "signals": defaults.get("signals")
                    or DEFAULT_HEADROOM_DEFAULTS["retrieval"]["signals"],
                    "checks": defaults.get("checks")
                    or DEFAULT_HEADROOM_DEFAULTS["retrieval"]["checks"],
                }
            }
        },
    }


def select_strategy(
    effective_config: dict[str, Any],
    matching_runs: list[dict[str, Any]],
    failure_records: list[dict[str, Any]],
) -> tuple[str, str | None, dict[str, Any] | None]:
    latest_run, best_run = select_reference_runs(matching_runs)
    relevant_failures = select_relevant_failures(failure_records, latest_run)

    combined = " ".join(
        " ".join(
            [
                str(record.get("family", "")),
                str(record.get("signature", "")),
                str(record.get("raw_error", "")),
            ]
        ).lower()
        for record in relevant_failures
    )

    omc_terms = [".omc", "project memory", "profile show", "import omc", "memory consistency"]
    if any(term in combined for term in omc_terms):
        return "restore_omc_profile_import_path", OMC_IMPORT_PATCH, None

    latest_quality_gaps = summarize_run_quality(latest_run)
    best_quality_gaps = summarize_run_quality(best_run)
    historical_quality_gaps = summarize_quality_gaps(matching_runs)
    thresholds = _metric_thresholds(effective_config)
    latest_indexing_metric_gaps, _ = _metric_gap_values(
        latest_run,
        section="architecture",
        thresholds=thresholds["indexing"],
    )
    latest_memory_metric_gaps, _ = _metric_gap_values(
        latest_run,
        section="maintainability",
        thresholds=thresholds["memory"],
        reverse_lower_is_better={"memory_stale_ratio"},
    )
    latest_retrieval_metric_gaps, _ = _metric_gap_values(
        latest_run,
        section="retrieval",
        thresholds=thresholds["retrieval"],
    )

    if latest_quality_gaps["profile_gap"] or latest_quality_gaps["memory_gap"]:
        return "close_profile_memory_quality_gap", OMC_IMPORT_PATCH, None

    if latest_quality_gaps["snapshot_gap"] or latest_quality_gaps["vector_gap"] or latest_quality_gaps["db_gap"]:
        return (
            "explore_indexing_headroom",
            None,
            build_headroom_config_patch(
                effective_config,
                focus="indexing",
                matching_runs=matching_runs,
                latest_run=latest_run,
                best_run=best_run,
            ),
        )

    if latest_indexing_metric_gaps:
        return (
            "explore_indexing_headroom",
            None,
            build_headroom_config_patch(
                effective_config,
                focus="indexing",
                matching_runs=matching_runs,
                latest_run=latest_run,
                best_run=best_run,
            ),
        )

    if latest_memory_metric_gaps:
        return (
            "explore_memory_headroom",
            None,
            build_headroom_config_patch(
                effective_config,
                focus="memory",
                matching_runs=matching_runs,
                latest_run=latest_run,
                best_run=best_run,
            ),
        )

    if best_quality_gaps["profile_gap"] or best_quality_gaps["memory_gap"]:
        return (
            "revalidate_profile_memory_fix",
            None,
            build_headroom_config_patch(
                effective_config,
                focus="memory",
                matching_runs=matching_runs,
                latest_run=latest_run,
                best_run=best_run,
            ),
        )

    if relevant_failures:
        return (
            "increase_budget_on_repeated_failures",
            None,
            build_headroom_config_patch(
                effective_config,
                focus="memory",
                matching_runs=matching_runs,
                latest_run=latest_run,
                best_run=best_run,
            ),
        )

    if latest_retrieval_metric_gaps:
        return (
            "explore_retrieval_headroom",
            None,
            build_headroom_config_patch(
                effective_config,
                focus="retrieval",
                matching_runs=matching_runs,
                latest_run=latest_run,
                best_run=best_run,
            ),
        )

    if historical_quality_gaps["profile_gap"] or historical_quality_gaps["memory_gap"]:
        return (
            "explore_memory_headroom",
            None,
            build_headroom_config_patch(
                effective_config,
                focus="memory",
                matching_runs=matching_runs,
                latest_run=latest_run,
                best_run=best_run,
            ),
        )

    return (
        "explore_retrieval_headroom",
        None,
        build_headroom_config_patch(
            effective_config,
            focus="retrieval",
            matching_runs=matching_runs,
            latest_run=latest_run,
            best_run=best_run,
        ),
    )


def main() -> None:
    payload = json.load(sys.stdin)
    effective_config = payload.get("effective_config") or {}
    failure_records = payload.get("failure_records", [])
    matching_runs = payload.get("matching_runs", [])
    strategy, code_patch, config_patch = select_strategy(
        effective_config,
        matching_runs,
        failure_records,
    )
    latest_run, best_run = select_reference_runs(matching_runs)
    source_runs = sorted({record["run_id"] for record in matching_runs})

    proposal: dict[str, Any] = {
        "strategy": strategy,
        "source_runs": source_runs,
        "failure_count": len(failure_records),
        "quality_gaps": {
            "historical": summarize_quality_gaps(matching_runs),
            "latest": summarize_run_quality(latest_run),
            "best": summarize_run_quality(best_run),
        },
        "latest_run_id": latest_run.get("run_id") if latest_run else None,
        "best_run_id": best_run.get("run_id") if best_run else None,
    }
    result: dict[str, Any] = {
        "notes": f"contextatlas proposal: {strategy}",
        "proposal": proposal,
    }

    if code_patch is not None:
        result["code_patch"] = code_patch
    if config_patch is not None:
        result["config_patch"] = config_patch
        headroom = ((config_patch.get("optimization") or {}).get("headroom")) if isinstance(config_patch, dict) else None
        if headroom is not None:
            proposal["headroom"] = headroom

    print(json.dumps(result))


if __name__ == "__main__":
    main()
