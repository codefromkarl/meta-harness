from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from meta_harness.archive import initialize_run
from meta_harness.binding_adapters import BindingExecutionResult, execute_binding
from meta_harness.config_loader import merge_dicts
from meta_harness.integration_review import require_activated_generated_binding
from meta_harness.primitive_bridge import materialize_binding_outputs
from meta_harness.runtime_context import _candidate_harness_execution_context
from meta_harness.runtime_workspace import _read_json, _seed_run_root_state, materialize_workspace
from meta_harness.scoring import score_run
from meta_harness.template_utils import (
    _build_template_context,
    _normalize_template_paths,
    _resolve_template,
)
from meta_harness.trace_store import append_trace_event


def _runtime_subprocess():
    import meta_harness.runtime as runtime_root
    return runtime_root.subprocess


def execute_managed_run(
    *,
    runs_root: Path,
    profile_name: str,
    project_name: str,
    effective_config: dict[str, Any],
    task_set_path: Path,
    candidate_id: str | None = None,
    code_patch_path: Path | None = None,
    workspace_source_override: Path | None = None,
    run_id: str | None = None,
    seed_root_state_from: Path | None = None,
    score_enabled: bool = True,
) -> dict[str, Any]:
    run_id = initialize_run(
        runs_root=runs_root,
        profile_name=profile_name,
        project_name=project_name,
        effective_config=effective_config,
        candidate_id=candidate_id,
        run_id=run_id,
    )
    run_dir = runs_root / run_id
    if seed_root_state_from is not None:
        _seed_run_root_state(run_dir, seed_root_state_from)
    execution_context = materialize_workspace(
        run_dir=run_dir,
        effective_config=effective_config,
        code_patch_path=code_patch_path,
        workspace_source_override=workspace_source_override,
    )
    task_summary = execute_task_set(
        run_dir,
        task_set_path,
        execution_context=execution_context,
    )
    score = score_run(run_dir) if score_enabled else None
    return {
        "run_id": run_id,
        "task_summary": task_summary,
        "score": score,
    }

def execute_task_set(
    run_dir: Path,
    task_set_path: Path,
    execution_context: dict[str, str] | None = None,
) -> dict[str, int]:
    task_set = _read_json(task_set_path)
    effective_config_path = run_dir / "effective_config.json"
    effective_config = (
        _read_json(effective_config_path) if effective_config_path.exists() else {}
    )
    total = 0
    succeeded = 0

    for task in task_set.get("tasks", []):
        total += 1
        if _execute_task(
            run_dir,
            task,
            execution_context=execution_context,
            effective_config=effective_config,
        ):
            succeeded += 1

    return {"succeeded": succeeded, "total": total}

def _evaluate_phase_assertions(
    *,
    phase: dict[str, Any],
    workdir: Path,
    completed: subprocess.CompletedProcess[str],
    context: dict[str, Any],
) -> tuple[str | None, dict[str, Any] | None]:
    raw_assertions = phase.get("assertions") or []
    if not raw_assertions:
        return None, None
    if not isinstance(raw_assertions, list):
        return "phase assertions must be a list", {"kind": "invalid_assertions"}

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""

    for raw_assertion in raw_assertions:
        if not isinstance(raw_assertion, dict):
            return (
                "phase assertion must be an object",
                {"kind": "invalid_assertion"},
            )

        kind = str(raw_assertion.get("kind", "")).strip()
        failed_assertion = dict(raw_assertion)
        failed_assertion["kind"] = kind or "unknown"

        if kind == "stdout_contains":
            expected = str(_resolve_template(raw_assertion.get("value", ""), context))
            if expected not in stdout:
                return (
                    f"assertion stdout_contains failed: missing {expected!r}",
                    failed_assertion,
                )
        elif kind == "stdout_not_contains":
            unexpected = str(_resolve_template(raw_assertion.get("value", ""), context))
            if unexpected and unexpected in stdout:
                return (
                    f"assertion stdout_not_contains failed: found {unexpected!r}",
                    failed_assertion,
                )
        elif kind == "stderr_contains":
            expected = str(_resolve_template(raw_assertion.get("value", ""), context))
            if expected not in stderr:
                return (
                    f"assertion stderr_contains failed: missing {expected!r}",
                    failed_assertion,
                )
        elif kind == "stderr_not_contains":
            unexpected = str(_resolve_template(raw_assertion.get("value", ""), context))
            if unexpected and unexpected in stderr:
                return (
                    f"assertion stderr_not_contains failed: found {unexpected!r}",
                    failed_assertion,
                )
        elif kind == "artifact_exists":
            resolved_path = _resolve_template(raw_assertion.get("path"), context)
            artifact_path = Path(str(resolved_path))
            if not artifact_path.is_absolute():
                artifact_path = workdir / artifact_path
            if not artifact_path.exists():
                failed_assertion["path"] = str(artifact_path)
                return (
                    f"assertion artifact_exists failed: missing {artifact_path}",
                    failed_assertion,
                )
        else:
            return (
                f"unknown assertion kind: {kind or '<empty>'}",
                failed_assertion,
            )

    return None, None

