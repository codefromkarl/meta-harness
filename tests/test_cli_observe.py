from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from meta_harness.cli import app


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def make_run(
    runs_root: Path,
    run_id: str,
    *,
    profile: str,
    project: str,
    created_at: str,
    composite: float,
    maintainability: dict | None = None,
    architecture: dict | None = None,
    retrieval: dict | None = None,
) -> None:
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
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
        {"evaluation": {"evaluators": ["basic", "command"]}},
    )
    write_json(
        run_dir / "score_report.json",
        {
            "correctness": {"task_count": 1, "completed_steps": 1},
            "cost": {"trace_event_count": 1, "command_evaluators_run": 1},
            "maintainability": maintainability or {},
            "architecture": architecture or {},
            "retrieval": retrieval or {},
            "human_collaboration": {"manual_interventions": 0},
            "composite": composite,
        },
    )


def make_observe_task_set(path: Path, command: list[str], *, workdir: str) -> None:
    write_json(
        path,
        {
            "tasks": [
                {
                    "task_id": "observe-task",
                    "workdir": workdir,
                    "phases": [
                        {
                            "phase": "prepare",
                            "command": command,
                        }
                    ],
                }
            ]
        },
    )


def test_observe_once_runs_task_set_and_emits_summary_payload(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    repo_root = tmp_path / "repo"
    task_set = tmp_path / "observe_task_set.json"

    repo_root.mkdir(parents=True, exist_ok=True)
    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {"evaluation": {"evaluators": ["basic"]}}},
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
    make_observe_task_set(
        task_set,
        [
            "python",
            "-c",
            "print('ready')",
        ],
        workdir=str(repo_root),
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "once",
            "--profile",
            "base",
            "--project",
            "demo",
            "--config-root",
            str(config_root),
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
            "--task-set",
            str(task_set),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)

    assert payload["run_id"]
    assert payload["score"]["composite"] == 1.0
    assert payload["needs_optimization"] is False
    assert payload["recommended_focus"] == "none"
    assert payload["architecture_recommendation"] is None
    assert payload["triggered_optimization"] is False
    assert "candidate_id" not in payload


