from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


_TEMPLATE_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _build_template_context(
    run_dir: Path,
    *,
    effective_config: dict[str, Any] | None = None,
    execution_context: dict[str, str] | None = None,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "run_dir": str(run_dir.resolve()),
        "workspace_dir": str(run_dir.resolve()),
        "source_repo": str(run_dir.resolve()),
        "meta_harness": {
            "repo_root": str(Path(__file__).resolve().parents[2]),
            "scripts_dir": str((Path(__file__).resolve().parents[2] / "scripts").resolve()),
        },
    }
    if effective_config:
        context.update(effective_config)
    if execution_context is not None:
        context.update(execution_context)
    _normalize_template_paths(context)
    return context


def _lookup_template_value(variables: dict[str, Any], key: str) -> Any:
    if key.startswith("env."):
        return os.environ.get(key[len("env.") :])
    current: Any = variables
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _resolve_template(value: Any, variables: dict[str, Any]) -> Any:
    if isinstance(value, str):
        resolved_value = value
        for _ in range(8):
            updated = _TEMPLATE_PATTERN.sub(
                lambda match: str(
                    _lookup_template_value(variables, match.group(1))
                    if _lookup_template_value(variables, match.group(1)) is not None
                    else match.group(0)
                ),
                resolved_value,
            )
            if updated == resolved_value:
                break
            resolved_value = updated
        return resolved_value
    if isinstance(value, list):
        return [_resolve_template(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_template(item, variables) for key, item in value.items()}
    return value


def _normalize_template_paths(context: dict[str, Any]) -> None:
    for key in ("run_dir", "workspace_dir", "source_repo"):
        value = context.get(key)
        if isinstance(value, str):
            context[key] = str(Path(value).expanduser().resolve())
