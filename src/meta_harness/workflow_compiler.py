from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any

from meta_harness.primitive_registry import load_registered_primitive_pack
from meta_harness.integration_review import require_activated_generated_binding
from meta_harness.schemas import (
    ClawBindingSpec,
    EvaluationContract,
    PrimitivePack,
    PageProfile,
    WorkflowHarnessRef,
    WorkflowSpec,
    WorkflowStep,
    WorkloadProfile,
)
from meta_harness.transfer import load_claw_binding


def load_workflow_spec(path: Path) -> WorkflowSpec:
    return WorkflowSpec.model_validate_json(path.read_text(encoding="utf-8"))


def load_workflow_primitive_packs(
    config_root: Path,
    spec: WorkflowSpec,
) -> dict[str, PrimitivePack]:
    primitive_ids = {step.primitive_id for step in spec.steps if step.primitive_id}
    resolved: dict[str, PrimitivePack] = {}
    for primitive_id in primitive_ids:
        try:
            resolved[primitive_id] = load_registered_primitive_pack(config_root, primitive_id)
        except FileNotFoundError:
            continue
    return resolved


def load_workflow_binding_specs(
    config_root: Path,
    spec: WorkflowSpec,
) -> dict[str, ClawBindingSpec]:
    binding_ids = {step.binding_id for step in spec.steps if step.binding_id}
    resolved: dict[str, ClawBindingSpec] = {}
    for binding_id in binding_ids:
        if binding_id is None:
            continue
        resolved[binding_id] = load_claw_binding(config_root, binding_id)
    return resolved


def compile_workflow_spec(
    spec: WorkflowSpec,
    *,
    primitive_packs: dict[str, PrimitivePack] | None = None,
    binding_specs: dict[str, ClawBindingSpec] | None = None,
) -> dict[str, Any]:
    ordered_steps = _topological_steps(spec.steps)
    primitive_lookup = primitive_packs or {}
    binding_lookup = binding_specs or {}
    return {
        "workflow_id": spec.workflow_id,
        "metadata": {
            "version": spec.version,
            "profile": spec.profile,
            "project": spec.project,
            "evaluator_packs": list(spec.evaluator_packs),
            "page_profile": spec.page_profile.model_dump(),
            "workload_profile": spec.workload_profile.model_dump(),
            "optimization_policy": spec.optimization_policy.model_dump(),
            "workflow_metadata": dict(spec.metadata),
        },
        "tasks": [
            _compile_step(
                step,
                page_profile=spec.page_profile,
                workload_profile=spec.workload_profile,
                primitive_pack=primitive_lookup.get(step.primitive_id)
                if step.primitive_id is not None
                else None,
                binding_spec=binding_lookup.get(step.binding_id or ""),
            )
            for step in ordered_steps
        ],
    }


