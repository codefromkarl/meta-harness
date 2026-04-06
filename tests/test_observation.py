from __future__ import annotations

import json
from pathlib import Path

from meta_harness.observation import list_observation_runs, summarize_observation
from meta_harness.observation_strategies import resolve_observation_strategy


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_run(
    runs_root: Path,
    run_id: str,
    *,
    profile: str,
    project: str,
    created_at: str,
    score: dict,
) -> None:
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "tasks").mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    write_json(
        run_dir / "run_metadata.json",
        {
            "run_id": run_id,
            "profile": profile,
            "project": project,
            "created_at": created_at,
        },
    )
    write_json(
        run_dir / "effective_config.json",
        {"evaluation": {"evaluators": ["basic"]}},
    )
    write_json(run_dir / "score_report.json", score)


def write_project_config(
    config_root: Path,
    *,
    threshold_overrides: dict | None = None,
) -> None:
    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "contextatlas_patch_repair.json",
        {"description": "workflow", "defaults": {}},
    )
    project_payload = {
        "workflow": "contextatlas_patch_repair",
        "overrides": {},
    }
    if threshold_overrides is not None:
        project_payload["overrides"]["optimization"] = {
            "headroom_thresholds": threshold_overrides
        }
    write_json(config_root / "projects" / "contextatlas_patch.json", project_payload)


