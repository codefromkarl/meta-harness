from __future__ import annotations

from pathlib import Path
import json

import typer

from meta_harness.archive import (
    diff_run_records,
    initialize_run,
    list_run_records,
    load_run_record,
)
from meta_harness.benchmark import run_benchmark, run_benchmark_suite
from meta_harness.catalog import (
    build_candidate_index,
    build_run_index,
    candidate_archive_view,
    candidate_current_view,
    run_archive_view,
    run_current_view,
)
from meta_harness.candidates import (
    create_candidate,
    load_candidate_record,
    promote_candidate,
)
from meta_harness.config_loader import load_effective_config
from meta_harness.datasets import extract_failure_dataset
from meta_harness.exporters import export_run_trace_otel_json
from meta_harness.failure_index import search_failure_signatures
from meta_harness.observation import summarize_observation
from meta_harness.observation_strategies import resolve_observation_strategy
from meta_harness.optimizer import (
    propose_candidate_from_architecture_recommendation,
    propose_candidate_from_failures,
    shadow_run_candidate,
)
from meta_harness.registry import list_profiles
from meta_harness.runtime import execute_managed_run, execute_task_set
from meta_harness.scoring import score_run
from meta_harness.strategy_cards import write_strategy_benchmark_spec
from meta_harness.strategy_cards import (
    create_candidate_from_strategy_card,
    evaluate_strategy_card_compatibility,
    load_strategy_card,
    run_strategy_benchmark,
    shortlist_strategy_cards,
)
from meta_harness.trace_store import append_trace_event

app = typer.Typer(help="Meta-Harness CLI")
profile_app = typer.Typer(help="Profile operations")
run_app = typer.Typer(help="Run operations")
candidate_app = typer.Typer(help="Candidate operations")
optimize_app = typer.Typer(help="Optimization operations")
observe_app = typer.Typer(help="Observation operations")
strategy_app = typer.Typer(help="External strategy operations")
dataset_app = typer.Typer(help="Dataset operations")

app.add_typer(profile_app, name="profile")
app.add_typer(run_app, name="run")
app.add_typer(candidate_app, name="candidate")
app.add_typer(optimize_app, name="optimize")
app.add_typer(observe_app, name="observe")
app.add_typer(strategy_app, name="strategy")
app.add_typer(dataset_app, name="dataset")


