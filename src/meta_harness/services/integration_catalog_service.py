from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError

from meta_harness.exporters import (
    build_langfuse_api_request,
    build_otlp_transport_request,
    build_phoenix_api_request,
)


def _integrations_root(config_root: Path) -> Path:
    return config_root / "integrations"

def list_integrations(config_root: Path) -> list[dict[str, Any]]:
    root = _integrations_root(config_root)
    if not root.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        items.append(
            {
                "name": str(payload.get("name", path.stem)),
                "kind": payload.get("kind"),
                "format": payload.get("format"),
                "default_format": infer_integration_export_format(payload),
                "endpoint": payload.get("endpoint"),
                "configured": bool(payload.get("endpoint")),
            }
        )
    return items

def load_integration_config(config_root: Path, name: str) -> dict[str, Any]:
    root = _integrations_root(config_root)
    path = root / f"{name}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    for candidate in sorted(root.glob("*.json")):
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        if payload.get("name") == name:
            return payload
    raise FileNotFoundError(f"integration '{name}' not found")

def infer_integration_export_format(config: dict[str, Any]) -> str:
    kind = str(config.get("kind") or "").lower()
    configured = config.get("format")
    if isinstance(configured, str) and configured:
        return configured
    if kind == "phoenix":
        return "phoenix-json"
    if kind == "langfuse":
        return "langfuse-json"
    return "otel-json"

def _post_json(
    *,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout_sec: float = 5.0,
) -> dict[str, Any]:
    encoded = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=encoded,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout_sec) as response:
            body = response.read().decode("utf-8")
            return {
                "status_code": response.getcode(),
                "body": json.loads(body) if body else None,
            }
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        return {
            "status_code": exc.code,
            "body": json.loads(body) if body else None,
        }
    except URLError as exc:
        raise ConnectionError(str(exc.reason)) from exc


def _retryable_status_codes(config: dict[str, Any]) -> set[int]:
    configured = config.get("retry_status_codes")
    if isinstance(configured, list) and configured:
        return {
            int(code)
            for code in configured
            if isinstance(code, (int, float, str)) and str(code).strip()
        }
    return {408, 429, 500, 502, 503, 504}


def _classify_transport_result(
    *,
    status_code: int | None,
    attempt_count: int,
    retryable_statuses: set[int],
    error: str | None = None,
) -> dict[str, Any]:
    if error is not None:
        return {
            "ok": False,
            "failure_kind": "connection_error",
            "retryable": True,
            "retry_exhausted": True,
            "error": error,
        }

    assert status_code is not None
    ok = 200 <= status_code < 300
    retryable = status_code in retryable_statuses
    failure_kind: str | None = None
    if not ok:
        failure_kind = "retryable_http" if retryable else "remote_rejected"
    return {
        "ok": ok,
        "failure_kind": failure_kind,
        "retryable": retryable,
        "retry_exhausted": bool(not ok and retryable and attempt_count >= 1),
        "error": None,
    }


