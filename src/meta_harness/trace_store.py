from __future__ import annotations

import json
from pathlib import Path

from meta_harness.schemas import TraceEvent


def _load_trace_context(run_dir: Path, task_id: str) -> dict[str, str | None]:
    metadata_path = run_dir / "run_metadata.json"
    metadata: dict[str, str | None] = {}
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    return {
        "run_id": str(metadata.get("run_id") or run_dir.name),
        "task_id": task_id,
        "candidate_id": (
            str(metadata["candidate_id"]) if metadata.get("candidate_id") is not None else None
        ),
    }


def append_trace_event(run_dir: Path, task_id: str, event: dict) -> None:
    task_dir = run_dir / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    trace_event = TraceEvent.model_validate(
        {
            **_load_trace_context(run_dir, task_id),
            **event,
        }
    )
    steps_path = task_dir / "steps.jsonl"
    with steps_path.open("a", encoding="utf-8") as handle:
        handle.write(trace_event.model_dump_json())
        handle.write("\n")
