from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from meta_harness.cli import app


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_run_export_trace_writes_otel_json(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run123"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)
    output_path = tmp_path / "trace-export.json"

    write_json(
        run_dir / "run_metadata.json",
        {
            "run_id": "run123",
            "profile": "base",
            "project": "demo",
            "candidate_id": "cand-001",
        },
    )
    write_json(run_dir / "effective_config.json", {"evaluation": {"evaluators": ["basic"]}})
    (task_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "run_id": "run123",
                "task_id": "task-a",
                "candidate_id": "cand-001",
                "step_id": "step-1",
                "phase": "tool_call",
                "status": "completed",
                "tool_name": "rg",
                "latency_ms": 12,
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
            "export-trace",
            "--run-id",
            "run123",
            "--runs-root",
            str(runs_root),
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "run123"
    assert len(payload["spans"]) == 1
    assert payload["spans"][0]["name"] == "task-a:tool_call"
    assert payload["spans"][0]["attributes"]["tool.name"] == "rg"
    assert payload["spans"][0]["attributes"]["meta_harness.candidate_id"] == "cand-001"


def test_run_export_trace_writes_phoenix_json(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run123"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)
    output_path = tmp_path / "trace-phoenix.json"

    write_json(
        run_dir / "run_metadata.json",
        {
            "run_id": "run123",
            "profile": "base",
            "project": "demo",
            "candidate_id": "cand-001",
        },
    )
    write_json(run_dir / "effective_config.json", {"evaluation": {"evaluators": ["basic"]}})
    (task_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "run_id": "run123",
                "task_id": "task-a",
                "candidate_id": "cand-001",
                "step_id": "step-1",
                "phase": "tool_call",
                "status": "completed",
                "tool_name": "rg",
                "latency_ms": 12,
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
            "export-trace",
            "--run-id",
            "run123",
            "--runs-root",
            str(runs_root),
            "--output",
            str(output_path),
            "--format",
            "phoenix-json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["project_name"] == "meta-harness/demo"
    assert payload["traces"][0]["trace_id"] == "run123"
    assert payload["traces"][0]["spans"][0]["name"] == "task-a:tool_call"


def test_run_export_trace_writes_langfuse_json(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run123"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)
    output_path = tmp_path / "trace-langfuse.json"

    write_json(
        run_dir / "run_metadata.json",
        {
            "run_id": "run123",
            "profile": "base",
            "project": "demo",
            "candidate_id": "cand-001",
        },
    )
    write_json(run_dir / "effective_config.json", {"evaluation": {"evaluators": ["basic"]}})
    (task_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "run_id": "run123",
                "task_id": "task-a",
                "candidate_id": "cand-001",
                "step_id": "step-1",
                "phase": "tool_call",
                "status": "completed",
                "tool_name": "rg",
                "latency_ms": 12,
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
            "export-trace",
            "--run-id",
            "run123",
            "--runs-root",
            str(runs_root),
            "--output",
            str(output_path),
            "--format",
            "langfuse-json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["trace"]["id"] == "run123"
    assert payload["trace"]["name"] == "meta-harness:demo"
    assert payload["observations"][0]["name"] == "task-a:tool_call"
    assert payload["observations"][0]["metadata"]["tool_name"] == "rg"
