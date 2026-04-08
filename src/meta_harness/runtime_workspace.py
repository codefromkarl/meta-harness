from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from meta_harness.config_loader import merge_dicts
from meta_harness.schemas import WorkspaceArtifact
from meta_harness.template_utils import (
    _build_template_context,
    _resolve_template,
)

_DEFAULT_WORKSPACE_IGNORE = (
    ".git",
    "node_modules",
    "runs",
    "candidates",
    "archive",
    "reports",
    "__pycache__",
    ".pytest_cache",
)


def _runtime_subprocess():
    import meta_harness.runtime as runtime_root
    return runtime_root.subprocess


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
    _validate_workspace_copy_source(copy_source_repo, workspace_dir)
    _copy_workspace_tree(copy_source_repo, workspace_dir, ignore_patterns)

    patch_applied = False
    patch_already_present = False
    code_patch_artifact = None
    if code_patch_path is not None:
        code_patch_artifact = code_patch_path.name
        completed = _runtime_subprocess().run(
            ["git", "apply", str(code_patch_path)],
            cwd=workspace_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            reverse_check = _runtime_subprocess().run(
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
    _validate_workspace_copy_source(source_repo, snapshot_dir)
    _copy_workspace_tree(source_repo, snapshot_dir, ignore_patterns)
    return snapshot_dir.resolve()

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


def _validate_workspace_copy_source(source_repo: Path, destination_dir: Path) -> None:
    resolved_source = source_repo.expanduser().resolve()
    resolved_destination = destination_dir.expanduser().resolve()
    if resolved_source == resolved_destination or resolved_source in resolved_destination.parents:
        raise ValueError(
            "workspace source_repo must not contain the destination run or snapshot directory"
        )

def _seed_run_root_state(run_dir: Path, source_run_dir: Path) -> None:
    protected = {"run_metadata.json", "effective_config.json", "score_report.json"}
    if not source_run_dir.exists():
        return
    for path in source_run_dir.iterdir():
        if not path.is_file() or path.name in protected:
            continue
        shutil.copy2(path, run_dir / path.name)
