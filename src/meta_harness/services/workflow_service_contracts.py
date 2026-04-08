from __future__ import annotations

from pathlib import Path
from typing import Any

from meta_harness.config_loader import load_effective_config
from meta_harness.workflow_compiler import (
    load_workflow_binding_specs,
    load_workflow_spec,
    load_workflow_primitive_packs,
    write_compiled_workflow_task_set,
)
from meta_harness.workflow_evaluator_binding import (
    bind_evaluator_packs,
    resolve_workflow_evaluator_packs,
    validate_evaluator_pack_bindings,
)


def resolve_workflow_contracts(
    *,
    workflow_path: Path,
    config_root: Path,
) -> tuple[Any, dict[str, Any], list[Any], dict[str, Any]]:
    workflow_spec = load_workflow_spec(workflow_path)
    primitive_packs = load_workflow_primitive_packs(config_root, workflow_spec)
    binding_specs = load_workflow_binding_specs(config_root, workflow_spec)
    evaluator_packs = resolve_workflow_evaluator_packs(config_root, workflow_spec)
    validate_evaluator_pack_bindings(workflow_spec, evaluator_packs, primitive_packs)
    return workflow_spec, primitive_packs, evaluator_packs, binding_specs


def inspect_workflow_payload(
    *,
    workflow_path: Path,
    config_root: Path = Path("configs"),
) -> dict[str, Any]:
    spec, _, _, _ = resolve_workflow_contracts(
        workflow_path=workflow_path,
        config_root=config_root,
    )
    return {
        "workflow_id": spec.workflow_id,
        "step_count": len(spec.steps),
        "primitive_ids": sorted(
            {step.primitive_id for step in spec.steps if step.primitive_id}
        ),
        "evaluator_packs": list(spec.evaluator_packs),
    }


def compile_workflow_payload(
    *,
    workflow_path: Path,
    output_path: Path,
    config_root: Path = Path("configs"),
) -> dict[str, Any]:
    spec, primitive_packs, _, binding_specs = resolve_workflow_contracts(
        workflow_path=workflow_path,
        config_root=config_root,
    )
    task_set = write_compiled_workflow_task_set(
        spec,
        output_path,
        primitive_packs=primitive_packs,
        binding_specs=binding_specs,
    )
    return {
        "workflow_id": spec.workflow_id,
        "output_path": str(output_path),
        "task_set": task_set,
    }


def resolve_workflow_effective_config(
    *,
    workflow_path: Path,
    config_root: Path,
    profile_name: str,
    project_name: str,
) -> dict[str, Any]:
    workflow_spec = load_workflow_spec(workflow_path)
    effective_config = load_effective_config(
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
    )
    primitive_packs = load_workflow_primitive_packs(config_root, workflow_spec)
    packs = resolve_workflow_evaluator_packs(config_root, workflow_spec)
    validate_evaluator_pack_bindings(workflow_spec, packs, primitive_packs)
    return bind_evaluator_packs(effective_config, packs)
