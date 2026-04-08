from __future__ import annotations

import re
from pathlib import Path

from meta_harness.integration_schemas import IntegrationIntent

_PATH_PATTERN = re.compile(r"(/[^\s]+)")
_PRIMITIVE_PATTERNS = (
    re.compile(r"适配到\s+([A-Za-z0-9_./-]+)"),
    re.compile(r"for\s+([A-Za-z0-9_./-]+)"),
    re.compile(r"to\s+([A-Za-z0-9_./-]+)"),
)


def build_integration_intent(
    *,
    intent_text: str | None = None,
    target_project_path: str | Path | None = None,
    primitive_id: str | None = None,
    workflow_paths: list[str | Path] | None = None,
    user_goal: str = "",
    preferred_adapter_kind: str | None = None,
    allow_wrapper_generation: bool = True,
    allow_code_inspection: bool = True,
) -> IntegrationIntent:
    normalized_workflows = _normalize_paths(workflow_paths or [])
    normalized_project = _resolve_target_project_path(
        target_project_path,
        intent_text,
        normalized_workflows,
    )
    normalized_primitive = primitive_id or _infer_primitive_id(intent_text)
    return IntegrationIntent(
        target_project_path=str(normalized_project),
        primitive_id=normalized_primitive,
        workflow_files=normalized_workflows,
        user_goal=user_goal or (intent_text or ""),
        preferred_adapter_kind=preferred_adapter_kind,
        allow_wrapper_generation=allow_wrapper_generation,
        allow_code_inspection=allow_code_inspection,
    )


def _resolve_target_project_path(
    target_project_path: str | Path | None,
    intent_text: str | None,
    normalized_workflows: list[str],
) -> Path:
    if target_project_path is not None:
        return Path(target_project_path).expanduser().resolve()
    inferred = _infer_path_from_text(intent_text or "")
    if inferred is None and normalized_workflows:
        inferred = Path(normalized_workflows[0]).resolve().parent
    if inferred is None:
        raise ValueError("target project path is required")
    return inferred


def _infer_path_from_text(intent_text: str) -> Path | None:
    for match in _PATH_PATTERN.findall(intent_text):
        candidate = Path(match).expanduser()
        suffix = candidate.suffix.lower()
        if suffix in {".yaml", ".yml", ".json"}:
            candidate = candidate.parent
        return candidate.resolve()
    return None


def _infer_primitive_id(intent_text: str | None) -> str | None:
    if not intent_text:
        return None
    for pattern in _PRIMITIVE_PATTERNS:
        matched = pattern.search(intent_text)
        if matched:
            value = matched.group(1).strip().strip(",.;")
            if value:
                return value
    return None


def _normalize_paths(paths: list[str | Path]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for path in paths:
        value = str(Path(path).expanduser().resolve())
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized
