from __future__ import annotations

from typing import Any


def _normalize_string(value: Any) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None

def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        normalized = value.strip()
        return [normalized] if normalized else []
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        normalized = _normalize_string(item)
        if normalized is not None:
            result.append(normalized)
    return result

def _is_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return bool(value)
    return True

def _deep_lookup_first(payload: Any, key: str) -> Any:
    stack: list[Any] = [payload]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            marker = id(current)
            if marker in seen:
                continue
            seen.add(marker)
            if key in current and _is_meaningful_value(current[key]):
                return current[key]
            for nested_key in (
                "candidate_harness",
                "harness",
                "outer_loop",
                "provenance",
                "runtime",
                "binding",
                "expectations",
                "task",
            ):
                nested = current.get(nested_key)
                if isinstance(nested, (dict, list)):
                    stack.append(nested)
        elif isinstance(current, list):
            for item in reversed(current):
                if isinstance(item, (dict, list)):
                    stack.append(item)
    return None

def _candidate_harness_execution_context(
    *,
    task: dict[str, Any],
    effective_config: dict[str, Any],
    resolved_binding: dict[str, Any],
) -> dict[str, Any]:
    sources: list[dict[str, Any]] = [task]
    for candidate in (
        task.get("expectations"),
        task.get("binding"),
        resolved_binding,
        effective_config,
    ):
        if isinstance(candidate, dict):
            sources.append(candidate)

    candidate_harness_id = _normalize_string(
        _deep_lookup_first(sources, "candidate_harness_id")
    )
    binding_id = _normalize_string(_deep_lookup_first(sources, "binding_id"))
    if candidate_harness_id is None and isinstance(binding_id, str):
        if binding_id.startswith(("harness/", "candidate_harness/")):
            candidate_harness_id = binding_id

    proposal_id = _normalize_string(_deep_lookup_first(sources, "proposal_id"))
    iteration_id = _normalize_string(_deep_lookup_first(sources, "iteration_id"))

    wrapper_path = _normalize_string(_deep_lookup_first(sources, "wrapper_path"))
    if wrapper_path is None:
        command = resolved_binding.get("command")
        if isinstance(command, list):
            for item in command:
                normalized = _normalize_string(item)
                if normalized is not None and normalized.endswith(".py"):
                    wrapper_path = normalized
                    break

    source_artifacts = _normalize_string_list(
        _deep_lookup_first(sources, "source_artifacts")
    )
    if not source_artifacts and wrapper_path is not None:
        source_artifacts = [wrapper_path]

    upstream_provenance = _deep_lookup_first(sources, "provenance")
    provenance: dict[str, Any] = {}
    if isinstance(upstream_provenance, dict):
        provenance.update(upstream_provenance)

    provenance.update(
        {
            "task_id": str(task.get("task_id", "")),
            "binding_id": binding_id,
            "candidate_harness_id": candidate_harness_id,
            "proposal_id": proposal_id,
            "iteration_id": iteration_id,
            "wrapper_path": wrapper_path,
            "source_artifacts": list(source_artifacts),
        }
    )

    return {
        "candidate_harness_id": candidate_harness_id,
        "proposal_id": proposal_id,
        "iteration_id": iteration_id,
        "wrapper_path": wrapper_path,
        "source_artifacts": source_artifacts,
        "provenance": provenance,
    }

