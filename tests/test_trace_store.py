from __future__ import annotations

import json
from pathlib import Path

from meta_harness.trace_store import append_trace_event


def test_append_trace_event_writes_jsonl_for_task(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run123"
    (run_dir / "tasks").mkdir(parents=True)

    append_trace_event(
        run_dir=run_dir,
        task_id="task-a",
        event={
            "step_id": "step-1",
            "phase": "retrieve",
            "status": "completed",
            "latency_ms": 42,
        },
    )

    steps_path = run_dir / "tasks" / "task-a" / "steps.jsonl"
    assert steps_path.exists()

    lines = steps_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    payload = json.loads(lines[0])
    assert payload["step_id"] == "step-1"
    assert payload["phase"] == "retrieve"
    assert payload["status"] == "completed"
    assert payload["latency_ms"] == 42
    assert "timestamp" in payload


def test_append_trace_event_preserves_v2_fields_and_enriches_context(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run456"
    (run_dir / "tasks").mkdir(parents=True)
    (run_dir / "run_metadata.json").write_text(
        json.dumps(
            {
                "run_id": "run456",
                "profile": "base",
                "project": "demo",
                "candidate_id": "cand-001",
            }
        ),
        encoding="utf-8",
    )

    append_trace_event(
        run_dir=run_dir,
        task_id="task-b",
        event={
            "step_id": "step-2",
            "phase": "tool_call",
            "status": "completed",
            "latency_ms": 7,
            "session_ref": "session://demo/run456/task-b",
            "candidate_harness_id": "candidate-harness-001",
            "proposal_id": "proposal-42",
            "iteration_id": "iter-7",
            "wrapper_path": "/tmp/harness-wrapper.py",
            "source_artifacts": ["/tmp/harness-wrapper.py"],
            "provenance": {"source": "test-suite"},
            "model": "gpt-5.4",
            "prompt_ref": "prompts/retrieve@v2",
            "tool_name": "codebase-retrieval",
            "tool_call_id": "tool-123",
            "retrieval_refs": ["mem://m1", "code://f1"],
            "artifact_refs": ["artifacts/request.json"],
            "token_usage": {"input_tokens": 12, "output_tokens": 5},
        },
    )

    payload = json.loads(
        (run_dir / "tasks" / "task-b" / "steps.jsonl").read_text(encoding="utf-8")
    )

    assert payload["run_id"] == "run456"
    assert payload["task_id"] == "task-b"
    assert payload["candidate_id"] == "cand-001"
    assert payload["session_ref"] == "session://demo/run456/task-b"
    assert payload["candidate_harness_id"] == "candidate-harness-001"
    assert payload["proposal_id"] == "proposal-42"
    assert payload["iteration_id"] == "iter-7"
    assert payload["wrapper_path"] == "/tmp/harness-wrapper.py"
    assert payload["source_artifacts"] == ["/tmp/harness-wrapper.py"]
    assert payload["provenance"] == {"source": "test-suite"}
    assert payload["model"] == "gpt-5.4"
    assert payload["prompt_ref"] == "prompts/retrieve@v2"
    assert payload["tool_name"] == "codebase-retrieval"
    assert payload["tool_call_id"] == "tool-123"
    assert payload["retrieval_refs"] == ["mem://m1", "code://f1"]
    assert payload["artifact_refs"] == ["artifacts/request.json"]
    assert payload["token_usage"] == {"input_tokens": 12, "output_tokens": 5}


def test_append_trace_event_backfills_session_ref_when_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run789"
    (run_dir / "tasks").mkdir(parents=True)
    (run_dir / "run_metadata.json").write_text(
        json.dumps({"run_id": "run789", "profile": "base", "project": "demo"}),
        encoding="utf-8",
    )

    append_trace_event(
        run_dir=run_dir,
        task_id="task-z",
        event={
            "step_id": "step-1",
            "phase": "analysis",
            "status": "completed",
        },
    )

    payload = json.loads(
        (run_dir / "tasks" / "task-z" / "steps.jsonl").read_text(encoding="utf-8")
    )

    assert payload["session_ref"] == "session://run789/task-z"
