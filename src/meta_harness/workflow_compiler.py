from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any

from meta_harness.schemas import WorkflowSpec, WorkflowStep


def load_workflow_spec(path: Path) -> WorkflowSpec:
    return WorkflowSpec.model_validate_json(path.read_text(encoding="utf-8"))


def compile_workflow_spec(spec: WorkflowSpec) -> dict[str, Any]:
    ordered_steps = _topological_steps(spec.steps)
    return {
        "workflow_id": spec.workflow_id,
        "metadata": {
            "version": spec.version,
            "profile": spec.profile,
            "project": spec.project,
            "evaluator_packs": list(spec.evaluator_packs),
            "optimization_policy": spec.optimization_policy.model_dump(),
            "workflow_metadata": dict(spec.metadata),
        },
        "tasks": [_compile_step(step) for step in ordered_steps],
    }


def write_compiled_workflow_task_set(
    spec: WorkflowSpec,
    output_path: Path,
) -> dict[str, Any]:
    payload = compile_workflow_spec(spec)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _compile_step(step: WorkflowStep) -> dict[str, Any]:
    if not step.command:
        raise ValueError(f"workflow step '{step.step_id}' must define a command")

    expectations = {
        **step.expectations,
        "primitive_id": step.primitive_id,
        "role": step.role,
        "depends_on": list(step.depends_on),
        "optional": step.optional,
        "knobs": dict(step.knobs),
    }

    return {
        "task_id": step.step_id,
        "scenario": step.primitive_id,
        "weight": step.weight,
        "workdir": step.workdir or "${workspace_dir}",
        "expectations": expectations,
        "phases": [
            {
                "phase": step.step_id,
                "command": list(step.command),
            }
        ],
    }


def _topological_steps(steps: list[WorkflowStep]) -> list[WorkflowStep]:
    by_id = {step.step_id: step for step in steps}
    incoming: dict[str, int] = {}
    outgoing: dict[str, list[str]] = {step.step_id: [] for step in steps}

    for step in steps:
        incoming[step.step_id] = len(step.depends_on)
        for dependency in step.depends_on:
            if dependency not in by_id:
                raise ValueError(
                    f"workflow step '{step.step_id}' depends on unknown step '{dependency}'"
                )
            outgoing.setdefault(dependency, []).append(step.step_id)

    queue = deque(sorted(step_id for step_id, degree in incoming.items() if degree == 0))
    ordered_ids: list[str] = []
    while queue:
        step_id = queue.popleft()
        ordered_ids.append(step_id)
        for neighbor in sorted(outgoing.get(step_id, [])):
            incoming[neighbor] -= 1
            if incoming[neighbor] == 0:
                queue.append(neighbor)

    if len(ordered_ids) != len(steps):
        raise ValueError("workflow step dependency cycle detected")

    return [by_id[step_id] for step_id in ordered_ids]
