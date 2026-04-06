from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from meta_harness.archive import initialize_run
from meta_harness.scoring import score_run
from meta_harness.schemas import WorkspaceArtifact
from meta_harness.trace_store import append_trace_event


_DEFAULT_WORKSPACE_IGNORE = (".git", "node_modules")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def materialize_workspace(
    run_dir: Path,
    effective_config: dict[str, Any],
    code_patch_path: Path | None = None,
    workspace_source_override: Path | None = None,
) -> dict[str, str] | None:
    resolved = _resolve_workspace_source(run_dir, effective_config=effective_config)
    if resolved is None:
        return None
    source_repo, ignore_patterns = resolved
    copy_source_repo = (
        workspace_source_override.expanduser().resolve()
        if workspace_source_override is not None
        else source_repo
    )
    workspace_dir = run_dir / "workspace"
    _copy_workspace_tree(copy_source_repo, workspace_dir, ignore_patterns)

    patch_applied = False
    patch_already_present = False
    code_patch_artifact = None
    if code_patch_path is not None:
        code_patch_artifact = code_patch_path.name
        completed = subprocess.run(
            ["git", "apply", str(code_patch_path)],
            cwd=workspace_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            reverse_check = subprocess.run(
                ["git", "apply", "--reverse", "--check", str(code_patch_path)],
                cwd=workspace_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            if reverse_check.returncode != 0:
                raise RuntimeError(
                    f"failed to apply code patch: {completed.stderr.strip()}"
                )
            patch_already_present = True
        else:
            patch_applied = True

    artifact = WorkspaceArtifact(
        source_repo=str(copy_source_repo),
        workspace_dir=str(workspace_dir),
        patch_applied=patch_applied,
        patch_already_present=patch_already_present,
        code_patch_artifact=code_patch_artifact,
    )
    (run_dir / "artifacts" / "workspace.json").write_text(
        artifact.model_dump_json(indent=2),
        encoding="utf-8",
    )

    return {
        "run_dir": str(run_dir),
        "workspace_dir": str(workspace_dir),
        "source_repo": str(source_repo),
    }


def freeze_workspace_source(
    *,
    snapshot_dir: Path,
    effective_config: dict[str, Any],
) -> Path | None:
    resolved = _resolve_workspace_source(snapshot_dir, effective_config=effective_config)
    if resolved is None:
        return None
    source_repo, ignore_patterns = resolved
    _copy_workspace_tree(source_repo, snapshot_dir, ignore_patterns)
    return snapshot_dir.resolve()


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


def _seed_run_root_state(run_dir: Path, source_run_dir: Path) -> None:
    protected = {"run_metadata.json", "effective_config.json", "score_report.json"}
    if not source_run_dir.exists():
        return
    for path in source_run_dir.iterdir():
        if not path.is_file() or path.name in protected:
            continue
        shutil.copy2(path, run_dir / path.name)


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


def _resolve_workspace_source(
    run_dir: Path,
    *,
    effective_config: dict[str, Any],
) -> tuple[Path, list[str]] | None:
    workspace_config = effective_config.get("runtime", {}).get("workspace")
    if not workspace_config:
        return None

    templating_context = _build_template_context(run_dir, effective_config=effective_config)
    source_repo = Path(
        _resolve_template(workspace_config["source_repo"], templating_context)
    ).expanduser()
    ignore_patterns = list(_DEFAULT_WORKSPACE_IGNORE)
    configured_patterns = workspace_config.get("ignore") or []
    for pattern in configured_patterns:
        resolved_pattern = _resolve_template(pattern, templating_context)
        if isinstance(resolved_pattern, str):
            ignore_patterns.append(resolved_pattern)
    return source_repo, ignore_patterns


def _copy_workspace_tree(source_repo: Path, destination_dir: Path, ignore_patterns: list[str]) -> None:
    shutil.copytree(
        source_repo,
        destination_dir,
        ignore=shutil.ignore_patterns(*ignore_patterns),
    )


_TEMPLATE_PATTERN = re.compile(r"\$\{([^}]+)\}")
_PROJECT_ID_JSON_PATTERN = re.compile(r'"projectId"\s*:\s*"([^"]+)"')
_PROJECT_ID_TEXT_PATTERN = re.compile(r"项目已注册：.*\(([^)]+)\)")


def _build_template_context(
    run_dir: Path,
    *,
    effective_config: dict[str, Any] | None = None,
    execution_context: dict[str, str] | None = None,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "run_dir": str(run_dir.resolve()),
        "workspace_dir": str(run_dir.resolve()),
        "source_repo": str(run_dir.resolve()),
    }
    if effective_config:
        context.update(effective_config)
    if execution_context is not None:
        context.update(execution_context)
    _normalize_template_paths(context)
    return context


def _lookup_template_value(variables: dict[str, Any], key: str) -> Any:
    current: Any = variables
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _resolve_template(value: Any, variables: dict[str, Any]) -> Any:
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            resolved = _lookup_template_value(variables, match.group(1))
            if resolved is None:
                return match.group(0)
            return str(resolved)

        return _TEMPLATE_PATTERN.sub(replace, value)
    if isinstance(value, list):
        return [_resolve_template(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_template(item, variables) for key, item in value.items()}
    return value


def _normalize_template_paths(context: dict[str, Any]) -> None:
    for key in ("run_dir", "workspace_dir", "source_repo"):
        value = context.get(key)
        if isinstance(value, str):
            context[key] = str(Path(value).expanduser().resolve())


def _extract_project_id(output: str) -> str | None:
    json_match = _PROJECT_ID_JSON_PATTERN.search(output)
    if json_match:
        return json_match.group(1)

    text_match = _PROJECT_ID_TEXT_PATTERN.search(output)
    if text_match:
        return text_match.group(1)

    return None


def _update_context_from_phase_output(context: dict[str, Any], phase: str, output: str) -> None:
    if phase != "register_project":
        return

    project_id = _extract_project_id(output)
    if project_id is None:
        return

    contextatlas = context.get("contextatlas")
    if not isinstance(contextatlas, dict):
        contextatlas = {}
        context["contextatlas"] = contextatlas
    contextatlas["project_id"] = project_id


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

    workdir = Path(_resolve_template(task.get("workdir", str(run_dir)), context))

    completed_phases = 0
    failed_phase: str | None = None

    for index, phase in enumerate(task.get("phases", []), start=1):
        start = time.monotonic()
        command = _resolve_template(phase["command"], context)
        completed = subprocess.run(
            command,
            cwd=workdir,
            capture_output=True,
            text=True,
            check=False,
            env={
                **os.environ,
                "META_HARNESS_RUN_DIR": context["run_dir"],
                "META_HARNESS_WORKSPACE_DIR": context["workspace_dir"],
                "META_HARNESS_SOURCE_REPO": context["source_repo"],
            },
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        status = "completed" if completed.returncode == 0 else "failed"
        error_text = (completed.stderr or completed.stdout).strip() or None

        append_trace_event(
            run_dir=run_dir,
            task_id=task_id,
            event={
                "step_id": f"step-{index}",
                "phase": phase["phase"],
                "status": status,
                "latency_ms": latency_ms,
                "error": error_text if status == "failed" else None,
            },
        )

        (task_dir / f"{phase['phase']}.stdout.txt").write_text(
            completed.stdout,
            encoding="utf-8",
        )
        (task_dir / f"{phase['phase']}.stderr.txt").write_text(
            completed.stderr,
            encoding="utf-8",
        )

        if completed.returncode != 0:
            failed_phase = phase["phase"]
            break

        _update_context_from_phase_output(
            context,
            phase["phase"],
            "\n".join(part for part in [completed.stdout, completed.stderr] if part),
        )
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
                "success": success,
                "completed_phases": completed_phases,
                "failed_phase": failed_phase,
                "workdir": str(workdir),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return success
