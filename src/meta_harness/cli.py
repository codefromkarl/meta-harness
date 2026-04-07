from __future__ import annotations

from pathlib import Path
import json
from tempfile import TemporaryDirectory

import typer

from meta_harness.archive import (
    diff_run_records,
    list_run_records,
    load_run_record,
)
from meta_harness.benchmark import run_benchmark, run_benchmark_suite
from meta_harness.candidates import load_candidate_record
from meta_harness.compaction import compact_runs
from meta_harness.config_loader import load_effective_config, load_platform_config
from meta_harness.failure_index import search_failure_signatures
from meta_harness.observation import summarize_observation
from meta_harness.observation_strategies import resolve_observation_strategy
from meta_harness.optimizer import (
    propose_candidate_from_architecture_recommendation,
    propose_candidate_from_failures,
    shadow_run_candidate,
)
from meta_harness.runtime import execute_managed_run, execute_task_set
from meta_harness.services.catalog_service import (
    archive_candidates_payload,
    archive_runs_payload,
    build_candidate_index_payload,
    build_run_index_payload,
    candidate_archive_view_payload,
    candidate_current_view_payload,
    prune_candidates_payload,
    prune_runs_payload,
    run_archive_view_payload,
    run_current_view_payload,
)
from meta_harness.services.benchmark_service import (
    observe_benchmark_payload,
    observe_benchmark_suite_payload,
)
from meta_harness.services.candidate_service import (
    create_candidate_record,
    promote_candidate_record,
)
from meta_harness.services.dataset_service import extract_failure_dataset_to_path
from meta_harness.services.export_service import export_run_trace_to_path
from meta_harness.services.observation_service import (
    observe_once_payload,
    observe_summary_payload,
)
from meta_harness.services.optimize_service import (
    propose_candidate_payload,
    shadow_run_candidate_payload,
)
from meta_harness.services.profile_service import list_profile_names
from meta_harness.services.run_query_service import (
    list_run_summaries,
    load_run_summary,
    search_failure_records,
)
from meta_harness.services.run_service import initialize_run_record
from meta_harness.services.scoring_service import score_run_record
from meta_harness.services.strategy_service import (
    build_strategy_benchmark_spec_payload,
    create_candidate_from_strategy_card_payload,
    inspect_strategy_card_payload,
    run_strategy_benchmark_payload,
    shortlist_strategy_cards_payload,
)
from meta_harness.strategy_cards import write_strategy_benchmark_spec
from meta_harness.strategy_cards import (
    create_candidate_from_strategy_card,
    evaluate_strategy_card_compatibility,
    load_strategy_card,
    run_strategy_benchmark,
    shortlist_strategy_cards,
)
from meta_harness.trace_store import append_trace_event
from meta_harness.workflow_compiler import (
    compile_workflow_spec,
    load_workflow_spec,
    write_compiled_workflow_task_set,
)
from meta_harness.workflow_evaluator_binding import (
    bind_evaluator_packs,
    resolve_workflow_evaluator_packs,
)

# Compatibility aliases for CLI-level monkeypatching during refactors.
archive_runs = archive_runs_payload
prune_runs = prune_runs_payload
archive_candidates = archive_candidates_payload
prune_candidates = prune_candidates_payload

app = typer.Typer(help="Meta-Harness CLI")
profile_app = typer.Typer(help="Profile operations")
run_app = typer.Typer(help="Run operations")
candidate_app = typer.Typer(help="Candidate operations")
optimize_app = typer.Typer(help="Optimization operations")
observe_app = typer.Typer(help="Observation operations")
strategy_app = typer.Typer(help="External strategy operations")
dataset_app = typer.Typer(help="Dataset operations")
workflow_app = typer.Typer(help="Workflow operations")

app.add_typer(profile_app, name="profile")
app.add_typer(run_app, name="run")
app.add_typer(candidate_app, name="candidate")
app.add_typer(optimize_app, name="optimize")
app.add_typer(observe_app, name="observe")
app.add_typer(strategy_app, name="strategy")
app.add_typer(dataset_app, name="dataset")
app.add_typer(workflow_app, name="workflow")


