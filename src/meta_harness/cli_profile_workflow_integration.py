from __future__ import annotations

import json
from pathlib import Path

import typer

from meta_harness.cli_support import (
    _compaction_cleanup_auxiliary_dirs,
    _compaction_compactable_statuses,
    _compaction_include_artifacts,
)
from meta_harness.services.integration_service import (
    analyze_integration_payload,
    review_harness_payload,
    review_integration_payload,
    scaffold_harness_payload,
    scaffold_integration_payload,
)
from meta_harness.services.profile_service import list_profile_names
from meta_harness.services.method_service import (
    inspect_method_binding_payload,
    plan_method_transfer_payload,
)
from meta_harness.services.workflow_service import (
    benchmark_workflow_payload,
    compile_workflow_payload,
    inspect_workflow_payload,
    run_workflow_payload,
)


def execute_managed_run(*args, **kwargs):
    import meta_harness.cli as root_cli
    return root_cli.execute_managed_run(*args, **kwargs)


def run_benchmark(*args, **kwargs):
    import meta_harness.cli as root_cli
    return root_cli.run_benchmark(*args, **kwargs)


def compact_runs(*args, **kwargs):
    import meta_harness.cli as root_cli
    return root_cli.compact_runs(*args, **kwargs)


def benchmark_harness_payload(*args, **kwargs):
    import meta_harness.cli as root_cli
    return root_cli.benchmark_harness_payload(*args, **kwargs)


def benchmark_integration_payload(*args, **kwargs):
    import meta_harness.cli as root_cli
    return root_cli.benchmark_integration_payload(*args, **kwargs)


def harness_outer_loop_payload(*args, **kwargs):
    import meta_harness.cli as root_cli
    return root_cli.harness_outer_loop_payload(*args, **kwargs)


profile_app = typer.Typer(help="Profile operations")
workflow_app = typer.Typer(help="Workflow operations")
integration_app = typer.Typer(help="Integration analysis operations")
method_app = typer.Typer(help="Task method and transfer operations")


@profile_app.command("list")
def profile_list(
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
) -> None:
    for name in list_profile_names(config_root):
        typer.echo(name)

@workflow_app.command("inspect")
def workflow_inspect(
    workflow: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Workflow spec JSON file"
    ),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
) -> None:
    try:
        payload = inspect_workflow_payload(
            workflow_path=workflow,
            config_root=config_root,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(payload))

@workflow_app.command("compile")
def workflow_compile(
    workflow: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Workflow spec JSON file"
    ),
    output: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Compiled task set JSON output"
    ),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
) -> None:
    try:
        payload = compile_workflow_payload(
            workflow_path=workflow,
            output_path=output,
            config_root=config_root,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(2) from exc
    typer.echo(payload["output_path"])

@workflow_app.command("run")
def workflow_run(
    workflow: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Workflow spec JSON file"
    ),
    profile: str = typer.Option(..., help="Workflow profile name"),
    project: str = typer.Option(..., help="Project overlay name"),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
    candidates_root: Path = typer.Option(
        Path("candidates"), exists=False, file_okay=False
    ),
) -> None:
    del candidates_root
    payload = run_workflow_payload(
        workflow_path=workflow,
        profile_name=profile,
        project_name=project,
        config_root=config_root,
        runs_root=runs_root,
        execute_managed_run_fn=execute_managed_run,
    )
    typer.echo(json.dumps(payload))

@workflow_app.command("benchmark")
def workflow_benchmark(
    workflow: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Workflow spec JSON file"
    ),
    profile: str = typer.Option(..., help="Workflow profile name"),
    project: str = typer.Option(..., help="Project overlay name"),
    spec: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Benchmark spec JSON file"
    ),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
    candidates_root: Path = typer.Option(
        Path("candidates"), exists=False, file_okay=False
    ),
    reports_root: Path = typer.Option(Path("reports"), exists=False, file_okay=False),
    focus: str | None = typer.Option(
        None, help="Optional comparison focus for benchmark"
    ),
    auto_compact_runs: bool = typer.Option(
        True,
        "--auto-compact-runs/--no-auto-compact-runs",
        help="Compact historical run workspaces after workflow benchmark completes",
    ),
    gate_policy: str | None = typer.Option(
        None,
        help="Optional gate policy id to auto-evaluate after workflow benchmark",
    ),
) -> None:
    payload = benchmark_workflow_payload(
        workflow_path=workflow,
        profile_name=profile,
        project_name=project,
        spec_path=spec,
        reports_root=reports_root,
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        focus=focus,
        auto_compact_runs=auto_compact_runs,
        include_artifacts=_compaction_include_artifacts(config_root, project, None),
        compactable_statuses=_compaction_compactable_statuses(config_root, project),
        cleanup_auxiliary_dirs=_compaction_cleanup_auxiliary_dirs(config_root, project),
        gate_policy_id=gate_policy,
        run_benchmark_fn=run_benchmark,
        compact_runs_fn=compact_runs,
    )
    typer.echo(json.dumps(payload))

