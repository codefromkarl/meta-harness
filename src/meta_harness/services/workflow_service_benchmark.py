from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

from meta_harness.benchmark_engine import run_benchmark, run_benchmark_suite
from meta_harness.compaction import compact_runs
from meta_harness.services.benchmark_service import persist_benchmark_payload
from meta_harness.services.gate_service import evaluate_gate_policy_from_paths
from meta_harness.services.workflow_service_contracts import (
    resolve_workflow_contracts,
    resolve_workflow_effective_config,
)
from meta_harness.workflow_compiler import write_compiled_workflow_task_set


def benchmark_workflow_payload(
    *,
    workflow_path: Path,
    profile_name: str,
    project_name: str,
    spec_path: Path,
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    reports_root: Path = Path("reports"),
    focus: str | None = None,
    auto_compact_runs: bool = True,
    include_artifacts: bool = False,
    compactable_statuses: list[str] | None = None,
    cleanup_auxiliary_dirs: bool = True,
    gate_policy_id: str | None = None,
    run_benchmark_fn: Callable[..., dict] = run_benchmark,
    compact_runs_fn: Callable[..., dict] = compact_runs,
) -> dict:
    workflow_spec, primitive_packs, _, binding_specs = resolve_workflow_contracts(
        workflow_path=workflow_path,
        config_root=config_root,
    )
    effective_config = resolve_workflow_effective_config(
        workflow_path=workflow_path,
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
    )
    with TemporaryDirectory(prefix="meta-harness-workflow-benchmark-") as temp_dir:
        task_set_path = Path(temp_dir) / f"{workflow_spec.workflow_id}.task_set.json"
        write_compiled_workflow_task_set(
            workflow_spec,
            task_set_path,
            primitive_packs=primitive_packs,
            binding_specs=binding_specs,
        )
        payload = run_benchmark_fn(
            config_root=config_root,
            runs_root=runs_root,
            candidates_root=candidates_root,
            profile_name=profile_name,
            project_name=project_name,
            task_set_path=task_set_path,
            spec_path=spec_path,
            focus=focus,
            effective_config_override=effective_config,
        )
    if auto_compact_runs:
        payload["run_compaction"] = compact_runs_fn(
            runs_root,
            candidates_root=candidates_root,
            include_artifacts=include_artifacts,
            compactable_statuses=compactable_statuses,
            cleanup_auxiliary_dirs=cleanup_auxiliary_dirs,
        )
    persisted = persist_benchmark_payload(reports_root=reports_root, payload=payload)
    if gate_policy_id:
        policy_path = config_root / "gate_policies" / f"{gate_policy_id}.json"
        target_path = reports_root.parent / str(persisted["artifact_path"])
        persisted["gate_result"] = evaluate_gate_policy_from_paths(
            policy_path=policy_path,
            target_path=target_path,
            target_type="benchmark_experiment",
            target_ref=str(persisted["artifact_path"]),
            reports_root=reports_root,
            persist_result=True,
        )
    return persisted


def benchmark_suite_workflow_payload(
    *,
    workflow_path: Path,
    profile_name: str,
    project_name: str,
    suite_path: Path,
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    reports_root: Path = Path("reports"),
    auto_compact_runs: bool = True,
    include_artifacts: bool = False,
    compactable_statuses: list[str] | None = None,
    cleanup_auxiliary_dirs: bool = True,
    run_benchmark_suite_fn: Callable[..., dict] = run_benchmark_suite,
    compact_runs_fn: Callable[..., dict] = compact_runs,
) -> dict:
    workflow_spec, primitive_packs, _, binding_specs = resolve_workflow_contracts(
        workflow_path=workflow_path,
        config_root=config_root,
    )
    effective_config = resolve_workflow_effective_config(
        workflow_path=workflow_path,
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
    )
    with TemporaryDirectory(prefix="meta-harness-workflow-benchmark-suite-") as temp_dir:
        task_set_path = Path(temp_dir) / f"{workflow_spec.workflow_id}.task_set.json"
        write_compiled_workflow_task_set(
            workflow_spec,
            task_set_path,
            primitive_packs=primitive_packs,
            binding_specs=binding_specs,
        )
        payload = run_benchmark_suite_fn(
            config_root=config_root,
            runs_root=runs_root,
            candidates_root=candidates_root,
            profile_name=profile_name,
            project_name=project_name,
            task_set_path=task_set_path,
            suite_path=suite_path,
            effective_config_override=effective_config,
        )
    if auto_compact_runs:
        payload["run_compaction"] = compact_runs_fn(
            runs_root,
            candidates_root=candidates_root,
            include_artifacts=include_artifacts,
            compactable_statuses=compactable_statuses,
            cleanup_auxiliary_dirs=cleanup_auxiliary_dirs,
        )
    return persist_benchmark_payload(reports_root=reports_root, payload=payload)
