from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _gate_policies_root(config_root: Path) -> Path:
    return config_root / "gate_policies"


def list_gate_policies(config_root: Path) -> list[dict[str, Any]]:
    root = _gate_policies_root(config_root)
    if not root.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        items.append(
            {
                "policy_id": str(payload.get("policy_id", path.stem)),
                "policy_type": payload.get("policy_type"),
                "path": str(path),
                "enabled": payload.get("enabled", True),
            }
        )
    return items


def load_gate_policy(config_root: Path, policy_id: str) -> dict[str, Any]:
    root = _gate_policies_root(config_root)
    for path in sorted(root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("policy_id", path.stem) == policy_id:
            return payload
    raise FileNotFoundError(f"gate policy '{policy_id}' not found")
