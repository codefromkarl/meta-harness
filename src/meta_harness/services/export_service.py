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
    run_id: str,
    export_format: str = "otel-json",
) -> dict[str, Any]:
    run_dir = runs_root / run_id
    if export_format == "otel-json":
        return export_run_trace_otel_json(run_dir)
    if export_format == "phoenix-json":
        return export_run_trace_phoenix_json(run_dir)
    if export_format == "langfuse-json":
        return export_run_trace_langfuse_json(run_dir)
    raise ValueError("format must be one of: otel-json, phoenix-json, langfuse-json")


def export_run_trace_to_path(
    *,
    runs_root: Path,
    run_id: str,
    output_path: Path,
    export_format: str = "otel-json",
) -> dict[str, Any]:
    payload = build_trace_export_payload(
        runs_root=runs_root,
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


def export_run_trace_to_integration(
    *,
    runs_root: Path,
    run_id: str,
    config_root: Path,
    integration_name: str,
    export_format: str = "otel-json",
) -> dict[str, Any]:
    payload = build_trace_export_payload(
        runs_root=runs_root,
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
    }


def export_run_to_named_integration(
    *,
    runs_root: Path,
    run_id: str,
    config_root: Path,
    integration_name: str,
    export_format: str | None = None,
) -> dict[str, Any]:
    config = load_integration_config(config_root, integration_name)
    resolved_format = export_format or infer_integration_export_format(config)
    return export_run_trace_to_integration(
        runs_root=runs_root,
        run_id=run_id,
        config_root=config_root,
        integration_name=integration_name,
        export_format=resolved_format,
    )
