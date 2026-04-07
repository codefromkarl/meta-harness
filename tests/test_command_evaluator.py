from __future__ import annotations

import json
from pathlib import Path

from meta_harness.scoring import score_run


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_score_run_merges_command_evaluator_outputs(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run123"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)

    write_json(
        run_dir / "effective_config.json",
        {
            "evaluation": {
                "evaluators": ["basic", "command"],
                "command_evaluators": [
                    {
                        "name": "maint-check",
                        "command": [
                            "python",
                            "-c",
                            (
                                "import json; print(json.dumps({"
                                "'maintainability': {'lint_warnings': 3}, "
                                "'architecture': {'dependency_violations': 1}, "
                                "'retrieval': {'hit_rate': 0.8}, "
                                "'composite_adjustment': -0.25"
                                "}))"
                            ),
                        ],
                    }
                ],
            }
        },
    )
    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run123", "profile": "base", "project": "demo"},
    )
    (task_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "step_id": "step-1",
                "phase": "review",
                "status": "completed",
                "latency_ms": 30,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = score_run(run_dir)

    assert report["correctness"]["completed_steps"] == 1
    assert report["maintainability"]["lint_warnings"] == 3
    assert report["architecture"]["dependency_violations"] == 1
    assert report["retrieval"]["hit_rate"] == 0.8
    assert report["cost"]["command_evaluators_run"] == 1
    assert report["composite"] == 0.75
    evaluator_report = json.loads(
        (run_dir / "evaluators" / "basic.json").read_text(encoding="utf-8")
    )
    command_report = json.loads(
        (run_dir / "evaluators" / "command.json").read_text(encoding="utf-8")
    )
    assert evaluator_report["correctness"]["completed_steps"] == 1
    assert command_report["architecture"]["dependency_violations"] == 1


def test_score_run_merges_capability_scores_workflow_scores_and_probes(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-workflow"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)

    write_json(
        run_dir / "effective_config.json",
        {
            "evaluation": {
                "evaluators": ["basic", "command"],
                "command_evaluators": [
                    {
                        "name": "workflow-pack",
                        "command": [
                            "python",
                            "-c",
                            (
                                "import json; print(json.dumps({"
                                "'capability_scores': {'web_scrape': {'success_rate': 0.92}}, "
                                "'workflow_scores': {'hot_path_success_rate': 0.88}, "
                                "'probes': {'scrape.navigation_depth': 2}"
                                "}))"
                            ),
                        ],
                    }
                ],
            }
        },
    )
    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run-workflow", "profile": "base", "project": "demo"},
    )
    (task_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "step_id": "step-1",
                "phase": "review",
                "status": "completed",
                "latency_ms": 30,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = score_run(run_dir)

    assert report["capability_scores"] == {"web_scrape": {"success_rate": 0.92}}
    assert report["workflow_scores"] == {"hot_path_success_rate": 0.88}
    assert report["probes"] == {"scrape.navigation_depth": 2}


def test_score_run_applies_calibration_variance_probe_adjustment_only_when_present(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-calibration"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)

    write_json(
        run_dir / "effective_config.json",
        {
            "evaluation": {
                "evaluators": ["basic"],
            }
        },
    )
    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run-calibration", "profile": "base", "project": "demo"},
    )
    (task_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "step_id": "step-1",
                "phase": "review",
                "status": "completed",
                "latency_ms": 30,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (task_dir / "variance_probe.stdout.txt").write_text(
        json.dumps(
            {
                "fingerprints": {"calibration.run_parity": 1},
                "probes": {
                    "calibration.synthetic_variance": 0.9,
                    "calibration.instability_trigger": 1,
                },
            }
        ),
        encoding="utf-8",
    )

    report = score_run(run_dir)

    assert report["correctness"]["completed_steps"] == 1
    assert report["composite"] < 1.0


def test_score_run_leaves_normal_runs_unchanged_without_calibration_probe(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-normal"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)

    write_json(
        run_dir / "effective_config.json",
        {
            "evaluation": {
                "evaluators": ["basic"],
            }
        },
    )
    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run-normal", "profile": "base", "project": "demo"},
    )
    (task_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "step_id": "step-1",
                "phase": "review",
                "status": "completed",
                "latency_ms": 30,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = score_run(run_dir)

    assert report["composite"] == 1.0
