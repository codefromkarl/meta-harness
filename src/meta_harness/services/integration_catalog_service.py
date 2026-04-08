from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError


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

def test_integration(config_root: Path, name: str) -> dict[str, Any]:
    config = load_integration_config(config_root, name)
    endpoint = str(config.get("healthcheck_endpoint") or config.get("endpoint") or "")
    if not endpoint:
        raise ValueError(f"integration '{name}' has no endpoint configured")
    result = _post_json(
        url=endpoint,
        payload={"type": "health_check", "service": "meta-harness", "integration": name},
        headers={
            str(key): str(value)
            for key, value in dict(config.get("headers") or {}).items()
        },
        timeout_sec=float(config.get("timeout_sec", 5.0) or 5.0),
    )
    return {
        "name": name,
        "status_code": result["status_code"],
        "ok": 200 <= int(result["status_code"]) < 300,
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
    result = _post_json(
        url=endpoint,
        payload=payload,
        headers={
            str(key): str(value)
            for key, value in dict(config.get("headers") or {}).items()
        },
        timeout_sec=float(config.get("timeout_sec", 5.0) or 5.0),
    )
    return {
        "name": str(config.get("name", name)),
        "kind": config.get("kind"),
        "format": config.get("format"),
        "endpoint": endpoint,
        "status_code": result["status_code"],
        "response": result.get("body"),
    }

