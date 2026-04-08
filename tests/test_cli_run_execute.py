from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from meta_harness.cli import app


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_run_execute_runs_taskset_and_writes_task_results(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run123"
    (run_dir / "tasks").mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)
    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run123", "profile": "base", "project": "demo"},
    )
    write_json(
        run_dir / "effective_config.json",
        {"evaluation": {"evaluators": ["basic"]}},
    )

    task_set = tmp_path / "task_set.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "task-a",
                    "workdir": str(tmp_path),
                    "phases": [
                        {
                            "phase": "prepare",
                            "command": ["python", "-c", "print('prepare-ok')"],
                        },
                        {
                            "phase": "review",
                            "command": ["python", "-c", "print('review-ok')"],
                        },
                    ],
                }
            ]
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "execute",
            "--run-id",
            "run123",
            "--task-set",
            str(task_set),
            "--runs-root",
            str(runs_root),
        ],
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "1/1"

    task_result = json.loads(
        (run_dir / "tasks" / "task-a" / "task_result.json").read_text(encoding="utf-8")
    )
    assert task_result["success"] is True
    assert task_result["completed_phases"] == 2

    lines = (
        (run_dir / "tasks" / "task-a" / "steps.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert len(lines) == 2
    assert json.loads(lines[0])["phase"] == "prepare"
    assert json.loads(lines[1])["phase"] == "review"
    assert json.loads(lines[0])["run_id"] == "run123"
    assert json.loads(lines[0])["task_id"] == "task-a"
    assert json.loads(lines[0])["candidate_id"] is None


def test_run_execute_records_failure_and_stops_task(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run999"
    (run_dir / "tasks").mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)
    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run999", "profile": "base", "project": "demo"},
    )
    write_json(
        run_dir / "effective_config.json",
        {"evaluation": {"evaluators": ["basic"]}},
    )

    task_set = tmp_path / "task_set_fail.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "task-f",
                    "workdir": str(tmp_path),
                    "phases": [
                        {
                            "phase": "compile",
                            "command": [
                                "python",
                                "-c",
                                "import sys; print('compile failed', file=sys.stderr); sys.exit(1)",
                            ],
                        },
                        {
                            "phase": "review",
                            "command": ["python", "-c", "print('should-not-run')"],
                        },
                    ],
                }
            ]
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "execute",
            "--run-id",
            "run999",
            "--task-set",
            str(task_set),
            "--runs-root",
            str(runs_root),
        ],
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "0/1"

    task_result = json.loads(
        (run_dir / "tasks" / "task-f" / "task_result.json").read_text(encoding="utf-8")
    )
    assert task_result["success"] is False
    assert task_result["failed_phase"] == "compile"

    lines = (
        (run_dir / "tasks" / "task-f" / "steps.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["status"] == "failed"
    assert payload["error"] == "compile failed"
    assert payload["run_id"] == "run999"
    assert payload["task_id"] == "task-f"


def test_run_execute_resolves_nested_effective_config_templates(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run-nested"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (run_dir / "tasks").mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)
    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run-nested", "profile": "base", "project": "demo"},
    )
    write_json(
        run_dir / "effective_config.json",
        {
            "integration": {
                "repo_path": str(repo_root),
                "project_id": "project-123",
            }
        },
    )

    task_set = tmp_path / "task_set_nested.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "task-nested",
                    "workdir": "${integration.repo_path}",
                    "phases": [
                        {
                            "phase": "inspect",
                            "command": [
                                "python",
                                "-c",
                                "import os; print(os.getcwd()); print('project=' + 'project-123')",
                            ],
                        },
                        {
                            "phase": "inspect_template",
                            "command": [
                                "python",
                                "-c",
                                "print('project=${integration.project_id}')",
                            ],
                        },
                    ],
                }
            ]
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "execute",
            "--run-id",
            "run-nested",
            "--task-set",
            str(task_set),
            "--runs-root",
            str(runs_root),
        ],
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "1/1"

    task_result = json.loads(
        (run_dir / "tasks" / "task-nested" / "task_result.json").read_text(
            encoding="utf-8"
        )
    )
    assert task_result["workdir"] == str(repo_root)
    assert (run_dir / "tasks" / "task-nested" / "inspect.stdout.txt").read_text(
        encoding="utf-8"
    ).splitlines()[0] == str(repo_root)
    assert (
        run_dir / "tasks" / "task-nested" / "inspect_template.stdout.txt"
    ).read_text(encoding="utf-8").strip() == "project=project-123"


def test_run_execute_can_skip_scoring_via_cli_flag(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run-no-score"
    (run_dir / "tasks").mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)
    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run-no-score", "profile": "base", "project": "demo"},
    )
    write_json(
        run_dir / "effective_config.json",
        {"evaluation": {"evaluators": ["basic"]}},
    )

    task_set = tmp_path / "task_set_no_score.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "task-a",
                    "workdir": str(tmp_path),
                    "phases": [
                        {
                            "phase": "prepare",
                            "command": ["python", "-c", "print('prepare-ok')"],
                        }
                    ],
                }
            ]
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "execute",
            "--run-id",
            "run-no-score",
            "--task-set",
            str(task_set),
            "--runs-root",
            str(runs_root),
            "--no-score",
        ],
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "1/1"
    assert not (run_dir / "score_report.json").exists()