def _cleanup_log_retention(
    config_root: Path,
    project_name: str | None = None,
) -> int | None:
    try:
        platform_config = load_platform_config(config_root, project_name=project_name)
    except FileNotFoundError:
        return None

    archive = platform_config.get("archive")
    if not isinstance(archive, dict):
        return None
    cleanup_logs = archive.get("cleanup_logs")
    if not isinstance(cleanup_logs, dict):
        return None
    retention = cleanup_logs.get("retention")
    if retention is None:
        return None
    return int(retention)


def _archive_config(
    config_root: Path,
    project_name: str | None = None,
) -> dict[str, object]:
    try:
        platform_config = load_platform_config(config_root, project_name=project_name)
    except FileNotFoundError:
        return {}
    archive = platform_config.get("archive")
    return archive if isinstance(archive, dict) else {}


def _compaction_include_artifacts(
    config_root: Path,
    project_name: str | None,
    include_artifacts: bool | None,
) -> bool:
    if include_artifacts is not None:
        return include_artifacts
    archive = _archive_config(config_root, project_name=project_name)
    compaction = archive.get("compaction")
    if not isinstance(compaction, dict):
        return False
    return bool(compaction.get("include_artifacts", False))


def _compaction_cleanup_auxiliary_dirs(
    config_root: Path,
    project_name: str | None,
) -> bool:
    archive = _archive_config(config_root, project_name=project_name)
    compaction = archive.get("compaction")
    if not isinstance(compaction, dict):
        return True
    value = compaction.get("cleanup_auxiliary_dirs")
    if value is None:
        return True
    return bool(value)


def _compaction_compactable_statuses(
    config_root: Path,
    project_name: str | None,
) -> list[str] | None:
    archive = _archive_config(config_root, project_name=project_name)
    compaction = archive.get("compaction")
    if not isinstance(compaction, dict):
        return None
    statuses = compaction.get("compactable_statuses")
    if not isinstance(statuses, list):
        return None
    return [str(status) for status in statuses]


def _workflow_summary(workflow_path: Path) -> dict[str, object]:
    spec = load_workflow_spec(workflow_path)
    return {
        "workflow_id": spec.workflow_id,
        "step_count": len(spec.steps),
        "primitive_ids": sorted({step.primitive_id for step in spec.steps}),
        "evaluator_packs": list(spec.evaluator_packs),
    }


def _bound_workflow_effective_config(
    *,
    config_root: Path,
    profile_name: str,
    project_name: str,
    workflow_path: Path,
) -> dict[str, object]:
    workflow_spec = load_workflow_spec(workflow_path)
    effective_config = load_effective_config(
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
    )
    packs = resolve_workflow_evaluator_packs(config_root, workflow_spec)
    return bind_evaluator_packs(effective_config, packs)


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
) -> None:
    typer.echo(json.dumps(_workflow_summary(workflow)))


