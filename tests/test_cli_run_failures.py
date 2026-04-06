from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from meta_harness.cli import app


def make_failed_run(
    runs_root: Path,
    run_id: str,
    profile: str,
    project: str,
    task_id: str,
    error: str,
) -> None:
    run_dir = runs_root / run_id
    task_dir = run_dir / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (run_dir / "run_metadata.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "profile": profile,
                "project": project,
                "created_at": "2026-04-05T10:00:00Z",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_dir / "effective_config.json").write_text(
        json.dumps({"evaluation": {"evaluators": ["basic"]}}, indent=2),
        encoding="utf-8",
    )
    (task_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "step_id": "step-1",
                "phase": "compile",
                "status": "failed",
                "latency_ms": 11,
                "error": error,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_run_failures_queries_similar_errors(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    make_failed_run(
        runs_root,
        "run-a",
        "java_to_rust",
        "voidsector",
        "task-a",
        "Trait bound `Foo: Clone` is not satisfied",
    )
    make_failed_run(
        runs_root,
        "run-b",
        "java_to_rust",
        "voidsector",
        "task-b",
        "Borrow checker error: cannot move out of borrowed content",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "failures",
            "--query",
            "trait bound",
            "--runs-root",
            str(runs_root),
        ],
    )

    assert result.exit_code == 0
    lines = result.stdout.strip().splitlines()
    assert "run-a\ttask-a\tcompile\ttrait bound foo clone is not satisfied" in lines
    assert all("run-b" not in line for line in lines)
