from __future__ import annotations

import json
from pathlib import Path
import subprocess


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_contextatlas_first_pass_runner_dry_run_emits_plan_and_shortlist(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    runner_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "contextatlas_first_pass_runner.py"
    )
    card_a = tmp_path / "a.json"
    card_b = tmp_path / "b.json"
    pool_path = tmp_path / "pool.json"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {
            "workflow": "base",
            "overrides": {
                "runtime": {"workspace": {"source_repo": str(repo_root)}},
            },
        },
    )
    write_json(
        card_a,
        {
            "strategy_id": "indexing/a",
            "title": "A",
            "source": "reference://a",
            "category": "indexing",
            "group": "chunking",
            "priority": 20,
            "change_type": "config_only",
            "config_patch": {"indexing": {"chunk_size": 1200}},
        },
    )
    write_json(
        card_b,
        {
            "strategy_id": "indexing/b",
            "title": "B",
            "source": "reference://b",
            "category": "indexing",
            "group": "incremental",
            "priority": 10,
            "change_type": "config_only",
            "config_patch": {"indexing": {"chunk_size": 1400}},
            "compatibility": {"review_required": True},
        },
    )
    write_json(
        pool_path,
        {
            "name": "contextatlas_first_pass",
            "profile": "base",
            "project": "demo",
            "suite": "configs/benchmarks/contextatlas_external_strategy_first_pass_suite.json",
            "task_set": "task_sets/contextatlas/benchmark_indexing_architecture_v2.json",
            "summary_script": "scripts/contextatlas_benchmark_summary.py",
            "strategy_cards": [str(card_a), str(card_b)],
            "decision_policy": {
                "prefer_status": ["executable", "review_required"],
                "max_blocked": 0
            }
        },
    )

    completed = subprocess.run(
        [
            "python",
            str(runner_path),
            "--pool",
            str(pool_path),
            "--config-root",
            str(config_root),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["pool"] == "contextatlas_first_pass"
    assert payload["shortlist"]["summary"] == {
        "total": 2,
        "executable": 1,
        "review_required": 1,
        "blocked": 0,
    }
    assert payload["recommended_cards"] == [
        "indexing/a",
        "indexing/b",
    ]
    assert payload["commands"]["benchmark_suite"][-1].endswith(
        "configs/benchmarks/contextatlas_external_strategy_first_pass_suite.json"
    )
    assert payload["commands"]["summary"][0] == "python"
    assert payload["commands"]["summary"][1].endswith(
        "scripts/contextatlas_benchmark_summary.py"
    )
    assert payload["commands"]["summary"][2] == "<benchmark-suite-output.json>"


def test_contextatlas_first_pass_pool_assets_exist() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    pool_path = (
        repo_root
        / "configs"
        / "strategy_pools"
        / "contextatlas_first_pass.json"
    )
    doc_path = repo_root / "docs" / "external-strategy-evaluation.md"
    payload = json.loads(pool_path.read_text(encoding="utf-8"))
    doc = doc_path.read_text(encoding="utf-8")

    assert payload["name"] == "contextatlas_first_pass"
    assert payload["profile"] == "contextatlas_benchmark"
    assert payload["project"] == "contextatlas_benchmark"
    assert payload["suite"] == (
        "configs/benchmarks/contextatlas_external_strategy_first_pass_suite.json"
    )
    assert payload["task_set"] == (
        "task_sets/contextatlas/benchmark_indexing_architecture_v2.json"
    )
    assert payload["summary_script"] == "scripts/contextatlas_benchmark_summary.py"
    assert payload["strategy_cards"] == [
        "configs/strategy_cards/contextatlas/dense_chunking_external.json",
        "configs/strategy_cards/contextatlas/freshness_guard_external.json",
        "configs/strategy_cards/contextatlas/incremental_refresh_patch.json",
        "configs/strategy_cards/contextatlas/graph_posting_lists_research_only.json",
    ]
    assert payload["decision_policy"] == {
        "prefer_status": ["executable", "review_required"],
        "max_blocked": 1,
    }
    assert "configs/strategy_pools/contextatlas_first_pass.json" in doc


def test_contextatlas_first_pass_runner_executes_suite_and_writes_outputs(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    output_dir = tmp_path / "reports"
    runner_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "contextatlas_first_pass_runner.py"
    )
    evaluator_script = tmp_path / "score_from_config.py"
    task_set = tmp_path / "task_set.json"
    spec_path = tmp_path / "spec.json"
    suite_path = tmp_path / "suite.json"
    card_path = tmp_path / "card.json"
    pool_path = tmp_path / "pool.json"

    evaluator_script.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "from pathlib import Path",
                "payload = json.loads(Path('effective_config.json').read_text(encoding='utf-8'))",
                "indexing = payload.get('indexing', {})",
                "chunk_size = int(indexing.get('chunk_size', 1000))",
                "bonus = 1.0 if chunk_size >= 1200 else 0.2",
                "print(json.dumps({'architecture': {'index_freshness_ratio': 0.95 if chunk_size >= 1200 else 0.88}, 'cost': {'index_build_latency_ms': 240.0 if chunk_size >= 1200 else 180.0}, 'composite_adjustment': bonus}))",
            ]
        ),
        encoding="utf-8",
    )
    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {
            "description": "workflow",
            "defaults": {
                "evaluation": {
                    "evaluators": ["basic", "command"],
                    "command_evaluators": [
                        {
                            "name": "runner-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                },
            },
        },
    )
    write_json(
        config_root / "projects" / "demo.json",
        {
            "workflow": "base",
            "overrides": {
                "runtime": {
                    "workspace": {
                        "source_repo": str(repo_root),
                    }
                }
            },
        },
    )
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "benchmark-task",
                    "scenario": "index_freshness_sensitive",
                    "difficulty": "medium",
                    "weight": 1.0,
                    "workdir": str(repo_root),
                    "phases": [
                        {
                            "phase": "prepare",
                            "command": ["python", "-c", "print('ok')"],
                        }
                    ],
                }
            ]
        },
    )
    write_json(
        spec_path,
        {
            "experiment": "first-pass-check",
            "baseline": "current_indexing",
            "variants": [
                {"name": "current_indexing"},
                {
                    "name": "indexing_dense",
                    "config_patch": {"indexing": {"chunk_size": 1200}},
                },
            ],
        },
    )
    write_json(
        suite_path,
        {
            "suite": "runner-suite",
            "benchmarks": [
                {
                    "spec": str(spec_path),
                    "focus": "indexing",
                    "task_set": str(task_set),
                }
            ],
        },
    )
    write_json(
        card_path,
        {
            "strategy_id": "indexing/dense",
            "title": "Dense",
            "source": "reference://dense",
            "category": "indexing",
            "priority": 10,
            "change_type": "config_only",
            "config_patch": {"indexing": {"chunk_size": 1200}},
        },
    )
    write_json(
        pool_path,
        {
            "name": "runner-pool",
            "profile": "base",
            "project": "demo",
            "suite": str(suite_path),
            "task_set": str(task_set),
            "summary_script": "scripts/contextatlas_benchmark_summary.py",
            "strategy_cards": [str(card_path)],
            "decision_policy": {
                "prefer_status": ["executable"],
                "max_blocked": 0,
            },
        },
    )

    completed = subprocess.run(
        [
            "python",
            str(runner_path),
            "--pool",
            str(pool_path),
            "--config-root",
            str(config_root),
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(completed.stdout)

    suite_output = Path(payload["artifacts"]["benchmark_suite_output"])
    summary_output = Path(payload["artifacts"]["summary_output"])
    conclusion_output = Path(payload["artifacts"]["conclusion_output"])
    report_output = Path(payload["artifacts"]["report_output"])

    assert payload["executed"] is True
    assert payload["shortlist"]["summary"]["executable"] == 1
    assert suite_output.exists()
    assert summary_output.exists()
    assert conclusion_output.exists()
    assert report_output.exists()
    suite_payload = json.loads(suite_output.read_text(encoding="utf-8"))
    summary_text = summary_output.read_text(encoding="utf-8")
    conclusion_payload = json.loads(conclusion_output.read_text(encoding="utf-8"))
    report_text = report_output.read_text(encoding="utf-8")
    assert suite_payload["suite"] == "runner-suite"
    assert "Suite: runner-suite" in summary_text
    assert "Best Variant: indexing_dense" in summary_text
    assert conclusion_payload["pool"] == "runner-pool"
    assert conclusion_payload["overall_status"] == "recommend_adopt"
    assert conclusion_payload["experiments"][0]["experiment"] == "first-pass-check"
    assert conclusion_payload["experiments"][0]["best_variant"] == "indexing_dense"
    assert "Runner Pool" in report_text
    assert "recommend_adopt" in report_text
