from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meta_harness.services.trace_service import classify_trace_event_kind


def _parse_timestamp(raw: Any) -> datetime:
    if not raw:
        return datetime.now(UTC)
    text = str(raw).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(UTC)


def export_run_trace_otel_json(run_dir: Path) -> dict[str, Any]:
    metadata_path = run_dir / "run_metadata.json"
    metadata = (
        json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata_path.exists()
        else {}
    )
    spans: list[dict[str, Any]] = []
    tasks_dir = run_dir / "tasks"
    if tasks_dir.exists():
        for task_dir in sorted(path for path in tasks_dir.iterdir() if path.is_dir()):
            steps_path = task_dir / "steps.jsonl"
            if not steps_path.exists():
                continue
            for line in steps_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                timestamp = _parse_timestamp(payload.get("timestamp"))
                latency_ms = int(payload.get("latency_ms") or 0)
                spans.append(
                    {
                        "trace_id": str(payload.get("run_id", run_dir.name)),
                        "span_id": str(payload.get("step_id", f"{task_dir.name}-span")),
                        "name": f"{payload.get('task_id', task_dir.name)}:{payload.get('phase', 'unknown')}",
                        "start_time": timestamp.isoformat(),
                        "duration_ms": latency_ms,
                        "attributes": {
                            "meta_harness.run_id": payload.get("run_id", run_dir.name),
                            "meta_harness.task_id": payload.get("task_id", task_dir.name),
                            "meta_harness.session_ref": payload.get("session_ref"),
                            "meta_harness.candidate_id": payload.get("candidate_id"),
                            "meta_harness.status": payload.get("status"),
                            "meta_harness.step_id": payload.get("step_id"),
                            "meta_harness.event_kind": classify_trace_event_kind(payload),
                            "meta_harness.artifact_refs": payload.get("artifact_refs"),
                            "meta_harness.retrieval_refs": payload.get("retrieval_refs"),
                            "tool.name": payload.get("tool_name"),
                            "gen_ai.prompt.ref": payload.get("prompt_ref"),
                            "gen_ai.request.model": payload.get("model"),
                            "gen_ai.usage.total_tokens": (
                                (payload.get("token_usage") or {}).get("total")
                                if isinstance(payload.get("token_usage"), dict)
                                else None
                            ),
                        },
                    }
                )

    return {
        "run_id": str(metadata.get("run_id", run_dir.name)),
        "resource": {
            "attributes": {
                "service.name": "meta-harness",
                "meta_harness.profile": metadata.get("profile"),
                "meta_harness.project": metadata.get("project"),
                "meta_harness.candidate_id": metadata.get("candidate_id"),
            }
        },
        "spans": spans,
    }


def export_run_trace_phoenix_json(run_dir: Path) -> dict[str, Any]:
    otel_payload = export_run_trace_otel_json(run_dir)
    resource = otel_payload.get("resource", {}).get("attributes", {})
    return {
        "project_name": f"meta-harness/{resource.get('meta_harness.project', 'unknown')}",
        "traces": [
            {
                "trace_id": otel_payload["run_id"],
                "spans": otel_payload["spans"],
            }
        ],
    }


def export_run_trace_langfuse_json(run_dir: Path) -> dict[str, Any]:
    otel_payload = export_run_trace_otel_json(run_dir)
    resource = otel_payload.get("resource", {}).get("attributes", {})
    observations = []
    for span in otel_payload["spans"]:
        observations.append(
            {
                "id": span["span_id"],
                "trace_id": span["trace_id"],
                "name": span["name"],
                "start_time": span["start_time"],
                "duration_ms": span["duration_ms"],
                "metadata": {
                    "tool_name": span["attributes"].get("tool.name"),
                    "task_id": span["attributes"].get("meta_harness.task_id"),
                    "candidate_id": span["attributes"].get(
                        "meta_harness.candidate_id"
                    ),
                    "status": span["attributes"].get("meta_harness.status"),
                },
            }
        )
    return {
        "trace": {
            "id": otel_payload["run_id"],
            "name": f"meta-harness:{resource.get('meta_harness.project', 'unknown')}",
            "metadata": resource,
        },
        "observations": observations,
    }
