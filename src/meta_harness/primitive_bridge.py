from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from meta_harness.primitive_registry import load_registered_primitive_pack


@dataclass
class PrimitiveBridgeResult:
    artifact_refs: list[str] = field(default_factory=list)
    normalized_events: list[dict[str, Any]] = field(default_factory=list)


def resolve_binding_message(
    *,
    binding: dict[str, Any],
    phase: dict[str, Any],
    context: dict[str, Any],
    resolve_template: Callable[[Any, dict[str, Any]], Any],
) -> str:
    base_message = _resolve_base_message(
        binding=binding,
        phase=phase,
        context=context,
        resolve_template=resolve_template,
    )
    bridge_contract = _bridge_contract(binding=binding, context=context)
    if bridge_contract is None:
        return base_message
    return _augment_message_with_contract(
        base_message=base_message,
        bridge_contract=bridge_contract,
        context=context,
    )


def materialize_binding_outputs(
    *,
    binding: dict[str, Any],
    context: dict[str, Any],
    payload: dict[str, Any] | None,
    task_dir: Path,
    resolve_template: Callable[[Any, dict[str, Any]], Any],
) -> PrimitiveBridgeResult:
    bridge_contract = _bridge_contract(binding=binding, context=context)
    if bridge_contract is None:
        return PrimitiveBridgeResult()
    if payload is None:
        raise RuntimeError("primitive bridge requires binding payload JSON")

    reply_payload = _extract_reply_payload(payload)
    artifact_refs = _write_artifacts(
        task_dir=task_dir,
        reply_payload=reply_payload,
        bridge_contract=bridge_contract,
    )
    probe_artifact = _write_benchmark_probe(
        task_dir=task_dir,
        bridge_contract=bridge_contract,
        context=context,
        resolve_template=resolve_template,
    )
    if probe_artifact is not None:
        artifact_refs.append(probe_artifact)

    return PrimitiveBridgeResult(
        artifact_refs=artifact_refs,
        normalized_events=[
            {
                "phase": "bridge_normalization",
                "status": "completed",
            }
        ],
    )


def _resolve_base_message(
    *,
    binding: dict[str, Any],
    phase: dict[str, Any],
    context: dict[str, Any],
    resolve_template: Callable[[Any, dict[str, Any]], Any],
) -> str:
    for key in ("message", "message_template", "prompt", "prompt_template"):
        value = binding.get(key)
        if isinstance(value, str) and value:
            return str(resolve_template(value, context))
    for key in ("message", "prompt"):
        value = phase.get(key)
        if isinstance(value, str) and value:
            return str(resolve_template(value, context))
    raise RuntimeError("openclaw_agent binding requires binding.message or phase.message")


def _bridge_contract(
    *,
    binding: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any] | None:
    bridge_mode = binding.get("bridge_contract")
    if not bridge_mode:
        return None
    if bridge_mode != "primitive_output":
        raise RuntimeError(f"unsupported primitive bridge contract: {bridge_mode}")

    config_root = _config_root(binding)
    primitive_id = _primitive_id(context)
    primitive_pack = load_registered_primitive_pack(config_root, primitive_id)
    output_contract = primitive_pack.output_contract if isinstance(primitive_pack.output_contract, dict) else {}
    bridge_contract = output_contract.get("bridge")
    if not isinstance(bridge_contract, dict) or not bridge_contract:
        raise RuntimeError(
            f"primitive '{primitive_id}' does not define output_contract.bridge"
        )
    return bridge_contract


def _config_root(binding: dict[str, Any]) -> Path:
    configured = binding.get("bridge_config_root")
    if isinstance(configured, str) and configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "configs"


def _primitive_id(context: dict[str, Any]) -> str:
    task = context.get("task")
    if isinstance(task, dict):
        expectations = task.get("expectations")
        if isinstance(expectations, dict):
            primitive_id = expectations.get("primitive_id")
            if isinstance(primitive_id, str) and primitive_id:
                return primitive_id
        scenario = task.get("scenario")
        if isinstance(scenario, str) and scenario:
            return scenario
    raise RuntimeError("primitive bridge requires task primitive_id")