@integration_app.command("analyze")
def integration_analyze(
    intent: str | None = typer.Option(None, help="Natural language integration intent"),
    target_project: Path | None = typer.Option(
        None,
        exists=False,
        file_okay=False,
        help="Target project root path",
    ),
    primitive_id: str | None = typer.Option(None, help="Target primitive id"),
    workflow: list[Path] = typer.Option(
        [],
        exists=False,
        dir_okay=False,
        help="Workflow definition path (JSON/YAML)",
    ),
    user_goal: str = typer.Option("", help="Optional explicit user goal"),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
    reports_root: Path = typer.Option(Path("reports"), exists=False, file_okay=False),
) -> None:
    try:
        payload = analyze_integration_payload(
            config_root=config_root,
            reports_root=reports_root,
            intent_text=intent,
            target_project_path=target_project,
            primitive_id=primitive_id,
            workflow_paths=workflow,
            user_goal=user_goal,
        )
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(payload))

@integration_app.command("scaffold")
def integration_scaffold(
    spec: Path | None = typer.Option(
        None,
        exists=False,
        dir_okay=False,
        help="Integration spec JSON file",
    ),
    harness_spec: Path | None = typer.Option(
        None,
        exists=False,
        dir_okay=False,
        help="Harness spec JSON file",
    ),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
) -> None:
    try:
        if spec is not None:
            payload = scaffold_integration_payload(
                config_root=config_root,
                spec_path=spec,
            )
        elif harness_spec is not None:
            payload = scaffold_harness_payload(
                config_root=config_root,
                harness_spec_path=harness_spec,
            )
        else:
            raise ValueError("either --spec or --harness-spec is required")
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(payload))

@integration_app.command("review")
def integration_review(
    spec: Path | None = typer.Option(
        None,
        exists=False,
        dir_okay=False,
        help="Integration spec JSON file",
    ),
    harness_spec: Path | None = typer.Option(
        None,
        exists=False,
        dir_okay=False,
        help="Harness spec JSON file",
    ),
    reviewer: str = typer.Option(..., help="Reviewer identity"),
    approve_check: list[str] = typer.Option([], help="Approved manual check entry"),
    approve_all_checks: bool = typer.Option(
        False,
        "--approve-all-checks",
        help="Approve every manual check in the spec",
    ),
    overrides: Path | None = typer.Option(
        None,
        exists=False,
        dir_okay=False,
        help="Optional reviewed spec override JSON",
    ),
    notes: str = typer.Option("", help="Optional review notes"),
    activate_binding: bool = typer.Option(
        False,
        "--activate-binding",
        help="Mark generated binding as activated after all checks are approved",
    ),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
) -> None:
    try:
        if spec is not None:
            payload = review_integration_payload(
                config_root=config_root,
                spec_path=spec,
                reviewer=reviewer,
                approve_checks=approve_check,
                approve_all_checks=approve_all_checks,
                overrides_path=overrides,
                notes=notes,
                activate_binding=activate_binding,
            )
        elif harness_spec is not None:
            payload = review_harness_payload(
                harness_spec_path=harness_spec,
                reviewer=reviewer,
                approve_checks=approve_check,
                approve_all_checks=approve_all_checks,
                overrides_path=overrides,
                notes=notes,
            )
        else:
            raise ValueError("either --spec or --harness-spec is required")
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(payload))

