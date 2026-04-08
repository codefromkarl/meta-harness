from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from meta_harness.candidates import create_candidate
from meta_harness.config_loader import load_effective_config, merge_dicts
from meta_harness.schemas import ClawBindingSpec, TaskMethodSpec, TransferPolicy


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_asset_path(root: Path, asset_id: str) -> Path:
    direct = root / f"{asset_id}.json"
    if direct.exists():
        return direct

    nested = root.joinpath(*asset_id.split("/")).with_suffix(".json")
    if nested.exists():
        return nested

    underscored = root / f"{asset_id.replace('/', '_')}.json"
    if underscored.exists():
        return underscored

    raise FileNotFoundError(f"asset '{asset_id}' not found under {root}")


def load_task_method(config_root: Path, method_id: str) -> TaskMethodSpec:
    path = _resolve_asset_path(config_root / "task_methods", method_id)
    return TaskMethodSpec.model_validate_json(path.read_text(encoding="utf-8"))


def load_claw_binding(config_root: Path, binding_id: str) -> ClawBindingSpec:
    path = _resolve_asset_path(config_root / "claw_bindings", binding_id)
    return ClawBindingSpec.model_validate_json(path.read_text(encoding="utf-8"))


def inspect_method_binding(
    *,
    config_root: Path,
    method_id: str,
    binding_id: str,
) -> dict[str, Any]:
    method = load_task_method(config_root, method_id)
    binding = load_claw_binding(config_root, binding_id)
    _validate_method_binding(method, binding)
    return {
        "method": method.model_dump(),
        "binding": binding.model_dump(),
    }


def plan_method_transfer(
    *,
    config_root: Path,
    method_id: str,
    source_binding_id: str,
    target_binding_id: str,
    method_patch: dict[str, Any] | None = None,
    binding_patch: dict[str, Any] | None = None,
    local_patch: dict[str, Any] | None = None,
    transfer_policy: TransferPolicy | None = None,
) -> dict[str, Any]:
    method = load_task_method(config_root, method_id)
    source_binding = load_claw_binding(config_root, source_binding_id)
    target_binding = load_claw_binding(config_root, target_binding_id)
    _validate_method_binding(method, source_binding)
    _validate_method_binding(method, target_binding)

    resolved_method_patch = merge_dicts(
        method.default_patch,
        method_patch or {},
    )
    resolved_binding_patch = merge_dicts(
        _binding_runtime_patch(target_binding),
        binding_patch or {},
    )
    resolved_local_patch = local_patch or {}

    effective_patch = merge_dicts(resolved_method_patch, resolved_binding_patch)
    effective_patch = merge_dicts(effective_patch, resolved_local_patch)

    transfer = transfer_policy or TransferPolicy(
        scope="portable_first",
        frozen_keys=list(method.portable_knobs),
        source_binding=source_binding_id,
        validated_targets=[target_binding_id],
    )

    return {
        "method_id": method.method_id,
        "primitive_id": method.primitive_id,
        "source_binding": source_binding.model_dump(),
        "target_binding": target_binding.model_dump(),
        "method_patch": resolved_method_patch,
        "binding_patch": resolved_binding_patch,
        "local_patch": resolved_local_patch,
        "effective_patch": effective_patch,
        "transfer": transfer.model_dump(),
    }


def create_transfer_candidate(
    *,
    config_root: Path,
    candidates_root: Path,
    profile_name: str,
    project_name: str,
    method_id: str,
    source_binding_id: str,
    target_binding_id: str,
    method_patch: dict[str, Any] | None = None,
    binding_patch: dict[str, Any] | None = None,
    local_patch: dict[str, Any] | None = None,
    proposal_overrides: dict[str, Any] | None = None,
    notes: str = "",
    reuse_existing: bool = True,
) -> str:
    plan = plan_method_transfer(
        config_root=config_root,
        method_id=method_id,
        source_binding_id=source_binding_id,
        target_binding_id=target_binding_id,
        method_patch=method_patch,
        binding_patch=binding_patch,
        local_patch=local_patch,
    )
    effective_config = load_effective_config(
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
    )
    effective_config = merge_dicts(effective_config, plan["effective_patch"])
    proposal = {
        "strategy": "method_transfer",
        "method_id": method_id,
        "primitive_id": plan["primitive_id"],
        "source_binding_id": source_binding_id,
        "target_binding_id": target_binding_id,
        "layers": {
            "method_patch": plan["method_patch"],
            "binding_patch": plan["binding_patch"],
            "local_patch": plan["local_patch"],
        },
        "transfer": plan["transfer"],
    }
    if proposal_overrides:
        proposal = merge_dicts(proposal, proposal_overrides)
    return create_candidate(
        candidates_root=candidates_root,
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
        effective_config_override=effective_config,
        notes=notes or f"method transfer: {method_id} -> {target_binding_id}",
        proposal=proposal,
        reuse_existing=reuse_existing,
    )


def _validate_method_binding(method: TaskMethodSpec, binding: ClawBindingSpec) -> None:
    if method.primitive_id != binding.primitive_id:
        raise ValueError(
            "method and binding primitive mismatch: "
            f"{method.method_id} expects '{method.primitive_id}', "
            f"binding '{binding.binding_id}' serves '{binding.primitive_id}'"
        )


def _binding_runtime_patch(binding: ClawBindingSpec) -> dict[str, Any]:
    runtime_binding = {
        "binding_id": binding.binding_id,
        "adapter_kind": binding.adapter_kind,
    }
    runtime_binding.update(binding.execution)
    return merge_dicts(
        {"runtime": {"binding": runtime_binding}},
        binding.binding_patch,
    )
