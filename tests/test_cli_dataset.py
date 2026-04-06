from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from meta_harness.cli import app
from meta_harness.datasets import build_dataset_from_task_set


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_dataset_extract_failures_writes_dataset_json(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    output_path = tmp_path / "datasets" / "failure_cases.json"
    run_dir = runs_root / "run123"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)

    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run123", "profile": "base", "project": "demo"},
    )
    write_json(run_dir / "effective_config.json", {"evaluation": {"evaluators": ["basic"]}})
    (task_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "run_id": "run123",
                "task_id": "task-a",
                "step_id": "step-1",
                "phase": "compile",
                "status": "failed",
                "error": "Trait bound `Foo: Clone` is not satisfied",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "dataset",
            "extract-failures",
            "--runs-root",
            str(runs_root),
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["dataset_id"] == "failure-signatures"
    assert payload["case_count"] == 1
    assert payload["schema_version"] == "2026-04-06"
    assert payload["cases"][0]["run_id"] == "run123"
    assert payload["cases"][0]["task_id"] == "task-a"
    assert payload["cases"][0]["failure_signature"] == "trait bound foo clone is not satisfied"


def test_build_dataset_from_task_set_preserves_task_metadata(tmp_path: Path) -> None:
    task_set_path = tmp_path / "task_set.json"
    write_json(
        task_set_path,
        {
            "tasks": [
                {
                    "task_id": "task-a",
                    "scenario": "cross_file_dependency_trace",
                    "difficulty": "hard",
                    "weight": 1.5,
                    "expectations": {"must_pass": ["build", "tests"]},
                    "workdir": "/tmp/workspace",
                    "phases": [
                        {"phase": "prepare", "command": ["python", "-c", "print('ok')"]},
                        {"phase": "review", "command": ["python", "-c", "print('done')"]},
                    ],
                }
            ]
        },
    )

    payload = build_dataset_from_task_set(
        task_set_path,
        dataset_id="benchmark-cases",
        version="v2",
    )

    assert payload["dataset_id"] == "benchmark-cases"
    assert payload["version"] == "v2"
    assert payload["schema_version"] == "2026-04-06"
    assert payload["case_count"] == 1
    case = payload["cases"][0]
    assert case["source_type"] == "task_set"
    assert case["task_id"] == "task-a"
    assert case["scenario"] == "cross_file_dependency_trace"
    assert case["difficulty"] == "hard"
    assert case["weight"] == 1.5
    assert case["expectations"] == {"must_pass": ["build", "tests"]}
    assert case["phase_names"] == ["prepare", "review"]