@workflow_app.command("compile")
def workflow_compile(
    workflow: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Workflow spec JSON file"
    ),
    output: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Compiled task set JSON output"
    ),
) -> None:
    spec = load_workflow_spec(workflow)
    write_compiled_workflow_task_set(spec, output)
    typer.echo(output)


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
    spec = load_workflow_spec(workflow)
    effective_config = _bound_workflow_effective_config(
        config_root=config_root,
        profile_name=profile,
        project_name=project,
        workflow_path=workflow,
    )
    with TemporaryDirectory(prefix="meta-harness-workflow-run-") as temp_dir:
        task_set_path = Path(temp_dir) / f"{spec.workflow_id}.task_set.json"
        write_compiled_workflow_task_set(spec, task_set_path)
        payload = execute_managed_run(
            runs_root=runs_root,
            profile_name=profile,
            project_name=project,
            effective_config=effective_config,
            task_set_path=task_set_path,
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
    focus: str | None = typer.Option(
        None, help="Optional comparison focus for benchmark"
    ),
    auto_compact_runs: bool = typer.Option(
        True,
        "--auto-compact-runs/--no-auto-compact-runs",
        help="Compact historical run workspaces after workflow benchmark completes",
    ),
) -> None:
    workflow_spec = load_workflow_spec(workflow)
    effective_config = _bound_workflow_effective_config(
        config_root=config_root,
        profile_name=profile,
        project_name=project,
        workflow_path=workflow,
    )
    with TemporaryDirectory(prefix="meta-harness-workflow-benchmark-") as temp_dir:
        task_set_path = Path(temp_dir) / f"{workflow_spec.workflow_id}.task_set.json"
        write_compiled_workflow_task_set(workflow_spec, task_set_path)
        payload = run_benchmark(
            config_root=config_root,
            runs_root=runs_root,
            candidates_root=candidates_root,
            profile_name=profile,
            project_name=project,
            task_set_path=task_set_path,
            spec_path=spec,
            focus=focus,
            effective_config_override=effective_config,
        )
    if auto_compact_runs:
        payload["run_compaction"] = compact_runs(
            runs_root,
            candidates_root=candidates_root,
            include_artifacts=_compaction_include_artifacts(config_root, project, None),
            compactable_statuses=_compaction_compactable_statuses(
                config_root,
                project,
            ),
            cleanup_auxiliary_dirs=_compaction_cleanup_auxiliary_dirs(
                config_root,
                project,
            ),
        )
    typer.echo(json.dumps(payload))


@run_app.command("init")
def run_init(
    profile: str | None = typer.Option(None, help="Workflow profile name"),
    project: str | None = typer.Option(None, help="Project overlay name"),
    candidate_id: str | None = typer.Option(None, help="Candidate id"),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
    candidates_root: Path = typer.Option(
        Path("candidates"), exists=False, file_okay=False
    ),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
) -> None:
    try:
        payload = initialize_run_record(
            config_root=config_root,
            candidates_root=candidates_root,
            runs_root=runs_root,
            profile_name=profile,
            project_name=project,
            candidate_id=candidate_id,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(payload["run_id"])


@run_app.command("trace")
def run_trace(
    run_id: str = typer.Option(..., help="Run id"),
    task_id: str = typer.Option(..., help="Task id"),
    step_id: str = typer.Option(..., help="Step id"),
    phase: str = typer.Option(..., help="Execution phase"),
    status: str = typer.Option(..., help="Trace status"),
    latency_ms: int = typer.Option(0, help="Latency in milliseconds"),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
) -> None:
    append_trace_event(
        run_dir=runs_root / run_id,
        task_id=task_id,
        event={
            "step_id": step_id,
            "phase": phase,
            "status": status,
            "latency_ms": latency_ms,
        },
    )


@run_app.command("score")
def run_score(
    run_id: str = typer.Option(..., help="Run id"),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
    evaluator: list[str] | None = typer.Option(
        None,
        "--evaluator",
        help="Optional evaluator name to run; may be provided multiple times",
    ),
) -> None:
    report = score_run_record(
        runs_root=runs_root,
        run_id=run_id,
        evaluator_names=list(evaluator) if evaluator else None,
    )
    typer.echo(report["composite"])


@run_app.command("execute")
def run_execute(
    run_id: str = typer.Option(..., help="Run id"),
    task_set: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Task set JSON file"
    ),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
    no_score: bool = typer.Option(
        False,
        "--no-score",
        help="Execute task set without writing score_report.json",
    ),
) -> None:
    summary = execute_task_set(runs_root / run_id, task_set)
    if not no_score:
        score_run(runs_root / run_id)
    typer.echo(f"{summary['succeeded']}/{summary['total']}")


@run_app.command("list")
def run_list(
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
) -> None:
    for record in list_run_summaries(runs_root):
        typer.echo(
            f"{record['run_id']}\t{record['profile']}\t{record['project']}\t{record['composite']}"
        )


