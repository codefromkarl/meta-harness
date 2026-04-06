from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    return _deep_merge(base, override)


def load_effective_config(
    config_root: Path,
    profile_name: str,
    project_name: str | None = None,
) -> dict[str, Any]:
    platform_config = _read_json(config_root / "platform.json")
    profile_config = _read_json(config_root / "profiles" / f"{profile_name}.json")

    effective = _deep_merge(platform_config, profile_config.get("defaults", {}))

    if project_name:
        project_config = _read_json(config_root / "projects" / f"{project_name}.json")
        if project_config.get("workflow") not in (None, profile_name):
            raise ValueError(
                f"project '{project_name}' targets workflow "
                f"'{project_config.get('workflow')}', not '{profile_name}'"
            )
        effective = _deep_merge(effective, project_config.get("overrides", {}))

    return effective
