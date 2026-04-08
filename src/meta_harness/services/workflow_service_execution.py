from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

from meta_harness.runtime_execution import execute_managed_run
from meta_harness.services.workflow_service_contracts import (
    resolve_workflow_contracts,
    resolve_workflow_effective_config,
)
from meta_harness.workflow_compiler import write_compiled_workflow_task_set


def run_workflow_payload(
    *,
    workflow_path: Path,
    profile_name: str,
    project_name: str,
    config_root: Path,
    runs_root: Path,
    execute_managed_run_fn: Callable[..., dict] = execute_managed_run,
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
    with TemporaryDirectory(prefix="meta-harness-workflow-run-") as temp_dir:
        task_set_path = Path(temp_dir) / f"{workflow_spec.workflow_id}.task_set.json"
        write_compiled_workflow_task_set(
            workflow_spec,
            task_set_path,
            primitive_packs=primitive_packs,
            binding_specs=binding_specs,
        )
        return execute_managed_run_fn(
            runs_root=runs_root,
            profile_name=profile_name,
            project_name=project_name,
            effective_config=effective_config,
            task_set_path=task_set_path,
        )