@run_app.command("index")
def run_index(
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
    candidates_root: Path | None = typer.Option(None, exists=False, file_okay=False),
) -> None:
    typer.echo(
        json.dumps(
            build_run_index_payload(
                runs_root=runs_root,
                candidates_root=candidates_root,
            )
        )
    )


@run_app.command("show")
def run_show(
    run_id: str = typer.Option(..., help="Run id"),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
) -> None:
    record = load_run_summary(runs_root, run_id)
    typer.echo(json.dumps(record, indent=2))


@run_app.command("current")
def run_current(
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
    candidates_root: Path | None = typer.Option(None, exists=False, file_okay=False),
) -> None:
    typer.echo(
        json.dumps(
            run_current_view_payload(
                runs_root=runs_root,
                candidates_root=candidates_root,
            )
        )
    )


@run_app.command("archive-list")
def run_archive_list(
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
    candidates_root: Path | None = typer.Option(None, exists=False, file_okay=False),
) -> None:
    typer.echo(
        json.dumps(
            run_archive_view_payload(
                runs_root=runs_root,
                candidates_root=candidates_root,
            )
        )
    )


@run_app.command("archive")
def run_archive(
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
    project: str | None = typer.Option(None, help="Optional project overlay for archive settings"),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
    candidates_root: Path | None = typer.Option(None, exists=False, file_okay=False),
    archive_root: Path = typer.Option(Path("archive"), exists=False, file_okay=False),
    dry_run: bool = typer.Option(False, help="Preview without moving files"),
    experiment: str | None = typer.Option(None, help="Filter by experiment"),
    benchmark_family: str | None = typer.Option(
        None, help="Filter by benchmark family"
    ),
    status: str | None = typer.Option(None, help="Filter by status"),
) -> None:
    typer.echo(
        json.dumps(
            archive_runs(
                runs_root=runs_root,
                archive_root=archive_root,
                candidates_root=candidates_root,
                cleanup_log_retention=_cleanup_log_retention(
                    config_root,
                    project_name=project,
                ),
                dry_run=dry_run,
                experiment=experiment,
                benchmark_family=benchmark_family,
                status=status,
            )
        )
    )


@run_app.command("prune")
def run_prune(
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
    project: str | None = typer.Option(None, help="Optional project overlay for archive settings"),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
    candidates_root: Path | None = typer.Option(None, exists=False, file_okay=False),
    archive_root: Path = typer.Option(Path("archive"), exists=False, file_okay=False),
    dry_run: bool = typer.Option(False, help="Preview without deleting files"),
    experiment: str | None = typer.Option(None, help="Filter by experiment"),
    benchmark_family: str | None = typer.Option(
        None, help="Filter by benchmark family"
    ),
    status: str | None = typer.Option(None, help="Filter by status"),
) -> None:
    typer.echo(
        json.dumps(
            prune_runs(
                runs_root=runs_root,
                candidates_root=candidates_root,
                archive_root=archive_root,
                cleanup_log_retention=_cleanup_log_retention(
                    config_root,
                    project_name=project,
                ),
                dry_run=dry_run,
                experiment=experiment,
                benchmark_family=benchmark_family,
                status=status,
            )
        )
    )


@run_app.command("compact")
def run_compact(
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
    project: str | None = typer.Option(None, help="Optional project overlay for compaction settings"),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
    candidates_root: Path | None = typer.Option(None, exists=False, file_okay=False),
    dry_run: bool = typer.Option(False, help="Preview without deleting workspace data"),
    experiment: str | None = typer.Option(None, help="Filter by experiment"),
    benchmark_family: str | None = typer.Option(
        None, help="Filter by benchmark family"
    ),
    status: str | None = typer.Option(None, help="Filter by status"),
    include_artifacts: bool | None = typer.Option(
        None,
        "--include-artifacts/--no-include-artifacts",
        help="Also remove artifact payloads except workspace.json/compaction.json",
    ),
) -> None:
    typer.echo(
        json.dumps(
            compact_runs(
                runs_root,
                candidates_root=candidates_root,
                dry_run=dry_run,
                experiment=experiment,
                benchmark_family=benchmark_family,
                status=status,
                include_artifacts=_compaction_include_artifacts(
                    config_root,
                    project,
                    include_artifacts,
                ),
                compactable_statuses=_compaction_compactable_statuses(
                    config_root,
                    project,
                ),
                cleanup_auxiliary_dirs=_compaction_cleanup_auxiliary_dirs(
                    config_root,
                    project,
                ),
            )
        )
    )