def _post_json_with_retry(
    *,
    transport_request: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    retry_limit = max(
        0,
        int(transport_request.get("retry_limit", config.get("retry_limit", 0)) or 0),
    )
    retry_backoff_sec = max(
        0.0,
        float(
            transport_request.get(
                "retry_backoff_sec",
                config.get("retry_backoff_sec", 0.0),
            )
            or 0.0
        ),
    )
    timeout_sec = float(
        transport_request.get("timeout_sec", config.get("timeout_sec", 5.0)) or 5.0
    )
    retryable_statuses = _retryable_status_codes(config)

    attempt_count = 0
    while True:
        attempt_count += 1
        try:
            result = _post_json(
                url=str(transport_request.get("endpoint") or ""),
                payload=(
                    transport_request.get("body")
                    if isinstance(transport_request.get("body"), dict)
                    else {}
                ),
                headers={
                    str(key): str(value)
                    for key, value in dict(transport_request.get("headers") or {}).items()
                },
                timeout_sec=timeout_sec,
            )
        except ConnectionError as exc:
            if attempt_count > retry_limit:
                return {
                    "status_code": None,
                    "body": None,
                    "attempt_count": attempt_count,
                    "error": str(exc),
                }
            if retry_backoff_sec > 0:
                time.sleep(retry_backoff_sec)
            continue

        status_code = int(result["status_code"])
        if status_code in retryable_statuses and attempt_count <= retry_limit:
            if retry_backoff_sec > 0:
                time.sleep(retry_backoff_sec)
            continue

        return {
            **result,
            "attempt_count": attempt_count,
        }


def _build_transport_request(
    *,
    config: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    kind = str(config.get("kind") or "").lower()
    if kind == "otlp_http":
        return build_otlp_transport_request(payload=payload, config=config)
    if kind == "phoenix":
        return build_phoenix_api_request(payload=payload, config=config)
    if kind == "langfuse":
        return build_langfuse_api_request(payload=payload, config=config)
    return {
        "kind": kind or "http_json",
        "method": "POST",
        "endpoint": str(config.get("endpoint") or ""),
        "headers": {
            "Content-Type": "application/json",
            **{
                str(key): str(value)
                for key, value in dict(config.get("headers") or {}).items()
            },
        },
        "timeout_sec": float(config.get("timeout_sec", 5.0) or 5.0),
        "retry_limit": max(0, int(config.get("retry_limit", 0) or 0)),
        "retry_backoff_sec": max(
            0.0,
            float(config.get("retry_backoff_sec", 0.0) or 0.0),
        ),
        "body": payload,
    }

def test_integration(config_root: Path, name: str) -> dict[str, Any]:
    config = load_integration_config(config_root, name)
    endpoint = str(config.get("healthcheck_endpoint") or config.get("endpoint") or "")
    if not endpoint:
        raise ValueError(f"integration '{name}' has no endpoint configured")
    transport_request = _build_transport_request(
        config={**config, "kind": "http_json", "endpoint": endpoint},
        payload={
            "type": "health_check",
            "service": "meta-harness",
            "integration": name,
        },
    )
    result = _post_json_with_retry(
        transport_request=transport_request,
        config=config,
    )
    return {
        "name": name,
        "status_code": result["status_code"],
        "attempt_count": result.get("attempt_count", 1),
        **_classify_transport_result(
            status_code=(
                int(result["status_code"]) if result.get("status_code") is not None else None
            ),
            attempt_count=int(result.get("attempt_count", 1)),
            retryable_statuses=_retryable_status_codes(config),
            error=result.get("error"),
        ),
        "response": result.get("body"),
    }

def export_payload_to_integration(
    *,
    config_root: Path,
    name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    config = load_integration_config(config_root, name)
    endpoint = str(config.get("endpoint") or "")
    if not endpoint:
        raise ValueError(f"integration '{name}' has no endpoint configured")
    transport_request = _build_transport_request(config=config, payload=payload)
    result = _post_json_with_retry(
        transport_request=transport_request,
        config=config,
    )
    return {
        "name": str(config.get("name", name)),
        "kind": config.get("kind"),
        "format": config.get("format"),
        "endpoint": str(transport_request.get("endpoint") or endpoint),
        "status_code": result["status_code"],
        "attempt_count": result.get("attempt_count", 1),
        **_classify_transport_result(
            status_code=(
                int(result["status_code"]) if result.get("status_code") is not None else None
            ),
            attempt_count=int(result.get("attempt_count", 1)),
            retryable_statuses=_retryable_status_codes(config),
            error=result.get("error"),
        ),
        "response": result.get("body"),
        "phoenix_api_request": (
            transport_request if str(config.get("kind") or "").lower() == "phoenix" else None
        ),
        "langfuse_api_request": (
            transport_request if str(config.get("kind") or "").lower() == "langfuse" else None
        ),
        "otlp_transport_request": (
            transport_request if str(config.get("kind") or "").lower() == "otlp_http" else None
        ),
    }
