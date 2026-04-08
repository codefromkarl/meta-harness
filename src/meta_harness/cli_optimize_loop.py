from __future__ import annotations

from pathlib import Path

import typer

from meta_harness.cli_run_candidate_optimize import optimize_app
from meta_harness.services.optimize_loop_service import optimize_loop_payload


@optimize_app.command("loop")
def optimize_loop(
    profile: str = typer.Option(..., help="Workflow profile name"),
    project: str = typer.Option(..., help="Project overlay name"),
    task_set: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Task set JSON file"
    ),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
    candidates_root: Path = typer.Option(
        Path("candidates"), exists=False, file_okay=False
    ),
    proposals_root: Path = typer.Option(
        Path("proposals"), exists=False, file_okay=False
    ),
    reports_root: Path = typer.Option(Path("reports"), exists=False, file_okay=False),
    loop_id: str | None = typer.Option(None, help="Optional loop id"),
    plugin_id: str = typer.Option("default", help="Task plugin id"),
    proposer_id: str = typer.Option("heuristic", help="Proposer id"),
    max_iterations: int = typer.Option(8, help="Maximum iteration count"),
    focus: str | None = typer.Option(None, help="Optional optimization focus"),
) -> None:
    payload = optimize_loop_payload(
        profile_name=profile,
        project_name=project,
        task_set_path=task_set,
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        proposals_root=proposals_root,
        reports_root=reports_root,
        loop_id=loop_id,
        plugin_id=plugin_id,
        proposer_id=proposer_id,
        max_iterations=max_iterations,
        focus=focus,
    )
    typer.echo(
        payload.get("loop_id")
        or payload.get("best_candidate_id")
        or payload.get("best_run_id")
        or ""
    )