def _execute_task(
    run_dir: Path,
    task: dict[str, Any],
    execution_context: dict[str, str] | None = None,
    effective_config: dict[str, Any] | None = None,
) -> bool:
    task_id = task["task_id"]
    task_dir = run_dir / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    context = _build_template_context(
        run_dir,
        effective_config=effective_config,
        execution_context=execution_context,
    )
    context["task"] = task

    workdir = Path(_resolve_template(task.get("workdir", str(run_dir)), context))

    completed_phases = 0
    failed_phase: str | None = None
    failed_assertion: dict[str, Any] | None = None
    expectations = task.get("expectations") if isinstance(task.get("expectations"), dict) else {}
    method_id = expectations.get("method_id")
    binding_id = expectations.get("binding_id")
    resolved_binding = _resolve_task_binding(task, effective_config)
    harness_execution_context = _candidate_harness_execution_context(
        task=task,
        effective_config=effective_config or {},
        resolved_binding=resolved_binding,
    )

    for index, phase in enumerate(task.get("phases", []), start=1):
        start = time.monotonic()
        execution = _execute_phase_command(
            phase=phase,
            task=task,
            workdir=workdir,
            context=context,
        )
        completed = execution.completed
        latency_ms = int((time.monotonic() - start) * 1000)

        (task_dir / f"{phase['phase']}.stdout.txt").write_text(
            completed.stdout,
            encoding="utf-8",
        )
        (task_dir / f"{phase['phase']}.stderr.txt").write_text(
            completed.stderr,
            encoding="utf-8",
        )

        assertion_error: str | None = None
        if completed.returncode == 0:
            assertion_error, failed_assertion = _evaluate_phase_assertions(
                phase=phase,
                workdir=workdir,
                completed=completed,
                context=context,
            )

        status = (
            "completed"
            if completed.returncode == 0 and assertion_error is None
            else "failed"
        )
        error_text = (
            assertion_error
            or (completed.stderr or completed.stdout).strip()
            or None
        )

        append_trace_event(
            run_dir=run_dir,
            task_id=task_id,
            event={
                "step_id": f"step-{index}",
                "phase": phase["phase"],
                "status": status,
                "model": execution.model or _binding_model_name(task, effective_config),
                "artifact_refs": list(execution.artifact_refs) or None,
                "token_usage": execution.token_usage,
                "latency_ms": latency_ms,
                "error": error_text if status == "failed" else None,
                **harness_execution_context,
            },
        )
        if status == "completed":
            for normalized_index, normalized_event in enumerate(
                execution.normalized_events,
                start=1,
            ):
                append_trace_event(
                    run_dir=run_dir,
                    task_id=task_id,
                    event={
                        "step_id": f"step-{index}-normalized-{normalized_index}",
                        "phase": normalized_event.get("phase", phase["phase"]),
                        "status": normalized_event.get("status", "completed"),
                        "model": normalized_event.get("model")
                        or execution.model
                        or _binding_model_name(task, effective_config),
                        "artifact_refs": list(execution.artifact_refs) or None,
                        "token_usage": normalized_event.get("token_usage")
                        or execution.token_usage,
                        "latency_ms": int(normalized_event.get("latency_ms") or 0),
                        "error": normalized_event.get("error"),
                        **harness_execution_context,
                    },
                )

        if completed.returncode != 0 or assertion_error is not None:
            failed_phase = phase["phase"]
            break

        completed_phases += 1

    success = failed_phase is None
    (task_dir / "task_result.json").write_text(
        json.dumps(
            {
                "task_id": task_id,
                "scenario": task.get("scenario"),
                "difficulty": task.get("difficulty"),
                "weight": task.get("weight"),
                "expectations": task.get("expectations"),
                "dataset_case": task.get("dataset_case"),
                "method_id": method_id,
                "binding_id": binding_id
                or _binding_id_from_task_or_config(task, effective_config),
                "binding_payload": execution.payload,
                "binding_artifacts": list(execution.artifact_refs),
                "success": success,
                "completed_phases": completed_phases,
                "failed_phase": failed_phase,
                "failed_assertion": failed_assertion,
                "workdir": str(workdir),
                **harness_execution_context,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return success

def _binding_model_name(
    task: dict[str, Any],
    effective_config: dict[str, Any] | None,
) -> str | None:
    binding = _resolve_task_binding(task, effective_config)
    model = binding.get("model")
    if isinstance(model, str) and model:
        return model
    agent_id = binding.get("agent_id")
    return str(agent_id) if isinstance(agent_id, str) and agent_id else None

def _binding_id_from_task_or_config(
    task: dict[str, Any],
    effective_config: dict[str, Any] | None,
) -> str | None:
    binding = _resolve_task_binding(task, effective_config)
    binding_id = binding.get("binding_id")
    return str(binding_id) if isinstance(binding_id, str) and binding_id else None

def _resolve_task_binding(
    task: dict[str, Any],
    effective_config: dict[str, Any] | None,
) -> dict[str, Any]:
    runtime_binding = {}
    if isinstance(effective_config, dict):
        runtime = effective_config.get("runtime")
        if isinstance(runtime, dict) and isinstance(runtime.get("binding"), dict):
            runtime_binding = dict(runtime["binding"])
    task_binding = task.get("binding")
    if isinstance(task_binding, dict):
        return merge_dicts(runtime_binding, task_binding)
    return runtime_binding

def _binding_env(
    binding: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, str]:
    resolved_env = {
        "META_HARNESS_RUN_DIR": context["run_dir"],
        "META_HARNESS_WORKSPACE_DIR": context["workspace_dir"],
        "META_HARNESS_SOURCE_REPO": context["source_repo"],
    }
    raw_env = binding.get("env")
    if isinstance(raw_env, dict):
        for key, value in _resolve_template(raw_env, context).items():
            resolved_env[str(key)] = str(value)
    return resolved_env

def _execute_phase_command(
    *,
    phase: dict[str, Any],
    task: dict[str, Any],
    workdir: Path,
    context: dict[str, Any],
) -> BindingExecutionResult:
    effective_config = context if isinstance(context, dict) else {}
    binding = _resolve_task_binding(task, effective_config)
    adapter_kind = binding.get("adapter_kind")
    if isinstance(adapter_kind, str) and adapter_kind:
        phase_context = dict(context)
        phase_context["phase"] = phase
        phase_context["phase_command_json"] = json.dumps(phase.get("command") or [])
        require_activated_generated_binding(binding)
        task_id = str(task.get("task_id", "task"))
        task_dir = Path(context["run_dir"]) / "tasks" / task_id
        return _execute_binding_phase(
            adapter_kind=adapter_kind,
            binding=binding,
            phase=phase,
            workdir=workdir,
            context=phase_context,
            task_dir=task_dir,
        )

    command = _resolve_template(phase["command"], context)
    completed = _runtime_subprocess().run(
        command,
        cwd=workdir,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **_binding_env({}, context)},
    )
    return BindingExecutionResult(completed=completed)

def _execute_binding_phase(
    *,
    adapter_kind: str,
    binding: dict[str, Any],
    phase: dict[str, Any],
    workdir: Path,
    context: dict[str, Any],
    task_dir: Path,
) -> BindingExecutionResult:
    execution = execute_binding(
        adapter_kind=adapter_kind,
        binding=binding,
        phase=phase,
        workdir=workdir,
        context=context,
        resolve_template=_resolve_template,
        env_factory=_binding_env,
    )
    if execution.payload is not None:
        artifact_name = f"{phase['phase']}.binding_payload.json"
        artifact_path = task_dir / artifact_name
        artifact_path.write_text(
            json.dumps(execution.payload, indent=2),
            encoding="utf-8",
        )
        execution.artifact_refs.append(artifact_name)
    bridge_result = materialize_binding_outputs(
        binding=binding,
        context=context,
        payload=execution.payload,
        task_dir=task_dir,
        resolve_template=_resolve_template,
    )
    execution.artifact_refs.extend(bridge_result.artifact_refs)
    execution.normalized_events.extend(bridge_result.normalized_events)
    _run_phase_postprocess(
        phase=phase,
        workdir=workdir,
        context=context,
    )
    return execution

def _run_phase_postprocess(
    *,
    phase: dict[str, Any],
    workdir: Path,
    context: dict[str, Any],
) -> None:
    raw_command = phase.get("postprocess_command")
    if raw_command is None:
        return
    command = _resolve_template(raw_command, context)
    completed = _runtime_subprocess().run(
        command,
        cwd=workdir,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **_binding_env({}, context)},
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"postprocess command failed for phase '{phase.get('phase', 'unknown')}': "
            f"{(completed.stderr or completed.stdout).strip()}"
        )