@run_app.command("diff")
def run_diff(
    left_run_id: str = typer.Option(..., help="Left run id"),
    right_run_id: str = typer.Option(..., help="Right run id"),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
) -> None:
    diff = diff_run_records(runs_root, left_run_id, right_run_id)
    typer.echo(json.dumps(diff, indent=2))


@run_app.command("failures")
def run_failures(
    query: str = typer.Option(..., help="Failure query"),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
) -> None:
    for record in search_failure_records(runs_root, query):
        typer.echo(
            f"{record['run_id']}\t{record['task_id']}\t{record['phase']}\t{record['signature']}"
        )


@run_app.command("export-trace")
def run_export_trace(
    run_id: str = typer.Option(..., help="Run id"),
    output: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Output JSON path"
    ),
    format: str = typer.Option(
        "otel-json",
        "--format",
        help="Export format: otel-json|phoenix-json|langfuse-json",
    ),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
) -> None:
    try:
        payload = export_run_trace_to_path(
            runs_root=runs_root,
            run_id=run_id,
            output_path=output,
            export_format=format,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(payload["output_path"])


@candidate_app.command("create")
def candidate_create(
    profile: str = typer.Option(..., help="Workflow profile name"),
    project: str = typer.Option(..., help="Project overlay name"),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
    candidates_root: Path = typer.Option(
        Path("candidates"), exists=False, file_okay=False
    ),
    config_patch: Path | None = typer.Option(
        None, exists=False, dir_okay=False, help="Patch JSON"
    ),
    code_patch: Path | None = typer.Option(
        None,
        exists=False,
        dir_okay=False,
        help="Unified diff patch file for code candidate",
    ),
    notes: str = typer.Option("", help="Candidate notes"),
) -> None:
    payload = create_candidate_record(
        profile_name=profile,
        project_name=project,
        config_root=config_root,
        candidates_root=candidates_root,
        config_patch_path=config_patch,
        code_patch_path=code_patch,
        notes=notes,
    )
    typer.echo(payload["candidate_id"])


@candidate_app.command("promote")
def candidate_promote(
    candidate_id: str = typer.Option(..., help="Candidate id"),
    candidates_root: Path = typer.Option(
        Path("candidates"), exists=False, file_okay=False
    ),
) -> None:
    payload = promote_candidate_record(candidates_root, candidate_id)
    typer.echo(payload["candidate_id"])


@candidate_app.command("index")
def candidate_index(
    candidates_root: Path = typer.Option(
        Path("candidates"), exists=False, file_okay=False
    ),
    runs_root: Path | None = typer.Option(
        None,
        exists=False,
        file_okay=False,
        help="Unused compatibility option",
    ),
) -> None:
    typer.echo(
        json.dumps(
            build_candidate_index_payload(
                candidates_root=candidates_root,
                runs_root=runs_root,
            )
        )
    )


@candidate_app.command("current")
def candidate_current(
    candidates_root: Path = typer.Option(
        Path("candidates"), exists=False, file_okay=False
    ),
    runs_root: Path | None = typer.Option(None, exists=False, file_okay=False),
) -> None:
    typer.echo(
        json.dumps(
            candidate_current_view_payload(
                candidates_root=candidates_root,
                runs_root=runs_root,
            )
        )
    )


@candidate_app.command("archive-list")
def candidate_archive_list(
    candidates_root: Path = typer.Option(
        Path("candidates"), exists=False, file_okay=False
    ),
    runs_root: Path | None = typer.Option(None, exists=False, file_okay=False),
) -> None:
    typer.echo(
        json.dumps(
            candidate_archive_view_payload(
                candidates_root=candidates_root,
                runs_root=runs_root,
            )
        )
    )


@candidate_app.command("archive")
def candidate_archive(
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
    project: str | None = typer.Option(None, help="Optional project overlay for archive settings"),
    candidates_root: Path = typer.Option(
        Path("candidates"), exists=False, file_okay=False
    ),
    runs_root: Path | None = typer.Option(None, exists=False, file_okay=False),
    archive_root: Path = typer.Option(Path("archive"), exists=False, file_okay=False),
    dry_run: bool = typer.Option(False, help="Preview without moving files"),
    experiment: str | None = typer.Option(None, help="Filter by experiment"),
    benchmark_family: str | None = typer.Option(
        None, help="Filter by benchmark family"
    ),
) -> None:
    typer.echo(
        json.dumps(
            archive_candidates(
                candidates_root=candidates_root,
                archive_root=archive_root,
                runs_root=runs_root,
                cleanup_log_retention=_cleanup_log_retention(
                    config_root,
                    project_name=project,
                ),
                dry_run=dry_run,
                experiment=experiment,
                benchmark_family=benchmark_family,
            )
        )
    )


@candidate_app.command("prune")
def candidate_prune(
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
    project: str | None = typer.Option(None, help="Optional project overlay for archive settings"),
    candidates_root: Path = typer.Option(
        Path("candidates"), exists=False, file_okay=False
    ),
    runs_root: Path | None = typer.Option(None, exists=False, file_okay=False),
    archive_root: Path = typer.Option(Path("archive"), exists=False, file_okay=False),
    dry_run: bool = typer.Option(False, help="Preview without deleting files"),
    experiment: str | None = typer.Option(None, help="Filter by experiment"),
    benchmark_family: str | None = typer.Option(
        None, help="Filter by benchmark family"
    ),
) -> None:
    typer.echo(
        json.dumps(
            prune_candidates(
                candidates_root=candidates_root,
                runs_root=runs_root,
                archive_root=archive_root,
                cleanup_log_retention=_cleanup_log_retention(
                    config_root,
                    project_name=project,
                ),
                dry_run=dry_run,
                experiment=experiment,
                benchmark_family=benchmark_family,
            )
        )
    )


@optimize_app.command("propose")
def optimize_propose(
    profile: str = typer.Option(..., help="Workflow profile name"),
    project: str = typer.Option(..., help="Project overlay name"),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
    candidates_root: Path = typer.Option(
        Path("candidates"), exists=False, file_okay=False
    ),
) -> None:
    payload = propose_candidate_payload(
        profile_name=profile,
        project_name=project,
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
    )
    typer.echo(payload["candidate_id"])


@optimize_app.command("shadow-run")
def optimize_shadow_run(
    candidate_id: str = typer.Option(..., help="Candidate id"),
    task_set: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Task set JSON file"
    ),
    candidates_root: Path = typer.Option(
        Path("candidates"), exists=False, file_okay=False
    ),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
) -> None:
    payload = shadow_run_candidate_payload(
        candidate_id=candidate_id,
        task_set_path=task_set,
        candidates_root=candidates_root,
        runs_root=runs_root,
    )
    typer.echo(payload["run_id"])


