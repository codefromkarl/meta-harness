from __future__ import annotations

import json
from pathlib import Path

from meta_harness.failure_index import extract_failure_signatures


def test_extract_failure_signatures_writes_error_signature_file(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run123"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)

    steps = [
        {
            "step_id": "step-1",
            "phase": "compile",
            "status": "failed",
            "latency_ms": 18,
            "error": "Trait bound `Foo: Clone` is not satisfied",
        }
    ]
    (task_dir / "steps.jsonl").write_text(
        "\n".join(json.dumps(item) for item in steps) + "\n",
        encoding="utf-8",
    )

    records = extract_failure_signatures(run_dir)

    assert len(records) == 1
    assert records[0]["task_id"] == "task-a"
    assert "trait bound" in records[0]["signature"]

    signature_path = run_dir / "error_signatures.json"
    assert signature_path.exists()

    payload = json.loads(signature_path.read_text(encoding="utf-8"))
    assert payload[0]["phase"] == "compile"
    assert payload[0]["raw_error"] == "Trait bound `Foo: Clone` is not satisfied"
