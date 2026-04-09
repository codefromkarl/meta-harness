from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meta_harness.schemas import CandidateMetadata
from meta_harness.services.trace_service import classify_trace_event_kind


def _parse_timestamp(raw: Any) -> datetime:
    if not raw:
        return datetime.now(UTC)
    text = str(raw).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(UTC)


def _resolve_candidates_root(run_dir: Path, candidates_root: Path | None) -> Path | None:
    if candidates_root is not None:
        return candidates_root
    default_root = run_dir.parent.parent / "candidates"
    return default_root if default_root.exists() else None


def _load_candidate_lineage(
    *,
    run_dir: Path,
    candidate_id: str | None,
    candidates_root: Path | None,
) -> dict[str, Any] | None:
    if not candidate_id:
        return None
    resolved_candidates_root = _resolve_candidates_root(run_dir, candidates_root)
    if resolved_candidates_root is None:
        return None
    candidate_path = resolved_candidates_root / str(candidate_id) / "candidate.json"
    if not candidate_path.exists():
        return None
    try:
        metadata = CandidateMetadata.model_validate_json(
            candidate_path.read_text(encoding="utf-8")
        )
    except Exception:
        return None
    return metadata.lineage.model_dump(mode="json")


def _lineage_resource_attributes(candidate_lineage: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(candidate_lineage, dict):
        return {}
    return {
        f"meta_harness.lineage.{key}": value
        for key, value in candidate_lineage.items()
    }


def export_run_trace_otel_json(
    run_dir: Path,
    *,
    candidates_root: Path | None = None,
) -> dict[str, Any]:
    metadata_path = run_dir / "run_metadata.json"
    metadata = (
        json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata_path.exists()
        else {}
    )
    candidate_lineage = _load_candidate_lineage(
        run_dir=run_dir,
        candidate_id=(
            str(metadata.get("candidate_id"))
            if metadata.get("candidate_id") is not None
            else None
        ),
        candidates_root=candidates_root,
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
                "meta_harness.candidate_lineage": candidate_lineage,
                **_lineage_resource_attributes(candidate_lineage),
            }
        },
        "spans": spans,
    }


def export_run_trace_phoenix_json(
    run_dir: Path,
    *,
    candidates_root: Path | None = None,
) -> dict[str, Any]:
    otel_payload = export_run_trace_otel_json(run_dir, candidates_root=candidates_root)
    resource = otel_payload.get("resource", {}).get("attributes", {})
    trace_metadata = {
        "candidate_lineage": resource.get("meta_harness.candidate_lineage"),
        **resource,
    }
    return {
        "project_name": f"meta-harness/{resource.get('meta_harness.project', 'unknown')}",
        "traces": [
            {
                "trace_id": otel_payload["run_id"],
                "metadata": trace_metadata,
                "spans": otel_payload["spans"],
            }
        ],
    }


def export_run_trace_langfuse_json(
    run_dir: Path,
    *,
    candidates_root: Path | None = None,
) -> dict[str, Any]:
    otel_payload = export_run_trace_otel_json(run_dir, candidates_root=candidates_root)
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


def build_otlp_transport_request(
    *,
    payload: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    endpoint = str(config.get("endpoint") or "").rstrip("/")
    resolved_endpoint = (
        endpoint
        if endpoint.endswith("/v1/traces")
        else f"{endpoint}/v1/traces"
    )
    headers = {
        "Content-Type": "application/json",
        **{
            str(key): str(value)
            for key, value in dict(config.get("headers") or {}).items()
        },
    }
    return {
        "kind": "otlp_http",
        "signal": "traces",
        "method": "POST",
        "endpoint": resolved_endpoint,
        "headers": headers,
        "timeout_sec": float(config.get("timeout_sec", 5.0) or 5.0),
        "retry_limit": max(0, int(config.get("retry_limit", 0) or 0)),
        "retry_backoff_sec": max(
            0.0,
            float(config.get("retry_backoff_sec", 0.0) or 0.0),
        ),
        "body": payload,
    }


def build_phoenix_api_request(
    *,
    payload: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        **{
            str(key): str(value)
            for key, value in dict(config.get("headers") or {}).items()
        },
    }
    traces = payload.get("traces")
    trace_count = len(traces) if isinstance(traces, list) else 0
    return {
        "kind": "phoenix",
        "method": "POST",
        "endpoint": str(config.get("endpoint") or ""),
        "headers": headers,
        "timeout_sec": float(config.get("timeout_sec", 5.0) or 5.0),
        "retry_limit": max(0, int(config.get("retry_limit", 0) or 0)),
        "retry_backoff_sec": max(0.0, float(config.get("retry_backoff_sec", 0.0) or 0.0)),
        "project_name": str(payload.get("project_name") or ""),
        "trace_count": trace_count,
        "body": payload,
    }


def build_langfuse_api_request(
    *,
    payload: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        **{
            str(key): str(value)
            for key, value in dict(config.get("headers") or {}).items()
        },
    }
    observations = payload.get("observations")
    observation_count = len(observations) if isinstance(observations, list) else 0
    trace = payload.get("trace") if isinstance(payload.get("trace"), dict) else {}
    return {
        "kind": "langfuse",
        "method": "POST",
        "endpoint": str(config.get("endpoint") or ""),
        "headers": headers,
        "timeout_sec": float(config.get("timeout_sec", 5.0) or 5.0),
        "retry_limit": max(0, int(config.get("retry_limit", 0) or 0)),
        "retry_backoff_sec": max(0.0, float(config.get("retry_backoff_sec", 0.0) or 0.0)),
        "trace_id": str(trace.get("id") or ""),
        "trace_name": str(trace.get("name") or ""),
        "observation_count": observation_count,
        "body": payload,
    }