def test_summarize_observation_reports_healthy_run(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    write_project_config(config_root)
    write_run(
        runs_root,
        "run-healthy",
        profile="contextatlas_patch_repair",
        project="contextatlas_patch",
        created_at="2026-04-05T10:00:00Z",
        score={
            "maintainability": {
                "profile_present": True,
                "memory_consistency_ok": True,
            },
            "architecture": {
                "snapshot_ready": True,
                "vector_index_ready": True,
                "db_integrity_ok": True,
                "vector_coverage_ratio": 0.95,
                "index_freshness_ratio": 0.9,
            },
            "retrieval": {
                "retrieval_hit_rate": 0.88,
                "retrieval_mrr": 0.74,
                "grounded_answer_rate": 0.91,
            },
            "composite": 12.0,
        },
    )

    summary = summarize_observation(
        runs_root,
        "contextatlas_patch_repair",
        "contextatlas_patch",
        config_root=config_root,
    )

    assert summary["run_count"] == 1
    assert summary["latest_run_id"] == "run-healthy"
    assert summary["best_run_id"] == "run-healthy"
    assert summary["latest_score"]["maintainability"]["profile_present"] is True
    assert summary["latest_score"]["architecture"]["snapshot_ready"] is True
    assert summary["latest_score"]["retrieval"]["retrieval_hit_rate"] == 0.88
    assert summary["composite_delta_from_best"] == 0.0
    assert summary["needs_optimization"] is False
    assert summary["recommended_focus"] == "none"
    assert summary["architecture_recommendation"] is None


def test_resolve_observation_strategy_uses_contextatlas_workflow(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    write_project_config(config_root)

    strategy = resolve_observation_strategy(
        config_root,
        "contextatlas_patch_repair",
        "contextatlas_patch",
    )

    assert strategy.name == "contextatlas"


def test_summarize_observation_keeps_default_fallback_behavior_for_non_contextatlas_workflows(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )
    write_run(
        runs_root,
        "run-default-gap",
        profile="base",
        project="demo",
        created_at="2026-04-05T10:00:00Z",
        score={
            "maintainability": {
                "profile_present": True,
                "memory_consistency_ok": True,
                "memory_completeness": 0.91,
                "memory_freshness": 0.93,
                "memory_stale_ratio": 0.04,
            },
            "architecture": {
                "snapshot_ready": True,
                "vector_index_ready": True,
                "db_integrity_ok": True,
                "vector_coverage_ratio": 0.94,
                "index_freshness_ratio": 0.9,
            },
            "retrieval": {
                "retrieval_hit_rate": 0.44,
                "retrieval_mrr": 0.31,
                "grounded_answer_rate": 0.69,
            },
            "composite": 12.0,
        },
    )

    summary = summarize_observation(
        runs_root,
        "base",
        "demo",
        config_root=config_root,
    )

    assert summary["needs_optimization"] is True
    assert summary["recommended_focus"] == "retrieval"


def test_summarize_observation_reports_memory_metric_gap(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    write_project_config(config_root)
    write_run(
        runs_root,
        "run-memory-gap",
        profile="contextatlas_patch_repair",
        project="contextatlas_patch",
        created_at="2026-04-05T10:00:00Z",
        score={
            "maintainability": {
                "profile_present": True,
                "memory_consistency_ok": True,
                "memory_completeness": 0.62,
                "memory_freshness": 0.89,
                "memory_stale_ratio": 0.18,
            },
            "architecture": {
                "snapshot_ready": True,
                "vector_index_ready": True,
                "db_integrity_ok": True,
            },
            "retrieval": {
                "retrieval_hit_rate": 0.87,
                "retrieval_mrr": 0.72,
                "grounded_answer_rate": 0.9,
            },
            "composite": 12.0,
        },
    )

    summary = summarize_observation(
        runs_root,
        "contextatlas_patch_repair",
        "contextatlas_patch",
        config_root=config_root,
    )

    assert summary["needs_optimization"] is True
    assert summary["recommended_focus"] == "memory"
    assert summary["latest_score"]["maintainability"]["memory_completeness"] == 0.62
    assert summary["architecture_recommendation"] == {
        "focus": "memory",
        "variant_type": "method_family",
        "proposal_strategy": "explore_memory_method_family",
        "hypothesis": "improve memory completeness and freshness while reducing stale memory interference",
        "gap_signals": [
            "memory_completeness",
            "memory_stale_ratio",
        ],
        "metric_thresholds": {
            "memory_completeness": 0.8,
            "memory_freshness": 0.85,
            "memory_stale_ratio": 0.1,
        },
    }


def test_summarize_observation_reports_retrieval_metric_gap(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    write_project_config(config_root)
    write_run(
        runs_root,
        "run-retrieval-gap",
        profile="contextatlas_patch_repair",
        project="contextatlas_patch",
        created_at="2026-04-05T10:00:00Z",
        score={
            "maintainability": {
                "profile_present": True,
                "memory_consistency_ok": True,
                "memory_completeness": 0.91,
                "memory_freshness": 0.93,
                "memory_stale_ratio": 0.04,
            },
            "architecture": {
                "snapshot_ready": True,
                "vector_index_ready": True,
                "db_integrity_ok": True,
                "vector_coverage_ratio": 0.93,
                "index_freshness_ratio": 0.9,
            },
            "retrieval": {
                "retrieval_hit_rate": 0.44,
                "retrieval_mrr": 0.31,
                "grounded_answer_rate": 0.69,
            },
            "composite": 12.0,
        },
    )

    summary = summarize_observation(
        runs_root,
        "contextatlas_patch_repair",
        "contextatlas_patch",
        config_root=config_root,
    )

    assert summary["needs_optimization"] is True
    assert summary["recommended_focus"] == "retrieval"
    assert summary["latest_score"]["retrieval"]["retrieval_mrr"] == 0.31
    assert summary["architecture_recommendation"] == {
        "focus": "retrieval",
        "variant_type": "method_family",
        "proposal_strategy": "explore_retrieval_method_family",
        "hypothesis": "improve retrieval hit rate, ranking quality, and grounded answer generation",
        "gap_signals": [
            "retrieval_hit_rate",
            "retrieval_mrr",
            "grounded_answer_rate",
        ],
        "metric_thresholds": {
            "retrieval_hit_rate": 0.7,
            "retrieval_mrr": 0.5,
            "grounded_answer_rate": 0.8,
        },
    }


def test_summarize_observation_reports_boolean_health_gap(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    write_project_config(config_root)
    write_run(
        runs_root,
        "run-boolean-gap",
        profile="contextatlas_patch_repair",
        project="contextatlas_patch",
        created_at="2026-04-05T10:00:00Z",
        score={
            "maintainability": {
                "profile_present": False,
                "memory_consistency_ok": True,
            },
            "architecture": {
                "snapshot_ready": True,
                "vector_index_ready": True,
                "db_integrity_ok": True,
            },
            "retrieval": {
                "retrieval_hit_rate": 0.9,
                "retrieval_mrr": 0.8,
                "grounded_answer_rate": 0.92,
            },
            "composite": 11.0,
        },
    )

    summary = summarize_observation(
        runs_root,
        "contextatlas_patch_repair",
        "contextatlas_patch",
        config_root=config_root,
    )

    assert summary["needs_optimization"] is True
    assert summary["recommended_focus"] == "memory"
    assert summary["architecture_recommendation"] == {
        "focus": "memory",
        "variant_type": "method_family",
        "proposal_strategy": "explore_memory_method_family",
        "hypothesis": "restore profile import and memory consistency before further retrieval optimization",
        "gap_signals": [
            "profile_present",
        ],
        "metric_thresholds": {
            "memory_completeness": 0.8,
            "memory_freshness": 0.85,
            "memory_stale_ratio": 0.1,
        },
    }


def test_summarize_observation_respects_threshold_overrides(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    write_project_config(
        config_root,
        threshold_overrides={
            "retrieval": {
                "retrieval_hit_rate": 0.9,
                "retrieval_mrr": 0.75,
                "grounded_answer_rate": 0.92,
            }
        },
    )
    write_run(
        runs_root,
        "run-threshold-gap",
        profile="contextatlas_patch_repair",
        project="contextatlas_patch",
        created_at="2026-04-05T10:00:00Z",
        score={
            "maintainability": {
                "profile_present": True,
                "memory_consistency_ok": True,
                "memory_completeness": 0.91,
                "memory_freshness": 0.93,
                "memory_stale_ratio": 0.04,
            },
            "architecture": {
                "snapshot_ready": True,
                "vector_index_ready": True,
                "db_integrity_ok": True,
                "vector_coverage_ratio": 0.94,
                "index_freshness_ratio": 0.9,
            },
            "retrieval": {
                "retrieval_hit_rate": 0.82,
                "retrieval_mrr": 0.63,
                "grounded_answer_rate": 0.88,
            },
            "composite": 12.0,
        },
    )

    summary = summarize_observation(
        runs_root,
        "contextatlas_patch_repair",
        "contextatlas_patch",
        config_root=config_root,
    )

    assert summary["needs_optimization"] is True
    assert summary["recommended_focus"] == "retrieval"


def test_list_observation_runs_supports_limit_for_recent_history(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    write_project_config(config_root)
    write_run(
        runs_root,
        "run-old",
        profile="contextatlas_patch_repair",
        project="contextatlas_patch",
        created_at="2026-04-05T08:00:00Z",
        score={
            "maintainability": {"profile_present": True, "memory_consistency_ok": True},
            "architecture": {
                "snapshot_ready": True,
                "vector_index_ready": True,
                "db_integrity_ok": True,
            },
            "retrieval": {
                "retrieval_hit_rate": 0.9,
                "retrieval_mrr": 0.8,
                "grounded_answer_rate": 0.95,
            },
            "composite": 10.0,
        },
    )
    write_run(
        runs_root,
        "run-mid",
        profile="contextatlas_patch_repair",
        project="contextatlas_patch",
        created_at="2026-04-05T09:00:00Z",
        score={
            "maintainability": {"profile_present": True, "memory_consistency_ok": True},
            "architecture": {
                "snapshot_ready": True,
                "vector_index_ready": True,
                "db_integrity_ok": True,
            },
            "retrieval": {
                "retrieval_hit_rate": 0.9,
                "retrieval_mrr": 0.8,
                "grounded_answer_rate": 0.95,
            },
            "composite": 11.0,
        },
    )
    write_run(
        runs_root,
        "run-latest",
        profile="contextatlas_patch_repair",
        project="contextatlas_patch",
        created_at="2026-04-05T10:00:00Z",
        score={
            "maintainability": {"profile_present": True, "memory_consistency_ok": True},
            "architecture": {
                "snapshot_ready": True,
                "vector_index_ready": True,
                "db_integrity_ok": True,
            },
            "retrieval": {
                "retrieval_hit_rate": 0.9,
                "retrieval_mrr": 0.8,
                "grounded_answer_rate": 0.95,
            },
            "composite": 12.0,
        },
    )

    runs = list_observation_runs(
        runs_root,
        "contextatlas_patch_repair",
        "contextatlas_patch",
    )
    summary = summarize_observation(
        runs_root,
        "contextatlas_patch_repair",
        "contextatlas_patch",
        config_root=config_root,
        limit=2,
    )

    assert [record["run_id"] for record in runs] == ["run-latest", "run-mid", "run-old"]
    assert summary["history"] == [
        {
            "run_id": "run-latest",
            "created_at": "2026-04-05T10:00:00Z",
            "composite": 12.0,
            "needs_optimization": False,
            "recommended_focus": "none",
        },
        {
            "run_id": "run-mid",
            "created_at": "2026-04-05T09:00:00Z",
            "composite": 11.0,
            "needs_optimization": False,
            "recommended_focus": "none",
        },
    ]
