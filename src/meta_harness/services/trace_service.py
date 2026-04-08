from __future__ import annotations

from collections import Counter
from typing import Any


def classify_trace_event_kind(event: dict[str, Any]) -> str:
    phase = str(event.get("phase") or "")
    if event.get("tool_name") or phase in {"tool_call", "command", "browser"}:
        return "tool"
    if event.get("retrieval_refs") or "retriev" in phase or "search" in phase:
        return "retrieval"
    if event.get("model") or event.get("prompt_ref") or phase in {
        "prompt",
        "assistant_reply",
        "analysis",
    }:
        return "model"
    if event.get("artifact_refs") or "artifact" in phase:
        return "artifact"
    return "phase"


def grade_trace_events(
    *,
    run_id: str,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    failure_count = 0
    total_latency_ms = 0
    issues: list[dict[str, str]] = []
    session_refs: set[str] = set()

    for event in events:
        counts[classify_trace_event_kind(event)] += 1
        if str(event.get("status") or "") == "failed":
            failure_count += 1
        session_ref = event.get("session_ref")
        if isinstance(session_ref, str) and session_ref:
            session_refs.add(session_ref)
        latency_ms = event.get("latency_ms")
        if latency_ms is not None:
            total_latency_ms += int(latency_ms)

    if failure_count:
        issues.append(
            {
                "code": "trace.has_failures",
                "message": f"trace contains {failure_count} failed events",
            }
        )
    for missing_kind in ("model", "retrieval", "tool"):
        if counts.get(missing_kind, 0) == 0:
            issues.append(
                {
                    "code": f"trace.missing_{missing_kind}",
                    "message": f"trace has no {missing_kind} events",
                }
            )
    if events and not session_refs:
        issues.append(
            {
                "code": "trace.missing_session_ref",
                "message": "trace has no session_ref values",
            }
        )

    return {
        "run_id": run_id,
        "event_count": len(events),
        "failure_count": failure_count,
        "session_count": len(session_refs),
        "event_kind_counts": dict(sorted(counts.items())),
        "latency_ms": total_latency_ms,
        "issues": issues,
    }