def _augment_message_with_contract(
    *,
    base_message: str,
    bridge_contract: dict[str, Any],
    context: dict[str, Any],
) -> str:
    response_fields = bridge_contract.get("response_fields")
    if not isinstance(response_fields, list) or not response_fields:
        return base_message

    schema_lines: list[str] = []
    for field in response_fields:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name") or "").strip()
        field_type = str(field.get("type") or "string").strip() or "string"
        if not name:
            continue
        if field_type == "object":
            nested_fields = _field_names_from_contract(field, context)
            nested_schema = ", ".join(f'"{item}": "<value>"' for item in nested_fields)
            schema_lines.append(f'"{name}": {{{nested_schema}}}')
        else:
            schema_lines.append(f'"{name}": "<{field_type}>"')

    schema_block = "{\n  " + ",\n  ".join(schema_lines) + "\n}"
    instructions = [
        base_message.strip(),
        "Return exactly one JSON object and no extra text.",
        "Use this reply schema:",
        schema_block,
    ]
    return "\n\n".join(item for item in instructions if item)


def _field_names_from_contract(field: dict[str, Any], context: dict[str, Any]) -> list[str]:
    configured = field.get("required_fields")
    if isinstance(configured, list):
        values = [str(item) for item in configured if str(item)]
        if values:
            return values

    from_task = field.get("required_fields_from")
    if from_task == "task.expectations.required_fields":
        task = context.get("task")
        if isinstance(task, dict):
            expectations = task.get("expectations")
            if isinstance(expectations, dict):
                values = expectations.get("required_fields")
                if isinstance(values, list):
                    normalized = [str(item) for item in values if str(item)]
                    if normalized:
                        return normalized
    return ["value"]


def _extract_reply_payload(payload: dict[str, Any]) -> dict[str, Any]:
    reply = payload.get("reply")
    if isinstance(reply, dict):
        return reply
    if isinstance(reply, str) and reply.strip():
        parsed = json.loads(reply)
        if isinstance(parsed, dict):
            return parsed
    raise RuntimeError("primitive bridge requires binding payload reply object")


def _write_artifacts(
    *,
    task_dir: Path,
    reply_payload: dict[str, Any],
    bridge_contract: dict[str, Any],
) -> list[str]:
    writes = bridge_contract.get("artifact_writes")
    if not isinstance(writes, list) or not writes:
        raise RuntimeError("primitive bridge requires artifact_writes")

    artifact_refs: list[str] = []
    task_dir.mkdir(parents=True, exist_ok=True)
    for write in writes:
        if not isinstance(write, dict):
            continue
        artifact_path = str(write.get("path") or "").strip()
        payload_path = str(write.get("payload_path") or "").strip()
        write_format = str(write.get("format") or "text").strip() or "text"
        if not artifact_path or not payload_path:
            continue
        value = _lookup_payload_value(reply_payload, payload_path)
        if value is None:
            raise RuntimeError(f"primitive bridge missing payload path '{payload_path}'")

        destination = task_dir / artifact_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if write_format == "json":
            destination.write_text(json.dumps(value, indent=2), encoding="utf-8")
        elif write_format == "text":
            text_value = value if isinstance(value, str) else json.dumps(value, indent=2)
            destination.write_text(text_value, encoding="utf-8")
        else:
            raise RuntimeError(f"unsupported bridge artifact format: {write_format}")
        artifact_refs.append(artifact_path)
    return artifact_refs


def _lookup_payload_value(payload: Any, dotted_path: str) -> Any:
    current = payload
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _write_benchmark_probe(
    *,
    task_dir: Path,
    bridge_contract: dict[str, Any],
    context: dict[str, Any],
    resolve_template: Callable[[Any, dict[str, Any]], Any],
) -> str | None:
    benchmark_probe = bridge_contract.get("benchmark_probe")
    payload = {"fingerprints": {}, "probes": {}}
    if isinstance(benchmark_probe, dict):
        fingerprints = benchmark_probe.get("fingerprints")
        if isinstance(fingerprints, dict):
            resolved = resolve_template(fingerprints, context)
            if isinstance(resolved, dict):
                payload["fingerprints"] = {
                    str(key): str(value)
                    for key, value in resolved.items()
                    if value is not None and "${" not in str(value)
                }
        probes = benchmark_probe.get("probes")
        if isinstance(probes, dict):
            resolved = resolve_template(probes, context)
            if isinstance(resolved, dict):
                for key, value in resolved.items():
                    try:
                        payload["probes"][str(key)] = float(value)
                    except (TypeError, ValueError):
                        continue

    path = task_dir / "benchmark_probe.stdout.txt"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path.name