def _should_bootstrap_observation_optimization(
    summary: dict[str, object],
    effective_config: dict[str, object],
    *,
    auto_propose: bool,
) -> tuple[bool, str]:
    if bool(summary.get("needs_optimization")):
        return True, str(summary.get("recommended_focus", "none"))

    optimization = (
        (effective_config.get("optimization") or {})
        if isinstance(effective_config, dict)
        else {}
    )
    proposal_command = (
        optimization.get("proposal_command") if isinstance(optimization, dict) else None
    )
    latest_score = (
        summary.get("score") if isinstance(summary.get("score"), dict) else {}
    )
    latest_score = latest_score if isinstance(latest_score, dict) else {}
    if (
        auto_propose
        and proposal_command
        and not any(
            latest_score.get(section)
            for section in ("maintainability", "architecture", "retrieval")
        )
    ):
        return True, "retrieval"
    return False, str(summary.get("recommended_focus", "none"))


@observe_app.command("summary")
def observe_summary(
    profile: str = typer.Option(..., help="Workflow profile name"),
    project: str = typer.Option(..., help="Project overlay name"),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
    limit: int | None = typer.Option(None, help="Recent history items to include"),
) -> None:
    summary = observe_summary_payload(
        runs_root=runs_root,
        profile_name=profile,
        project_name=project,
        config_root=config_root,
        limit=limit,
    )
    typer.echo(json.dumps(summary))


