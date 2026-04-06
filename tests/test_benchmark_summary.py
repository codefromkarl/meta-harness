from __future__ import annotations

import json
from pathlib import Path
import subprocess


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_contextatlas_benchmark_summary_script_emits_cost_sensitive_findings(
    tmp_path: Path,
) -> None:
    payload_path = tmp_path / "external_strategy_suite.json"
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "contextatlas_benchmark_summary.py"
    )
    write_json(
        payload_path,
        {
            "suite": "contextatlas_external_strategy_first_pass",
            "best_by_experiment": {
                "contextatlas_indexing_architecture_v2": "chunk_dense_quality_bias",
                "contextatlas_external_indexing_strategies": "indexing_freshness-guard-external",
            },
            "best_by_quality_by_experiment": {
                "contextatlas_indexing_architecture_v2": "chunk_dense_quality_bias",
                "contextatlas_external_indexing_strategies": "indexing_incremental-refresh-patch",
            },
            "best_by_stability_by_experiment": {
                "contextatlas_indexing_architecture_v2": "chunk_compact_cost_bias",
                "contextatlas_external_indexing_strategies": "indexing_freshness-guard-external",
            },
            "benchmarks": [
                {
                    "experiment": "contextatlas_external_indexing_strategies",
                    "best_variant": "indexing_freshness-guard-external",
                    "best_by_quality": "indexing_incremental-refresh-patch",
                    "best_by_stability": "indexing_freshness-guard-external",
                    "report_summary": {
                        "top_variants_by_ranking_score": [
                            {
                                "name": "indexing_freshness-guard-external",
                                "ranking_score": 3.2,
                                "ranking_penalty": 0.3,
                                "stability_penalty": 0.0,
                                "cost_penalty": 0.3,
                                "composite": 3.5,
                            },
                            {
                                "name": "indexing_incremental-refresh-patch",
                                "ranking_score": 2.8,
                                "ranking_penalty": 1.0,
                                "stability_penalty": 0.2,
                                "cost_penalty": 0.8,
                                "composite": 3.8,
                            },
                        ]
                    },
                }
            ],
        },
    )

    completed = subprocess.run(
        ["python", str(script_path), str(payload_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    output = completed.stdout

    assert "Suite: contextatlas_external_strategy_first_pass" in output
    assert "Experiment: contextatlas_external_indexing_strategies" in output
    assert "Best Variant: indexing_freshness-guard-external" in output
    assert "Best By Quality: indexing_incremental-refresh-patch" in output
    assert "cost_penalty=0.8" in output
    assert "Cost-sensitive winner differs from quality winner." in output
