from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from meta_harness.exporters import (
    export_run_trace_langfuse_json,
    export_run_trace_otel_json,
    export_run_trace_phoenix_json,
)
from meta_harness.services.integration_catalog_service import (
    export_payload_to_integration,
    infer_integration_export_format,
    load_integration_config,
)


def build_trace_export_payload(
    *,
    runs_root: Path,
    candidates_root: Path | None = None,
    run_id: str,
    export_format: str = "otel-json",
) -> dict[str, Any]:
    run_dir = runs_root / run_id
    if export_format == "otel-json":
        return export_run_trace_otel_json(run_dir, candidates_root=candidates_root)
    if export_format == "phoenix-json":
        return export_run_trace_phoenix_json(run_dir, candidates_root=candidates_root)
    if export_format == "langfuse-json":
        return export_run_trace_langfuse_json(run_dir, candidates_root=candidates_root)
    raise ValueError("format must be one of: otel-json, phoenix-json, langfuse-json")


def export_run_trace_to_path(
    *,
    runs_root: Path,
    candidates_root: Path | None = None,
    run_id: str,
    output_path: Path,
    export_format: str = "otel-json",
) -> dict[str, Any]:
    payload = build_trace_export_payload(
        runs_root=runs_root,
        candidates_root=candidates_root,
        run_id=run_id,
        export_format=export_format,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {
        "run_id": run_id,
        "destination": "download",
        "output_path": str(output_path),
        "format": export_format,
    }


def _integration_export_artifact_path(
    *,
    reports_root: Path,
    integration_name: str,
    run_id: str,
) -> Path:
    return reports_root / "exports" / "integrations" / integration_name / f"{run_id}.json"


def _extract_candidate_lineage(payload: dict[str, Any]) -> dict[str, Any] | None:
    resource = payload.get("resource")
    if isinstance(resource, dict):
        attributes = resource.get("attributes")
        if isinstance(attributes, dict):
            lineage = attributes.get("meta_harness.candidate_lineage")
            if isinstance(lineage, dict):
                return lineage

    traces = payload.get("traces")
    if isinstance(traces, list):
        for trace in traces:
            if not isinstance(trace, dict):
                continue
            metadata = trace.get("metadata")
            if not isinstance(metadata, dict):
                continue
            lineage = metadata.get("candidate_lineage")
            if isinstance(lineage, dict):
                return lineage
            lineage = metadata.get("meta_harness.candidate_lineage")
            if isinstance(lineage, dict):
                return lineage

    trace = payload.get("trace")
    if isinstance(trace, dict):
        metadata = trace.get("metadata")
        if isinstance(metadata, dict):
            lineage = metadata.get("candidate_lineage")
            if isinstance(lineage, dict):
                return lineage
            lineage = metadata.get("meta_harness.candidate_lineage")
            if isinstance(lineage, dict):
                return lineage

    return None


def _persist_integration_export_artifact(
    *,
    reports_root: Path,
    run_id: str,
    export_format: str,
    integration_name: str,
    integration_payload: dict[str, Any],
    export_payload: dict[str, Any],
) -> str:
    artifact_path = _integration_export_artifact_path(
        reports_root=reports_root,
        integration_name=integration_name,
        run_id=run_id,
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact = {
        "run_id": run_id,
        "destination": "integration",
        "format": export_format,
        "candidate_lineage": _extract_candidate_lineage(export_payload),
        "phoenix_api_request": integration_payload.get("phoenix_api_request"),
        "langfuse_api_request": integration_payload.get("langfuse_api_request"),
        "otlp_transport_request": integration_payload.get("otlp_transport_request"),
        "integration": integration_payload,
    }
    artifact_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    return str(artifact_path.relative_to(reports_root.parent))


def export_run_trace_to_integration(
    *,
    runs_root: Path,
    candidates_root: Path | None = None,
    run_id: str,
    config_root: Path,
    integration_name: str,
    export_format: str = "otel-json",
    reports_root: Path | None = None,
) -> dict[str, Any]:
    payload = build_trace_export_payload(
        runs_root=runs_root,
        candidates_root=candidates_root,
        run_id=run_id,
        export_format=export_format,
    )
    integration = export_payload_to_integration(
        config_root=config_root,
        name=integration_name,
        payload=payload,
    )
    return {
        "run_id": run_id,
        "destination": "integration",
        "format": export_format,
        "integration": integration,
        "artifact_path": (
            _persist_integration_export_artifact(
                reports_root=reports_root,
                run_id=run_id,
                export_format=export_format,
                integration_name=integration_name,
                integration_payload=integration,
                export_payload=payload,
            )
            if reports_root is not None
            else None
        ),
    }


def export_run_to_named_integration(
    *,
    runs_root: Path,
    candidates_root: Path | None = None,
    run_id: str,
    config_root: Path,
    integration_name: str,
    export_format: str | None = None,
    reports_root: Path | None = None,
) -> dict[str, Any]:
    config = load_integration_config(config_root, integration_name)
    resolved_format = export_format or infer_integration_export_format(config)
    return export_run_trace_to_integration(
        runs_root=runs_root,
        candidates_root=candidates_root,
        run_id=run_id,
        config_root=config_root,
        integration_name=integration_name,
        export_format=resolved_format,
        reports_root=reports_root,
    )