def test_observe_summary_reports_latest_best_and_need_for_optimization(
    tmp_path: Path,
) -> None:
    runs_root = tmp_path / "runs"

    make_run(
        runs_root,
        "run-old-best",
        profile="base",
        project="demo",
        created_at="2026-04-05T10:00:00Z",
        composite=4.0,
        maintainability={
            "profile_present": True,
            "memory_consistency_ok": True,
        },
        architecture={
            "snapshot_ready": True,
            "vector_index_ready": True,
            "db_integrity_ok": True,
        },
        retrieval={
            "retrieval_hit_rate": 0.81,
            "retrieval_mrr": 0.61,
            "grounded_answer_rate": 0.88,
        },
    )
    make_run(
        runs_root,
        "run-latest-gap",
        profile="base",
        project="demo",
        created_at="2026-04-05T11:00:00Z",
        composite=2.0,
        maintainability={
            "profile_present": True,
            "memory_consistency_ok": False,
            "memory_completeness": 0.6,
            "memory_freshness": 0.8,
            "memory_stale_ratio": 0.2,
        },
        architecture={
            "snapshot_ready": True,
            "vector_index_ready": True,
            "db_integrity_ok": True,
            "vector_coverage_ratio": 0.95,
            "index_freshness_ratio": 0.91,
        },
        retrieval={
            "retrieval_hit_rate": 0.79,
            "retrieval_mrr": 0.6,
            "grounded_answer_rate": 0.85,
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "summary",
            "--profile",
            "base",
            "--project",
            "demo",
            "--runs-root",
            str(runs_root),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)

    assert payload["run_count"] == 2
    assert payload["latest_run_id"] == "run-latest-gap"
    assert payload["best_run_id"] == "run-old-best"
    assert payload["needs_optimization"] is True
    assert payload["recommended_focus"] == "memory"
    assert payload["architecture_recommendation"] == {
        "focus": "memory",
        "variant_type": "method_family",
        "proposal_strategy": "explore_memory_method_family",
        "hypothesis": "restore profile import and memory consistency before further retrieval optimization",
        "gap_signals": ["memory_consistency_ok"],
        "metric_thresholds": {
            "memory_completeness": 0.8,
            "memory_freshness": 0.85,
            "memory_stale_ratio": 0.1,
        },
    }


def test_observe_once_auto_propose_creates_candidate_when_needed(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    repo_root = tmp_path / "repo"
    task_set = tmp_path / "observe_task_set.json"
    proposal_script = tmp_path / "proposal_generator.py"

    repo_root.mkdir(parents=True, exist_ok=True)
    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {"evaluation": {"evaluators": ["basic"]}}},
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
                },
                "optimization": {
                    "proposal_command": ["python", str(proposal_script)],
                },
            },
        },
    )
    proposal_script.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "import sys",
                "payload = json.load(sys.stdin)",
                "print(json.dumps({",
                "  'notes': 'auto propose from observe',",
                "  'proposal': {",
                "    'strategy': 'observe_auto_propose',",
                "    'source_runs': [record['run_id'] for record in payload['matching_runs']]",
                "  },",
                "  'config_patch': {",
                "    'optimization': {'focus': 'retrieval'}",
                "  }",
                "}))",
            ]
        ),
        encoding="utf-8",
    )
    make_observe_task_set(task_set, ["python", "-c", "pass"], workdir=str(repo_root))

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "once",
            "--profile",
            "base",
            "--project",
            "demo",
            "--config-root",
            str(config_root),
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
            "--task-set",
            str(task_set),
            "--auto-propose",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)

    assert payload["needs_optimization"] is True
    assert payload["triggered_optimization"] is True
    assert payload["candidate_id"]
    assert payload["architecture_recommendation"] == {
        "focus": "retrieval",
        "variant_type": "method_family",
        "proposal_strategy": "explore_retrieval_method_family",
        "hypothesis": "improve retrieval hit rate, ranking quality, and grounded answer generation",
        "gap_signals": [],
        "metric_thresholds": {
            "retrieval_hit_rate": 0.7,
            "retrieval_mrr": 0.5,
            "grounded_answer_rate": 0.8,
        },
    }


def test_observe_once_auto_propose_creates_builtin_method_family_candidate_without_proposal_command(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    repo_root = tmp_path / "repo"
    task_set = tmp_path / "observe_task_set.json"
    evaluator_script = tmp_path / "score_gap.py"

    repo_root.mkdir(parents=True, exist_ok=True)
    evaluator_script.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "print(json.dumps({",
                "  'retrieval': {",
                "    'retrieval_hit_rate': 0.41,",
                "    'retrieval_mrr': 0.29,",
                "    'grounded_answer_rate': 0.62",
                "  }",
                "}))",
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
                            "name": "gap-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                }
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
    make_observe_task_set(task_set, ["python", "-c", "pass"], workdir=str(repo_root))

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "once",
            "--profile",
            "base",
            "--project",
            "demo",
            "--config-root",
            str(config_root),
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
            "--task-set",
            str(task_set),
            "--auto-propose",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)

    assert payload["needs_optimization"] is True
    assert payload["triggered_optimization"] is True
    assert payload["candidate_id"]
    candidate_dir = candidates_root / str(payload["candidate_id"])
    proposal = json.loads((candidate_dir / "proposal.json").read_text(encoding="utf-8"))
    effective_config = json.loads(
        (candidate_dir / "effective_config.json").read_text(encoding="utf-8")
    )

    assert payload["architecture_recommendation"] == {
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
    assert proposal == {
        "strategy": "explore_retrieval_method_family",
        "variant_type": "method_family",
        "hypothesis": "improve retrieval hit rate, ranking quality, and grounded answer generation",
        "source_runs": [payload["run_id"]],
        "architecture_recommendation": payload["architecture_recommendation"],
        "expected_signals": {
            "probes": {
                "retrieval.retrieval_budget": {"min": 1},
            }
        },
        "tags": ["auto-propose", "method-family", "retrieval"],
    }
    assert effective_config["optimization"]["focus"] == "retrieval"
    assert effective_config["optimization"]["architecture_recommendation"] == payload[
        "architecture_recommendation"
    ]