@observe_app.command("once")
def observe_once(
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
    auto_propose: bool = typer.Option(
        False, help="Automatically create optimization candidate"
    ),
) -> None:
    result = observe_once_payload(
        profile_name=profile,
        project_name=project,
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        task_set_path=task_set,
        auto_propose=auto_propose,
    )

    typer.echo(json.dumps(result))


@observe_app.command("benchmark")
def observe_benchmark(
    profile: str = typer.Option(..., help="Workflow profile name"),
    project: str = typer.Option(..., help="Project overlay name"),
    task_set: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Task set JSON file"
    ),
    spec: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Benchmark spec JSON file"
    ),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
    candidates_root: Path = typer.Option(
        Path("candidates"), exists=False, file_okay=False
    ),
    focus: str | None = typer.Option(
        None, help="Optional comparison focus: indexing|memory|retrieval"
    ),
    auto_compact_runs: bool = typer.Option(
        True,
        "--auto-compact-runs/--no-auto-compact-runs",
        help="Compact historical run workspaces after benchmark completes",
    ),
) -> None:
    payload = observe_benchmark_payload(
        profile_name=profile,
        project_name=project,
        task_set_path=task_set,
        spec_path=spec,
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        focus=focus,
        auto_compact_runs=auto_compact_runs,
        include_artifacts=_compaction_include_artifacts(config_root, project, None),
        compactable_statuses=_compaction_compactable_statuses(
            config_root,
            project,
        ),
        cleanup_auxiliary_dirs=_compaction_cleanup_auxiliary_dirs(
            config_root,
            project,
        ),
        compact_runs_fn=compact_runs,
    )
    typer.echo(json.dumps(payload))


@observe_app.command("benchmark-suite")
def observe_benchmark_suite(
    profile: str = typer.Option(..., help="Workflow profile name"),
    project: str = typer.Option(..., help="Project overlay name"),
    task_set: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Task set JSON file"
    ),
    suite: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Benchmark suite JSON file"
    ),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
    candidates_root: Path = typer.Option(
        Path("candidates"), exists=False, file_okay=False
    ),
    auto_compact_runs: bool = typer.Option(
        True,
        "--auto-compact-runs/--no-auto-compact-runs",
        help="Compact historical run workspaces after benchmark suite completes",
    ),
) -> None:
    payload = observe_benchmark_suite_payload(
        profile_name=profile,
        project_name=project,
        task_set_path=task_set,
        suite_path=suite,
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        auto_compact_runs=auto_compact_runs,
        include_artifacts=_compaction_include_artifacts(config_root, project, None),
        compactable_statuses=_compaction_compactable_statuses(
            config_root,
            project,
        ),
        cleanup_auxiliary_dirs=_compaction_cleanup_auxiliary_dirs(
            config_root,
            project,
        ),
        compact_runs_fn=compact_runs,
    )
    typer.echo(json.dumps(payload))


