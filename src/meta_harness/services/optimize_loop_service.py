from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from meta_harness.config_loader import load_effective_config
from meta_harness.loop import SearchLoopRequest, run_search_loop
from meta_harness.proposers import build_proposer
from meta_harness.task_plugins import get_task_plugin


def _resolve_task_plugin(plugin_id: str):
    resolved_id = plugin_id
    if plugin_id in {"", "default"}:
        resolved_id = "web_scrape"
    return get_task_plugin(resolved_id)


def _resolve_proposer(
    *,
    proposer_id: str,
    effective_config: dict[str, Any],
):
    return build_proposer(proposer_id, effective_config=effective_config)


def build_search_loop_request(
    *,
    profile_name: str,
    project_name: str,
    task_set_path: Path,
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    reports_root: Path | None = None,
    proposals_root: Path | None = None,
    loop_id: str | None = None,
    plugin_id: str | None = None,
    proposer_id: str | None = None,
    max_iterations: int = 8,
    focus: str | None = None,
    evaluation_mode: str = "auto",
):
    return SearchLoopRequest(
        profile_name=profile_name,
        project_name=project_name,
        task_set_path=Path(task_set_path),
        config_root=Path(config_root),
        runs_root=Path(runs_root),
        candidates_root=Path(candidates_root),
        loop_id=loop_id,
        reports_root=Path(reports_root) if reports_root is not None else None,
        proposals_root=Path(proposals_root) if proposals_root is not None else None,
        task_plugin_id=plugin_id,
        proposer_id=proposer_id,
        max_iterations=max_iterations,
        focus=focus,
        evaluation_mode=evaluation_mode,
    )


def optimize_loop_payload(
    *,
    profile_name: str,
    project_name: str,
    task_set_path: Path,
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    reports_root: Path | None = None,
    proposals_root: Path | None = None,
    loop_id: str | None = None,
    plugin_id: str = "default",
    proposer_id: str = "heuristic",
    max_iterations: int = 8,
    focus: str | None = None,
    run_search_loop_fn: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    effective_config = load_effective_config(
        config_root=Path(config_root),
        profile_name=profile_name,
        project_name=project_name,
    )
    runner = run_search_loop_fn or run_search_loop
    search_request = build_search_loop_request(
        profile_name=profile_name,
        project_name=project_name,
        task_set_path=task_set_path,
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        reports_root=reports_root,
        proposals_root=proposals_root,
        loop_id=loop_id,
        plugin_id=plugin_id,
        proposer_id=proposer_id,
        max_iterations=max_iterations,
        focus=focus,
    )
    task_plugin = _resolve_task_plugin(plugin_id)
    proposer = _resolve_proposer(
        proposer_id=proposer_id,
        effective_config=effective_config,
    )
    result = runner(
        search_request,
        task_plugin=task_plugin,
        proposer=proposer,
        reports_root=search_request.reports_root,
        proposals_root=Path(proposals_root) if proposals_root is not None else None,
    )
    if isinstance(result, dict):
        payload = dict(result)
    else:
        payload = result.model_dump() if hasattr(result, "model_dump") else {"result": result}
    payload.setdefault("loop_request", search_request.model_dump())
    loop_request = payload.get("loop_request")
    if isinstance(loop_request, dict) and loop_id is not None:
        loop_request.setdefault("loop_id", loop_id)
    if loop_id is not None and payload.get("loop_id") is None:
        payload["loop_id"] = loop_id
    return payload
