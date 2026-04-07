from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable

from meta_harness.benchmark import run_benchmark, run_benchmark_suite
from meta_harness.compaction import compact_runs
from meta_harness.config_loader import load_effective_config
from meta_harness.runtime import execute_managed_run
from meta_harness.workflow_compiler import (
    load_workflow_spec,
    write_compiled_workflow_task_set,
)
from meta_harness.workflow_evaluator_binding import (
    bind_evaluator_packs,
    resolve_workflow_evaluator_packs,
)


def inspect_workflow_payload(*, workflow_path: Path) -> dict[str, Any]:
    spec = load_workflow_spec(workflow_path)
    return {
        "workflow_id": spec.workflow_id,
        "step_count": len(spec.steps),
        "primitive_ids": sorted({step.primitive_id for step in spec.steps}),
        "evaluator_packs": list(spec.evaluator_packs),
    }


def compile_workflow_payload(
    *,
    workflow_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    spec = load_workflow_spec(workflow_path)
    task_set = write_compiled_workflow_task_set(spec, output_path)
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
    packs = resolve_workflow_evaluator_packs(config_root, workflow_spec)
    return bind_evaluator_packs(effective_config, packs)


def run_workflow_payload(
    *,
    workflow_path: Path,
    profile_name: str,
    project_name: str,
    config_root: Path,
    runs_root: Path,
    execute_managed_run_fn: Callable[..., dict[str, Any]] = execute_managed_run,
) -> dict[str, Any]:
    workflow_spec = load_workflow_spec(workflow_path)
    effective_config = resolve_workflow_effective_config(
        workflow_path=workflow_path,
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
    )
    with TemporaryDirectory(prefix="meta-harness-workflow-run-") as temp_dir:
        task_set_path = Path(temp_dir) / f"{workflow_spec.workflow_id}.task_set.json"
        write_compiled_workflow_task_set(workflow_spec, task_set_path)
        return execute_managed_run_fn(
            runs_root=runs_root,
            profile_name=profile_name,
            project_name=project_name,
            effective_config=effective_config,
            task_set_path=task_set_path,
        )


def benchmark_workflow_payload(
    *,
    workflow_path: Path,
    profile_name: str,
    project_name: str,
    spec_path: Path,
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    focus: str | None = None,
    auto_compact_runs: bool = True,
    include_artifacts: bool = False,
    compactable_statuses: list[str] | None = None,
    cleanup_auxiliary_dirs: bool = True,
    run_benchmark_fn: Callable[..., dict[str, Any]] = run_benchmark,
    compact_runs_fn: Callable[..., dict[str, Any]] = compact_runs,
) -> dict[str, Any]:
    workflow_spec = load_workflow_spec(workflow_path)
    effective_config = resolve_workflow_effective_config(
        workflow_path=workflow_path,
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
    )
    with TemporaryDirectory(prefix="meta-harness-workflow-benchmark-") as temp_dir:
        task_set_path = Path(temp_dir) / f"{workflow_spec.workflow_id}.task_set.json"
        write_compiled_workflow_task_set(workflow_spec, task_set_path)
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
    return payload


def benchmark_suite_workflow_payload(
    *,
    workflow_path: Path,
    profile_name: str,
    project_name: str,
    suite_path: Path,
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    auto_compact_runs: bool = True,
    include_artifacts: bool = False,
    compactable_statuses: list[str] | None = None,
    cleanup_auxiliary_dirs: bool = True,
    run_benchmark_suite_fn: Callable[..., dict[str, Any]] = run_benchmark_suite,
    compact_runs_fn: Callable[..., dict[str, Any]] = compact_runs,
) -> dict[str, Any]:
    workflow_spec = load_workflow_spec(workflow_path)
    effective_config = resolve_workflow_effective_config(
        workflow_path=workflow_path,
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
    )
    with TemporaryDirectory(prefix="meta-harness-workflow-benchmark-suite-") as temp_dir:
        task_set_path = Path(temp_dir) / f"{workflow_spec.workflow_id}.task_set.json"
        write_compiled_workflow_task_set(workflow_spec, task_set_path)
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
    return payload