@profile_app.command("list")
def profile_list(
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
) -> None:
    for name in list_profiles(config_root):
        typer.echo(name)


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
    if candidate_id:
        candidate = load_candidate_record(candidates_root, candidate_id)
        resolved_profile = candidate["profile"]
        resolved_project = candidate["project"]
        effective_config = candidate["effective_config"]
    else:
        if not profile or not project:
            raise typer.BadParameter(
                "either candidate-id or both profile/project are required"
            )
        resolved_profile = profile
        resolved_project = project
        effective_config = load_effective_config(
            config_root=config_root,
            profile_name=resolved_profile,
            project_name=resolved_project,
        )

    run_id = initialize_run(
        runs_root=runs_root,
        profile_name=resolved_profile,
        project_name=resolved_project,
        effective_config=effective_config,
        candidate_id=candidate_id,
    )
    typer.echo(run_id)


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
    report = score_run(
        runs_root / run_id,
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
    for record in list_run_records(runs_root):
        composite = "-"
        if record["score"] is not None:
            composite = str(record["score"].get("composite", "-"))
        typer.echo(
            f"{record['run_id']}\t{record['profile']}\t{record['project']}\t{composite}"
        )


@run_app.command("index")
def run_index(
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
    candidates_root: Path | None = typer.Option(None, exists=False, file_okay=False),
) -> None:
    typer.echo(json.dumps(build_run_index(runs_root, candidates_root=candidates_root)))


@run_app.command("show")
def run_show(
    run_id: str = typer.Option(..., help="Run id"),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
) -> None:
    record = load_run_record(runs_root, run_id)
    typer.echo(json.dumps(record, indent=2))


@run_app.command("current")
def run_current(
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
    candidates_root: Path | None = typer.Option(None, exists=False, file_okay=False),
) -> None:
    typer.echo(json.dumps(run_current_view(runs_root, candidates_root=candidates_root)))


@run_app.command("archive-list")
def run_archive_list(
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
    candidates_root: Path | None = typer.Option(None, exists=False, file_okay=False),
) -> None:
    typer.echo(json.dumps(run_archive_view(runs_root, candidates_root=candidates_root)))


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
    for record in search_failure_signatures(runs_root, query):
        typer.echo(
            f"{record['run_id']}\t{record['task_id']}\t{record['phase']}\t{record['signature']}"
        )


@run_app.command("export-trace")
def run_export_trace(
    run_id: str = typer.Option(..., help="Run id"),
    output: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Output JSON path"
    ),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
) -> None:
    payload = export_run_trace_otel_json(runs_root / run_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    typer.echo(str(output))


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
    patch = None
    if config_patch is not None:
        patch = json.loads(config_patch.read_text(encoding="utf-8"))
    candidate_id = create_candidate(
        candidates_root=candidates_root,
        config_root=config_root,
        profile_name=profile,
        project_name=project,
        config_patch=patch,
        code_patch_path=code_patch,
        notes=notes,
    )
    typer.echo(candidate_id)


@candidate_app.command("promote")
def candidate_promote(
    candidate_id: str = typer.Option(..., help="Candidate id"),
    candidates_root: Path = typer.Option(
        Path("candidates"), exists=False, file_okay=False
    ),
) -> None:
    promote_candidate(candidates_root, candidate_id)
    typer.echo(candidate_id)


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
    typer.echo(json.dumps(build_candidate_index(candidates_root, runs_root=runs_root)))


@candidate_app.command("current")
def candidate_current(
    candidates_root: Path = typer.Option(
        Path("candidates"), exists=False, file_okay=False
    ),
    runs_root: Path | None = typer.Option(None, exists=False, file_okay=False),
) -> None:
    typer.echo(json.dumps(candidate_current_view(candidates_root, runs_root=runs_root)))


@candidate_app.command("archive-list")
def candidate_archive_list(
    candidates_root: Path = typer.Option(
        Path("candidates"), exists=False, file_okay=False
    ),
    runs_root: Path | None = typer.Option(None, exists=False, file_okay=False),
) -> None:
    typer.echo(json.dumps(candidate_archive_view(candidates_root, runs_root=runs_root)))


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
    candidate_id = propose_candidate_from_failures(
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        profile_name=profile,
        project_name=project,
    )
    typer.echo(candidate_id)


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
    run_id = shadow_run_candidate(
        candidates_root=candidates_root,
        runs_root=runs_root,
        candidate_id=candidate_id,
        task_set_path=task_set,
    )
    typer.echo(run_id)


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
    summary = summarize_observation(
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
    effective_config = load_effective_config(
        config_root=config_root,
        profile_name=profile,
        project_name=project,
    )
    execution = execute_managed_run(
        runs_root=runs_root,
        profile_name=profile,
        project_name=project,
        effective_config=effective_config,
        task_set_path=task_set,
    )
    run_id = str(execution["run_id"])
    score = execution["score"]
    summary = summarize_observation(
        runs_root=runs_root,
        profile_name=profile,
        project_name=project,
        config_root=config_root,
    )

    result: dict[str, object] = {
        "run_id": run_id,
        "score": score,
        "needs_optimization": bool(summary.get("needs_optimization")),
        "recommended_focus": summary.get("recommended_focus", "none"),
        "architecture_recommendation": summary.get("architecture_recommendation"),
        "triggered_optimization": False,
    }

    needs_optimization, recommended_focus = _should_bootstrap_observation_optimization(
        {
            **summary,
            "score": score,
        },
        effective_config,
        auto_propose=auto_propose,
    )
    result["needs_optimization"] = needs_optimization
    result["recommended_focus"] = recommended_focus
    if result.get("architecture_recommendation") is None and needs_optimization:
        strategy = resolve_observation_strategy(config_root, profile, project)
        thresholds = strategy.load_thresholds(config_root, profile, project)
        result["architecture_recommendation"] = strategy.architecture_recommendation(
            score,
            thresholds,
            focus_override=recommended_focus,
        )

    if auto_propose and needs_optimization:
        optimization = (
            (effective_config.get("optimization") or {})
            if isinstance(effective_config, dict)
            else {}
        )
        proposal_command = (
            optimization.get("proposal_command")
            if isinstance(optimization, dict)
            else None
        )
        if proposal_command:
            candidate_id = propose_candidate_from_failures(
                config_root=config_root,
                runs_root=runs_root,
                candidates_root=candidates_root,
                profile_name=profile,
                project_name=project,
            )
        else:
            architecture_recommendation = result.get("architecture_recommendation")
            if not isinstance(architecture_recommendation, dict):
                raise RuntimeError(
                    "auto-propose requires proposal_command or architecture_recommendation"
                )
            candidate_id = propose_candidate_from_architecture_recommendation(
                config_root=config_root,
                candidates_root=candidates_root,
                profile_name=profile,
                project_name=project,
                source_run_ids=[run_id],
                architecture_recommendation=architecture_recommendation,
            )
        result["triggered_optimization"] = True
        result["candidate_id"] = candidate_id

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
) -> None:
    payload = run_benchmark(
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        profile_name=profile,
        project_name=project,
        task_set_path=task_set,
        spec_path=spec,
        focus=focus,
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
) -> None:
    payload = run_benchmark_suite(
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        profile_name=profile,
        project_name=project,
        task_set_path=task_set,
        suite_path=suite,
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
    payload = write_strategy_benchmark_spec(
        output_path=output,
        experiment=experiment,
        baseline_name=baseline,
        strategy_card_paths=strategy_cards,
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
        candidate_id = create_candidate_from_strategy_card(
            config_root=config_root,
            candidates_root=candidates_root,
            profile_name=profile,
            project_name=project,
            strategy_card_path=strategy_card,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(2) from exc
    typer.echo(candidate_id)


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
        payload = run_strategy_benchmark(
            config_root=config_root,
            runs_root=runs_root,
            candidates_root=candidates_root,
            profile_name=profile,
            project_name=project,
            task_set_path=task_set,
            experiment=experiment,
            baseline_name=baseline,
            strategy_card_paths=strategy_cards,
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
    payload = evaluate_strategy_card_compatibility(
        load_strategy_card(strategy_card),
        config_root=config_root,
        profile_name=profile,
        project_name=project,
        strategy_card_path=strategy_card,
    )
    typer.echo(json.dumps(payload))


@strategy_app.command("shortlist")
def strategy_shortlist(
    strategy_cards: list[Path] = typer.Argument(..., exists=False, dir_okay=False),
    profile: str = typer.Option(..., help="Workflow profile name"),
    project: str = typer.Option(..., help="Project overlay name"),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
) -> None:
    payload = shortlist_strategy_cards(
        strategy_card_paths=strategy_cards,
        config_root=config_root,
        profile_name=profile,
        project_name=project,
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
    payload = extract_failure_dataset(
        runs_root,
        profile_name=profile,
        project_name=project,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    typer.echo(str(output))


if __name__ == "__main__":
    app()