@integration_app.command("benchmark")
def integration_benchmark(
    spec: Path | None = typer.Option(
        None,
        exists=False,
        dir_okay=False,
        help="Integration spec JSON file",
    ),
    harness_spec: Path | None = typer.Option(
        None,
        exists=False,
        dir_okay=False,
        help="Harness spec JSON file",
    ),
    profile: str = typer.Option(..., help="Workflow profile name"),
    project: str = typer.Option(..., help="Project overlay name"),
    task_set: Path = typer.Option(
        ...,
        exists=False,
        dir_okay=False,
        help="Task set JSON file",
    ),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
    candidates_root: Path = typer.Option(Path("candidates"), exists=False, file_okay=False),
    reports_root: Path = typer.Option(Path("reports"), exists=False, file_okay=False),
    focus: str | None = typer.Option(None, help="Optional benchmark focus"),
) -> None:
    try:
        if spec is not None:
            payload = benchmark_integration_payload(
                config_root=config_root,
                reports_root=reports_root,
                runs_root=runs_root,
                candidates_root=candidates_root,
                spec_path=spec,
                profile_name=profile,
                project_name=project,
                task_set_path=task_set,
                focus=focus,
            )
        elif harness_spec is not None:
            payload = benchmark_harness_payload(
                config_root=config_root,
                reports_root=reports_root,
                runs_root=runs_root,
                candidates_root=candidates_root,
                harness_spec_path=harness_spec,
                profile_name=profile,
                project_name=project,
                task_set_path=task_set,
                focus=focus,
            )
        else:
            raise ValueError("either --spec or --harness-spec is required")
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(payload))

@integration_app.command("outer-loop")
def integration_outer_loop(
    harness_spec: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Harness spec JSON file"
    ),
    proposal: list[Path] = typer.Option(
        [],
        "--proposal",
        exists=False,
        dir_okay=False,
        help="Candidate harness proposal JSON file",
    ),
    profile: str = typer.Option(..., help="Workflow profile name"),
    project: str = typer.Option(..., help="Project overlay name"),
    task_set: Path = typer.Option(
        ...,
        exists=False,
        dir_okay=False,
        help="Task set JSON file",
    ),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
    candidates_root: Path = typer.Option(
        Path("candidates"), exists=False, file_okay=False
    ),
    reports_root: Path = typer.Option(Path("reports"), exists=False, file_okay=False),
    iteration_id: str | None = typer.Option(None, help="Optional iteration id"),
    focus: str | None = typer.Option(None, help="Optional benchmark focus"),
) -> None:
    try:
        payload = harness_outer_loop_payload(
            config_root=config_root,
            reports_root=reports_root,
            runs_root=runs_root,
            candidates_root=candidates_root,
            harness_spec_path=harness_spec,
            profile_name=profile,
            project_name=project,
            task_set_path=task_set,
            candidate_harness_patches=[
                json.loads(path.read_text(encoding="utf-8")) for path in proposal
            ],
            iteration_id=iteration_id,
            focus=focus,
        )
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(payload))

@method_app.command("inspect")
def method_inspect(
    method_id: str = typer.Option(..., help="Task method id"),
    binding_id: str = typer.Option(..., help="Claw binding id"),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
) -> None:
    try:
        payload = inspect_method_binding_payload(
            config_root=config_root,
            method_id=method_id,
            binding_id=binding_id,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(payload))

@method_app.command("transfer-plan")
def method_transfer_plan(
    method_id: str = typer.Option(..., help="Task method id"),
    source_binding_id: str = typer.Option(..., help="Source Claw binding id"),
    target_binding_id: str = typer.Option(..., help="Target Claw binding id"),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
    method_patch: Path | None = typer.Option(
        None, exists=False, dir_okay=False, help="Optional method patch JSON"
    ),
    binding_patch: Path | None = typer.Option(
        None, exists=False, dir_okay=False, help="Optional binding patch JSON"
    ),
    local_patch: Path | None = typer.Option(
        None, exists=False, dir_okay=False, help="Optional local patch JSON"
    ),
) -> None:
    try:
        payload = plan_method_transfer_payload(
            config_root=config_root,
            method_id=method_id,
            source_binding_id=source_binding_id,
            target_binding_id=target_binding_id,
            method_patch_path=method_patch,
            binding_patch_path=binding_patch,
            local_patch_path=local_patch,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(payload))
