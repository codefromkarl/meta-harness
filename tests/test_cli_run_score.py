from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from meta_harness.cli import app


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_run_score_writes_score_report(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run123"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)

    write_json(
        run_dir / "effective_config.json",
        {"evaluation": {"evaluators": ["basic"]}},
    )
    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run123", "profile": "base", "project": "demo"},
    )
    (task_dir / "steps.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "step_id": "step-1",
                        "phase": "parse",
                        "status": "completed",
                        "latency_ms": 20,
                    }
                ),
                json.dumps(
                    {
                        "step_id": "step-2",
                        "phase": "review",
                        "status": "completed",
                        "latency_ms": 30,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    write_json(task_dir / "intervention.json", {"manual_interventions": 1})

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "score",
            "--run-id",
            "run123",
            "--runs-root",
            str(runs_root),
        ],
    )

    assert result.exit_code == 0

    score_report = json.loads((run_dir / "score_report.json").read_text(encoding="utf-8"))
    evaluator_report = json.loads(
        (run_dir / "evaluators" / "basic.json").read_text(encoding="utf-8")
    )
    assert score_report["correctness"]["task_count"] == 1
    assert score_report["correctness"]["completed_steps"] == 2
    assert score_report["cost"]["trace_event_count"] == 2
    assert score_report["human_collaboration"]["manual_interventions"] == 1
    assert score_report["composite"] == 1.5
    assert evaluator_report["evaluator_name"] == "basic"
    assert evaluator_report["run_id"] == "run123"
    assert evaluator_report["status"] == "completed"
    assert evaluator_report["report"]["composite"] == 1.5


def test_run_score_writes_trace_grade_into_evaluator_envelope(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run-trace"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)

    write_json(
        run_dir / "effective_config.json",
        {"evaluation": {"evaluators": ["basic"]}},
    )
    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run-trace", "profile": "base", "project": "demo"},
    )
    (task_dir / "steps.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "step_id": "step-1",
                        "phase": "search",
                        "status": "completed",
                        "session_ref": "session://run-trace/task-a",
                        "retrieval_refs": ["mem://1"],
                    }
                ),
                json.dumps(
                    {
                        "step_id": "step-2",
                        "phase": "tool_call",
                        "status": "completed",
                        "session_ref": "session://run-trace/task-a",
                        "tool_name": "rg",
                    }
                ),
                json.dumps(
                    {
                        "step_id": "step-3",
                        "phase": "assistant_reply",
                        "status": "completed",
                        "session_ref": "session://run-trace/task-a",
                        "model": "gpt-5.4",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "score",
            "--run-id",
            "run-trace",
            "--runs-root",
            str(runs_root),
        ],
    )

    assert result.exit_code == 0

    evaluator_report = json.loads(
        (run_dir / "evaluators" / "basic.json").read_text(encoding="utf-8")
    )
    assert evaluator_report["trace_grade"]["event_count"] == 3
    assert evaluator_report["trace_grade"]["failure_count"] == 0


def test_run_score_with_command_evaluator_updates_report(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run456"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)

    write_json(
        run_dir / "effective_config.json",
        {
            "evaluation": {
                "evaluators": ["basic", "command"],
                "command_evaluators": [
                    {
                        "name": "arch-check",
                        "command": [
                            "python",
                            "-c",
                            (
                                "import json; print(json.dumps({"
                                "'architecture': {'layering_violations': 2}, "
                                "'composite_adjustment': -0.5"
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
        {"run_id": "run456", "profile": "base", "project": "demo"},
    )
    (task_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "step_id": "step-1",
                "phase": "review",
                "status": "completed",
                "latency_ms": 15,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "score",
            "--run-id",
            "run456",
            "--runs-root",
            str(runs_root),
        ],
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "0.5"

    score_report = json.loads((run_dir / "score_report.json").read_text(encoding="utf-8"))
    assert score_report["architecture"]["layering_violations"] == 2
    assert score_report["cost"]["command_evaluators_run"] == 1
    assert score_report["composite"] == 0.5


def test_run_score_can_select_specific_evaluator(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run789"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)

    write_json(
        run_dir / "effective_config.json",
        {
            "evaluation": {
                "evaluators": ["basic", "command"],
                "command_evaluators": [
                    {
                        "name": "arch-check",
                        "command": [
                            "python",
                            "-c",
                            (
                                "import json; print(json.dumps({"
                                "'architecture': {'layering_violations': 3}, "
                                "'composite_adjustment': -0.75"
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
        {"run_id": "run789", "profile": "base", "project": "demo"},
    )
    (task_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "step_id": "step-1",
                "phase": "review",
                "status": "completed",
                "latency_ms": 15,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "score",
            "--run-id",
            "run789",
            "--runs-root",
            str(runs_root),
            "--evaluator",
            "command",
        ],
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "-0.75"

    score_report = json.loads((run_dir / "score_report.json").read_text(encoding="utf-8"))
    assert score_report["architecture"]["layering_violations"] == 3
    assert score_report["correctness"] == {}
    assert score_report["cost"]["command_evaluators_run"] == 1