@strategy_app.command("build-spec")
def strategy_build_spec(
    strategy_cards: list[Path] = typer.Argument(..., exists=False, dir_okay=False),
    experiment: str = typer.Option(..., help="Benchmark experiment name"),
    baseline: str = typer.Option(..., help="Baseline variant name"),
    output: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Output benchmark spec path"
    ),
    repeats: int = typer.Option(1, help="Benchmark repeat count"),
    template: str = typer.Option(
        "generic",
        help="Spec template: generic|contextatlas_indexing_v2",
    ),
) -> None:
    payload = build_strategy_benchmark_spec_payload(
        strategy_card_paths=strategy_cards,
        experiment=experiment,
        baseline_name=baseline,
        output_path=output,
        repeats=repeats,
        template=template,
    )
    typer.echo(json.dumps(payload))


@strategy_app.command("create-candidate")
def strategy_create_candidate(
    strategy_card: Path = typer.Argument(..., exists=False, dir_okay=False),
    profile: str = typer.Option(..., help="Workflow profile name"),
    project: str = typer.Option(..., help="Project overlay name"),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
    candidates_root: Path = typer.Option(
        Path("candidates"), exists=False, file_okay=False
    ),
) -> None:
    try:
        payload = create_candidate_from_strategy_card_payload(
            strategy_card_path=strategy_card,
            profile_name=profile,
            project_name=project,
            config_root=config_root,
            candidates_root=candidates_root,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(2) from exc
    typer.echo(payload["candidate_id"])


@strategy_app.command("benchmark")
def strategy_benchmark(
    strategy_cards: list[Path] = typer.Argument(..., exists=False, dir_okay=False),
    profile: str = typer.Option(..., help="Workflow profile name"),
    project: str = typer.Option(..., help="Project overlay name"),
    task_set: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Task set JSON file"
    ),
    experiment: str = typer.Option(..., help="Benchmark experiment name"),
    baseline: str = typer.Option(..., help="Baseline variant name"),
    template: str = typer.Option(
        "generic",
        help="Spec template: generic|contextatlas_indexing_v2",
    ),
    focus: str | None = typer.Option(None, help="Optional comparison focus"),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
    candidates_root: Path = typer.Option(
        Path("candidates"), exists=False, file_okay=False
    ),
) -> None:
    try:
        payload = run_strategy_benchmark_payload(
            strategy_card_paths=strategy_cards,
            profile_name=profile,
            project_name=project,
            task_set_path=task_set,
            experiment=experiment,
            baseline_name=baseline,
            config_root=config_root,
            runs_root=runs_root,
            candidates_root=candidates_root,
            focus=focus,
            template=template,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(payload))


@strategy_app.command("inspect")
def strategy_inspect(
    strategy_card: Path = typer.Argument(..., exists=False, dir_okay=False),
    profile: str = typer.Option(..., help="Workflow profile name"),
    project: str = typer.Option(..., help="Project overlay name"),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
) -> None:
    payload = inspect_strategy_card_payload(
        strategy_card_path=strategy_card,
        profile_name=profile,
        project_name=project,
        config_root=config_root,
    )
    typer.echo(json.dumps(payload))


@strategy_app.command("shortlist")
def strategy_shortlist(
    strategy_cards: list[Path] = typer.Argument(..., exists=False, dir_okay=False),
    profile: str = typer.Option(..., help="Workflow profile name"),
    project: str = typer.Option(..., help="Project overlay name"),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
) -> None:
    payload = shortlist_strategy_cards_payload(
        strategy_card_paths=strategy_cards,
        profile_name=profile,
        project_name=project,
        config_root=config_root,
    )
    typer.echo(json.dumps(payload))


@dataset_app.command("extract-failures")
def dataset_extract_failures(
    output: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Output dataset JSON path"
    ),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
    profile: str | None = typer.Option(None, help="Optional profile filter"),
    project: str | None = typer.Option(None, help="Optional project filter"),
) -> None:
    payload = extract_failure_dataset_to_path(
        runs_root=runs_root,
        output_path=output,
        profile_name=profile,
        project_name=project,
    )
    typer.echo(payload["output_path"])


if __name__ == "__main__":
    app()
