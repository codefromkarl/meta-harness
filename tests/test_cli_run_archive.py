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
    profile: str,
    project: str,
    composite: float | None = None,
) -> None:
    run_dir = runs_root / run_id
    (run_dir / "tasks").mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    write_json(
        run_dir / "run_metadata.json",
        {
            "run_id": run_id,
            "profile": profile,
            "project": project,
            "created_at": "2026-04-05T10:00:00Z",
        },
    )
    write_json(run_dir / "effective_config.json", {"tools": ["rg"]})
    if composite is not None:
        write_json(
            run_dir / "score_report.json",
            {
                "correctness": {"task_count": 1, "completed_steps": 2},
                "cost": {"trace_event_count": 2},
                "maintainability": {},
                "architecture": {},
                "human_collaboration": {"manual_interventions": 0},
                "composite": composite,
            },
        )


def test_run_list_outputs_run_summary_lines(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    make_run(runs_root, "run-a", "base", "demo", 2.0)
    make_run(runs_root, "run-b", "java_to_rust", "voidsector", None)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "list",
            "--runs-root",
            str(runs_root),
        ],
    )

    assert result.exit_code == 0
    lines = result.stdout.strip().splitlines()
    assert "run-a\tbase\tdemo\t2.0" in lines
    assert "run-b\tjava_to_rust\tvoidsector\t-" in lines


def test_run_show_outputs_combined_json(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    make_run(runs_root, "run-a", "base", "demo", 2.0)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "show",
            "--run-id",
            "run-a",
            "--runs-root",
            str(runs_root),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["run_id"] == "run-a"
    assert payload["profile"] == "base"
    assert payload["project"] == "demo"
    assert payload["score"]["composite"] == 2.0


def test_run_diff_outputs_score_deltas(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    make_run(runs_root, "run-a", "base", "demo", 2.0)
    make_run(runs_root, "run-b", "base", "demo", 1.5)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "diff",
            "--left-run-id",
            "run-a",
            "--right-run-id",
            "run-b",
            "--runs-root",
            str(runs_root),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["left_run_id"] == "run-a"
    assert payload["right_run_id"] == "run-b"
    assert payload["score_delta"]["composite"] == -0.5