def write_compiled_workflow_task_set(
    spec: WorkflowSpec,
    output_path: Path,
    *,
    primitive_packs: dict[str, PrimitivePack] | None = None,
    binding_specs: dict[str, ClawBindingSpec] | None = None,
) -> dict[str, Any]:
    payload = compile_workflow_spec(
        spec,
        primitive_packs=primitive_packs,
        binding_specs=binding_specs,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _merge_evaluation_contract(
    primitive_default: EvaluationContract | None,
    step_override: EvaluationContract,
) -> dict[str, Any]:
    base = (
        primitive_default.model_dump(exclude_none=True)
        if primitive_default is not None
        else {}
    )
    override = step_override.model_dump(exclude_none=True)

    merged: dict[str, Any] = {
        "artifact_requirements": (
            override.get("artifact_requirements")
            if override.get("artifact_requirements")
            else base.get("artifact_requirements", [])
        ),
        "required_fields": (
            override.get("required_fields")
            if override.get("required_fields")
            else base.get("required_fields", [])
        ),
    }

    latency_budget_ms = override.get("latency_budget_ms")
    if latency_budget_ms is None:
        latency_budget_ms = base.get("latency_budget_ms")
    if latency_budget_ms is not None:
        merged["latency_budget_ms"] = latency_budget_ms

    base_thresholds = base.get("quality_thresholds") or {}
    override_thresholds = override.get("quality_thresholds") or {}
    threshold_keys = sorted(set(base_thresholds) | set(override_thresholds))
    if threshold_keys:
        merged["quality_thresholds"] = {
            key: (
                override_thresholds[key]
                if override_thresholds.get(key) is not None
                else base_thresholds.get(key)
            )
            for key in threshold_keys
            if (
                override_thresholds.get(key) is not None
                or base_thresholds.get(key) is not None
            )
        }

    return merged


def _merge_profile(
    default_profile: PageProfile | WorkloadProfile | None,
    override_profile: PageProfile | WorkloadProfile | None,
) -> dict[str, Any]:
    base = (
        default_profile.model_dump()
        if default_profile is not None
        else {}
    )
    if override_profile is None:
        return base
    override = override_profile.model_dump(exclude_unset=True, exclude_none=True)
    if not override:
        return base
    return {**base, **override}


def _compile_step(
    step: WorkflowStep,
    *,
    page_profile: PageProfile | None = None,
    workload_profile: WorkloadProfile | None = None,
    primitive_pack: PrimitivePack | None = None,
    binding_spec: ClawBindingSpec | None = None,
) -> dict[str, Any]:
    if not step.command:
        raise ValueError(f"workflow step '{step.step_id}' must define a command")
    if (
        binding_spec is not None
        and step.primitive_id is not None
        and binding_spec.primitive_id != step.primitive_id
    ):
        raise ValueError(
            "workflow binding primitive mismatch: "
            f"step '{step.step_id}' uses '{step.primitive_id}', "
            f"binding '{binding_spec.binding_id}' serves '{binding_spec.primitive_id}'"
        )
    if binding_spec is not None:
        require_activated_generated_binding(binding_spec.model_dump())

    evaluation = _merge_evaluation_contract(
        primitive_pack.evaluation_contract if primitive_pack is not None else None,
        step.evaluation,
    )
    merged_page_profile = _merge_profile(page_profile, step.page_profile)
    merged_workload_profile = _merge_profile(workload_profile, step.workload_profile)
    quality_thresholds = evaluation.get("quality_thresholds")
    if not quality_thresholds:
        evaluation.pop("quality_thresholds", None)

    expectations = {
        **step.expectations,
        "primitive_id": step.primitive_id,
        "role": step.role,
        "depends_on": list(step.depends_on),
        "optional": step.optional,
        "knobs": dict(step.knobs),
        "page_profile": merged_page_profile,
        "workload_profile": merged_workload_profile,
        "execution_kind": "harness" if _step_harness_ref(step) is not None else "primitive",
        **evaluation,
    }
    if step.method_id is not None:
        expectations["method_id"] = step.method_id
    if step.binding_id is not None:
        expectations["binding_id"] = step.binding_id

    harness_payload = _step_harness_payload(step)
    if harness_payload is not None:
        expectations.update(
            {
                key: value
                for key, value in harness_payload.items()
                if key != "execution_unit"
            }
        )
    payload = {
        "task_id": step.step_id,
        "scenario": _step_scenario(step, harness_payload),
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
    if step.primitive_id is not None:
        payload["primitive_id"] = step.primitive_id
    if harness_payload is not None:
        payload.update(harness_payload)
    if binding_spec is not None:
        payload["binding"] = {
            "binding_id": binding_spec.binding_id,
            "adapter_kind": binding_spec.adapter_kind,
            **dict(binding_spec.execution),
        }
    return payload


def _step_scenario(
    step: WorkflowStep,
    harness_payload: dict[str, Any] | None,
) -> str:
    if harness_payload is not None:
        execution_unit = harness_payload.get("execution_unit")
        if isinstance(execution_unit, dict):
            execution_id = execution_unit.get("execution_id")
            if isinstance(execution_id, str) and execution_id:
                return execution_id
            candidate_harness_id = execution_unit.get("candidate_harness_id")
            if isinstance(candidate_harness_id, str) and candidate_harness_id:
                return candidate_harness_id
            harness_id = execution_unit.get("harness_id")
            if isinstance(harness_id, str) and harness_id:
                return harness_id
    if step.primitive_id is not None:
        return step.primitive_id
    return step.step_id


def _step_harness_ref(step: WorkflowStep) -> WorkflowHarnessRef | None:
    return step.candidate_harness_ref or step.harness_ref


def _workflow_harness_ref_payload(
    ref: WorkflowHarnessRef | None,
) -> dict[str, Any] | None:
    if ref is None:
        return None
    return ref.model_dump(exclude_none=True)


def _step_harness_payload(step: WorkflowStep) -> dict[str, Any] | None:
    harness_ref = _workflow_harness_ref_payload(step.harness_ref)
    candidate_harness_ref = _workflow_harness_ref_payload(step.candidate_harness_ref)
    effective_ref = candidate_harness_ref or harness_ref
    if effective_ref is None:
        return None

    harness_id = effective_ref.get("harness_id")
    candidate_harness_id = effective_ref.get("candidate_harness_id")
    execution_id = candidate_harness_id or harness_id or step.step_id
    harness_context = {
        "execution_kind": "harness",
        "harness_id": harness_id,
        "candidate_harness_id": candidate_harness_id,
        "proposal_id": effective_ref.get("proposal_id"),
        "iteration_id": effective_ref.get("iteration_id"),
        "wrapper_path": effective_ref.get("wrapper_path"),
        "source_artifacts": list(effective_ref.get("source_artifacts") or []),
        "provenance": dict(effective_ref.get("provenance") or {}),
        "execution_unit": {
            "kind": "harness",
            "ref_kind": (
                "candidate_harness_ref"
                if candidate_harness_ref is not None
                else "harness_ref"
            ),
            "execution_id": execution_id,
            "harness_id": harness_id,
            "candidate_harness_id": candidate_harness_id,
            "proposal_id": effective_ref.get("proposal_id"),
            "iteration_id": effective_ref.get("iteration_id"),
            "wrapper_path": effective_ref.get("wrapper_path"),
            "source_artifacts": list(effective_ref.get("source_artifacts") or []),
            "provenance": dict(effective_ref.get("provenance") or {}),
        },
        "harness_ref": harness_ref or effective_ref,
    }
    if candidate_harness_ref is not None:
        harness_context["candidate_harness_ref"] = candidate_harness_ref
    return harness_context


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
