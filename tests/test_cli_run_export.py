from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from meta_harness.cli import app


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_candidate_with_lineage(root: Path, candidate_id: str = "cand-001") -> None:
    candidate_dir = root / "candidates" / candidate_id
    candidate_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        candidate_dir / "candidate.json",
        {
            "candidate_id": candidate_id,
            "profile": "base",
            "project": "demo",
            "notes": "candidate",
            "proposal_id": "proposal-1",
            "source_proposal_ids": ["proposal-1"],
            "iteration_id": "iter-1",
            "source_iteration_ids": ["iter-1"],
            "source_run_ids": ["run-1"],
            "source_artifacts": ["reports/loops/loop-1/iteration.json"],
        },
    )
    write_json(candidate_dir / "effective_config.json", {"budget": {"max_turns": 12}})


def test_run_export_trace_writes_otel_json(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run123"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)
    output_path = tmp_path / "trace-export.json"
    write_candidate_with_lineage(tmp_path)

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
    assert payload["resource"]["attributes"]["meta_harness.candidate_lineage"]["proposal_id"] == "proposal-1"
    assert payload["resource"]["attributes"]["meta_harness.lineage.proposal_id"] == "proposal-1"
    assert payload["resource"]["attributes"]["meta_harness.lineage.iteration_id"] == "iter-1"
    assert payload["resource"]["attributes"]["meta_harness.lineage.source_run_ids"] == ["run-1"]
    assert payload["resource"]["attributes"]["meta_harness.lineage.source_artifacts"] == [
        "reports/loops/loop-1/iteration.json"
    ]
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
    write_candidate_with_lineage(tmp_path)

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
    assert payload["traces"][0]["metadata"]["candidate_lineage"]["proposal_id"] == "proposal-1"
    assert payload["traces"][0]["metadata"]["meta_harness.lineage.proposal_id"] == "proposal-1"
    assert payload["traces"][0]["spans"][0]["name"] == "task-a:tool_call"


def test_run_export_trace_writes_langfuse_json(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run123"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)
    output_path = tmp_path / "trace-langfuse.json"
    write_candidate_with_lineage(tmp_path)

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
    assert payload["trace"]["metadata"]["meta_harness.lineage.proposal_id"] == "proposal-1"
    assert payload["trace"]["metadata"]["meta_harness.lineage.source_run_ids"] == ["run-1"]
    assert payload["observations"][0]["name"] == "task-a:tool_call"
    assert payload["observations"][0]["metadata"]["tool_name"] == "rg"


def test_run_export_trace_preserves_artifact_refs_and_token_usage(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run123"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)
    output_path = tmp_path / "trace-export-artifacts.json"

    write_json(
        run_dir / "run_metadata.json",
        {
            "run_id": "run123",
            "profile": "base",
            "project": "demo",
        },
    )
    write_json(run_dir / "effective_config.json", {"evaluation": {"evaluators": ["basic"]}})
    (task_dir / "steps.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "run_id": "run123",
                        "task_id": "task-a",
                        "step_id": "step-1",
                        "phase": "analyze",
                        "status": "completed",
                        "model": "ops",
                        "artifact_refs": ["analyze.binding_payload.json"],
                        "token_usage": {"total": 321},
                        "latency_ms": 12,
                    }
                ),
                json.dumps(
                    {
                        "run_id": "run123",
                        "task_id": "task-a",
                        "step_id": "step-1-assistant",
                        "phase": "assistant_reply",
                        "status": "completed",
                        "model": "ops",
                        "artifact_refs": ["analyze.binding_payload.json"],
                        "token_usage": {"total": 321},
                        "latency_ms": 0,
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
    assert len(payload["spans"]) == 2
    assert payload["spans"][0]["attributes"]["gen_ai.request.model"] == "ops"
    assert payload["spans"][0]["attributes"]["meta_harness.artifact_refs"] == [
        "analyze.binding_payload.json"
    ]
    assert payload["spans"][0]["attributes"]["gen_ai.usage.total_tokens"] == 321


def test_run_export_trace_projects_candidate_lineage(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    run_dir = runs_root / "run123"
    task_dir = run_dir / "tasks" / "task-a"
    candidate_dir = candidates_root / "cand-001"
    task_dir.mkdir(parents=True)
    candidate_dir.mkdir(parents=True)
    output_path = tmp_path / "trace-export-lineage.json"

    write_json(
        candidate_dir / "candidate.json",
        {
            "candidate_id": "cand-001",
            "profile": "base",
            "project": "demo",
            "lineage": {
                "parent_candidate_id": None,
                "proposal_id": "proposal-1",
                "source_proposal_ids": ["proposal-1"],
                "iteration_id": "iter-1",
                "source_iteration_ids": ["iter-1"],
                "source_run_ids": ["run-older"],
                "source_artifacts": ["reports/loops/loop-1/iteration.json"],
            },
        },
    )
    write_json(candidate_dir / "effective_config.json", {"budget": {"max_turns": 12}})
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
    assert payload["resource"]["attributes"]["meta_harness.candidate_lineage"] == {
        "parent_candidate_id": None,
        "proposal_id": "proposal-1",
        "source_proposal_ids": ["proposal-1"],
        "iteration_id": "iter-1",
        "source_iteration_ids": ["iter-1"],
        "source_run_ids": ["run-older"],
        "source_artifacts": ["reports/loops/loop-1/iteration.json"],
    }


def test_run_export_trace_projects_candidate_lineage(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    run_dir = runs_root / "run123"
    task_dir = run_dir / "tasks" / "task-a"
    candidate_dir = candidates_root / "cand-001"
    task_dir.mkdir(parents=True)
    candidate_dir.mkdir(parents=True)
    output_path = tmp_path / "trace-export-lineage.json"

    write_json(
        candidate_dir / "candidate.json",
        {
            "candidate_id": "cand-001",
            "profile": "base",
            "project": "demo",
            "lineage": {
                "parent_candidate_id": None,
                "proposal_id": "proposal-1",
                "source_proposal_ids": ["proposal-1"],
                "iteration_id": "iter-1",
                "source_iteration_ids": ["iter-1"],
                "source_run_ids": ["run-older"],
                "source_artifacts": ["reports/loops/loop-1/iteration.json"],
            },
        },
    )
    write_json(candidate_dir / "effective_config.json", {"budget": {"max_turns": 12}})
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
    assert payload["resource"]["attributes"]["meta_harness.candidate_lineage"] == {
        "parent_candidate_id": None,
        "proposal_id": "proposal-1",
        "source_proposal_ids": ["proposal-1"],
        "iteration_id": "iter-1",
        "source_iteration_ids": ["iter-1"],
        "source_run_ids": ["run-older"],
        "source_artifacts": ["reports/loops/loop-1/iteration.json"],
    }
