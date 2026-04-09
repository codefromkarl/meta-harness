from __future__ import annotations

import json
from pathlib import Path

import typer

from meta_harness.cli_support import (
    _cleanup_log_retention,
    _compaction_cleanup_auxiliary_dirs,
    _compaction_compactable_statuses,
    _compaction_include_artifacts,
)
from meta_harness.archive import (
    diff_run_records,
    list_run_records,
    load_run_record,
)
from meta_harness.candidates import load_candidate_record
from meta_harness.failure_index import search_failure_signatures
from meta_harness.optimizer_generation import (
    propose_candidate_from_architecture_recommendation,
    propose_candidate_from_failures,
)
from meta_harness.optimizer_shadow import shadow_run_candidate
from meta_harness.runtime_execution import execute_task_set
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
from meta_harness.services.candidate_service import (
    create_candidate_record,
    create_transfer_candidate_record,
    promote_candidate_record,
)
from meta_harness.services.export_service import export_run_trace_to_path
from meta_harness.services.optimize_service import (
    list_proposals_payload,
    load_proposal_payload,
    materialize_proposal_payload,
    propose_candidate_payload,
    shadow_run_candidate_payload,
)
from meta_harness.services.run_query_service import (
    list_run_summaries,
    load_run_summary,
    search_failure_records,
)
from meta_harness.services.run_service import initialize_run_record
from meta_harness.services.scoring_service import score_run_record
from meta_harness.trace_store import append_trace_event

def archive_runs(*args, **kwargs):
    import meta_harness.cli as root_cli
    return root_cli.archive_runs(*args, **kwargs)


def prune_runs(*args, **kwargs):
    import meta_harness.cli as root_cli
    return root_cli.prune_runs(*args, **kwargs)


def archive_candidates(*args, **kwargs):
    import meta_harness.cli as root_cli
    return root_cli.archive_candidates(*args, **kwargs)


def prune_candidates(*args, **kwargs):
    import meta_harness.cli as root_cli
    return root_cli.prune_candidates(*args, **kwargs)


def compact_runs(*args, **kwargs):
    import meta_harness.cli as root_cli
    return root_cli.compact_runs(*args, **kwargs)


run_app = typer.Typer(help="Run operations")
candidate_app = typer.Typer(help="Candidate operations")
optimize_app = typer.Typer(help="Optimization operations")


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
        score_run_record(runs_root=runs_root, run_id=run_id)
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
    candidates_root: Path | None = typer.Option(
        None, exists=False, file_okay=False, help="Candidates root for candidate lineage projection"
    ),
) -> None:
    try:
        payload = export_run_trace_to_path(
            runs_root=runs_root,
            candidates_root=candidates_root,
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

@candidate_app.command("create-transfer")
def candidate_create_transfer(
    profile: str = typer.Option(..., help="Workflow profile name"),
    project: str = typer.Option(..., help="Project overlay name"),
    method_id: str = typer.Option(..., help="Task method id"),
    source_binding_id: str = typer.Option(..., help="Source Claw binding id"),
    target_binding_id: str = typer.Option(..., help="Target Claw binding id"),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
    candidates_root: Path = typer.Option(
        Path("candidates"), exists=False, file_okay=False
    ),
    method_patch: Path | None = typer.Option(
        None, exists=False, dir_okay=False, help="Optional method patch JSON"
    ),
    binding_patch: Path | None = typer.Option(
        None, exists=False, dir_okay=False, help="Optional binding patch JSON"
    ),
    local_patch: Path | None = typer.Option(
        None, exists=False, dir_okay=False, help="Optional local patch JSON"
    ),
    notes: str = typer.Option("", help="Candidate notes"),
) -> None:
    try:
        payload = create_transfer_candidate_record(
            profile_name=profile,
            project_name=project,
            config_root=config_root,
            candidates_root=candidates_root,
            method_id=method_id,
            source_binding_id=source_binding_id,
            target_binding_id=target_binding_id,
            method_patch_path=method_patch,
            binding_patch_path=binding_patch,
            local_patch_path=local_patch,
            notes=notes,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(payload["candidate_id"])

@candidate_app.command("promote")
def candidate_promote(
    candidate_id: str = typer.Option(..., help="Candidate id"),
    candidates_root: Path = typer.Option(
        Path("candidates"), exists=False, file_okay=False
    ),
    runs_root: Path | None = typer.Option(
        None, exists=False, file_okay=False, help="Optional runs root for evidence lookup"
    ),
    promoted_by: str | None = typer.Option(None, help="Promotion operator"),
    reason: str | None = typer.Option(None, help="Promotion reason"),
    evidence_run_id: list[str] = typer.Option([], help="Evidence run id"),
) -> None:
    payload = promote_candidate_record(
        candidates_root,
        candidate_id,
        promoted_by=promoted_by,
        promotion_reason=reason,
        evidence_run_ids=evidence_run_id,
        runs_root=runs_root,
    )
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
    proposals_root: Path | None = typer.Option(
        None, exists=False, file_okay=False
    ),
    proposal_only: bool = typer.Option(
        False, help="Only create proposal artifact without materializing candidate"
    ),
) -> None:
    payload = propose_candidate_payload(
        profile_name=profile,
        project_name=project,
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        proposals_root=proposals_root,
        proposal_only=proposal_only,
    )
    typer.echo(payload.get("candidate_id") or payload["proposal_id"])

@optimize_app.command("materialize-proposal")
def optimize_materialize_proposal(
    proposal_id: str = typer.Option(..., help="Proposal id"),
    proposals_root: Path = typer.Option(
        Path("proposals"), exists=False, file_okay=False
    ),
    candidates_root: Path = typer.Option(
        Path("candidates"), exists=False, file_okay=False
    ),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
) -> None:
    payload = materialize_proposal_payload(
        proposal_id=proposal_id,
        proposals_root=proposals_root,
        candidates_root=candidates_root,
        config_root=config_root,
    )
    typer.echo(payload["candidate_id"])


@optimize_app.command("list-proposals")
def optimize_list_proposals(
    proposals_root: Path = typer.Option(Path("proposals"), exists=False, file_okay=False),
    profile: str | None = typer.Option(None, help="Optional profile filter"),
    project: str | None = typer.Option(None, help="Optional project filter"),
    status: str | None = typer.Option(None, help="Optional proposal status filter"),
    proposer_kind: str | None = typer.Option(None, help="Optional proposer kind filter"),
    strategy: str | None = typer.Option(None, help="Optional strategy filter"),
) -> None:
    payload = list_proposals_payload(
        proposals_root=proposals_root,
        profile_name=profile,
        project_name=project,
        status=status,
        proposer_kind=proposer_kind,
        strategy=strategy,
    )
    typer.echo(json.dumps(payload))


@optimize_app.command("show-proposal")
def optimize_show_proposal(
    proposal_id: str = typer.Option(..., help="Proposal id"),
    proposals_root: Path = typer.Option(Path("proposals"), exists=False, file_okay=False),
) -> None:
    payload = load_proposal_payload(
        proposals_root=proposals_root,
        proposal_id=proposal_id,
    )
    typer.echo(json.dumps(payload))

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


import meta_harness.cli_optimize_loop  # noqa: E402,F401
