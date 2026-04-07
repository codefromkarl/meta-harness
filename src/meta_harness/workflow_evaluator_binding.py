from __future__ import annotations

from typing import Any
from pathlib import Path

from meta_harness.evaluator_pack_registry import (
    list_evaluator_packs,
    load_registered_evaluator_pack,
)
from meta_harness.schemas import EvaluatorPack, WorkflowSpec


def resolve_workflow_evaluator_packs(
    config_root: Path,
    workflow_spec: WorkflowSpec,
) -> list[EvaluatorPack]:
    if workflow_spec.evaluator_packs:
        return [
            load_registered_evaluator_pack(config_root, pack_id)
            for pack_id in workflow_spec.evaluator_packs
        ]

    primitive_ids = {step.primitive_id for step in workflow_spec.steps}
    resolved: list[EvaluatorPack] = []
    for pack_id in list_evaluator_packs(config_root):
        pack = load_registered_evaluator_pack(config_root, pack_id)
        if primitive_ids.intersection(pack.supported_primitives):
            resolved.append(pack)
    return resolved


def bind_evaluator_packs(
    effective_config: dict[str, Any],
    packs: list[EvaluatorPack],
) -> dict[str, Any]:
    if not packs:
        return effective_config

    bound = dict(effective_config)
    evaluation = dict(bound.get("evaluation") or {})
    evaluators = list(evaluation.get("evaluators") or [])
    if "command" not in evaluators:
        evaluators.append("command")

    existing_commands = list(evaluation.get("command_evaluators") or [])
    seen_names = {
        str(item.get("name"))
        for item in existing_commands
        if isinstance(item, dict) and item.get("name") is not None
    }
    for pack in packs:
        if pack.pack_id in seen_names:
            continue
        existing_commands.append(
            {
                "name": pack.pack_id,
                "command": list(pack.command),
            }
        )
        seen_names.add(pack.pack_id)

    evaluation["evaluators"] = evaluators
    evaluation["command_evaluators"] = existing_commands
    bound["evaluation"] = evaluation
    return bound
