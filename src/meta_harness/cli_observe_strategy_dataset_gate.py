from __future__ import annotations

import json
from pathlib import Path

import typer

from meta_harness.cli_support import (
    _compaction_cleanup_auxiliary_dirs,
    _compaction_compactable_statuses,
    _compaction_include_artifacts,
    _should_bootstrap_observation_optimization,
)
from meta_harness.observation import summarize_observation
from meta_harness.observation_strategies import resolve_observation_strategy
from meta_harness.services.benchmark_service import (
    observe_benchmark_payload,
    observe_benchmark_suite_payload,
)
from meta_harness.services.dataset_service import (
    build_task_set_dataset_to_path,
    derive_dataset_split_to_path,
    extract_failure_dataset_to_path,
    ingest_dataset_annotations_to_path,
    promote_dataset_version,
)
from meta_harness.services.gate_service import (
    evaluate_gate_policy_from_paths,
    list_gate_history,
    list_gate_results,
    load_gate_result,
)
from meta_harness.services.observation_service import (
    observe_once_payload,
    observe_summary_payload,
)
from meta_harness.services.profile_service import list_profile_names
from meta_harness.services.strategy_service import (
    build_web_scrape_audit_benchmark_spec_payload,
    build_web_scrape_audit_report_payload,
    build_strategy_benchmark_spec_payload,
    create_candidate_from_strategy_card_payload,
    inspect_strategy_card_payload,
    recommend_web_scrape_strategy_cards_payload,
    run_strategy_benchmark_payload,
    shortlist_strategy_cards_payload,
)
from meta_harness.strategy_cards_core import (
    evaluate_strategy_card_compatibility,
    load_strategy_card,
    shortlist_strategy_cards,
)
from meta_harness.strategy_cards_execution import (
    create_candidate_from_strategy_card,
    run_strategy_benchmark,
    write_strategy_benchmark_spec,
)


def compact_runs(*args, **kwargs):
    import meta_harness.cli as root_cli
    return root_cli.compact_runs(*args, **kwargs)


observe_app = typer.Typer(help="Observation operations")
strategy_app = typer.Typer(help="External strategy operations")
dataset_app = typer.Typer(help="Dataset operations")
gate_app = typer.Typer(help="Gate policy operations")


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
    method_id: str | None = typer.Option(
        None, help="Task method id for transfer-aware auto-propose"
    ),
    target_binding_id: str | None = typer.Option(
        None,
        help="Target Claw binding id for transfer-aware auto-propose and shadow-run",
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
        method_id=method_id,
        target_binding_id=target_binding_id,
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
    reports_root: Path = typer.Option(Path("reports"), exists=False, file_okay=False),
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
        reports_root=reports_root,
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
    reports_root: Path = typer.Option(Path("reports"), exists=False, file_okay=False),
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
        reports_root=reports_root,
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
        help="Spec template: generic",
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
        help="Spec template: generic",
    ),
    focus: str | None = typer.Option(None, help="Optional comparison focus"),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
    runs_root: Path = typer.Option(Path("runs"), exists=False, file_okay=False),
    candidates_root: Path = typer.Option(
        Path("candidates"), exists=False, file_okay=False
    ),
    reports_root: Path = typer.Option(Path("reports"), exists=False, file_okay=False),
) -> None:
    try:
        payload = run_strategy_benchmark_payload(
            strategy_card_paths=strategy_cards,
            profile_name=profile,
            project_name=project,
            task_set_path=task_set,
            experiment=experiment,
            baseline_name=baseline,
            reports_root=reports_root,
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

@strategy_app.command("recommend-web-scrape")
def strategy_recommend_web_scrape(
    page_profile: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Page profile JSON file"
    ),
    workload_profile: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Workload profile JSON file"
    ),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
    limit: int = typer.Option(4, help="Maximum recommendation count"),
    strategy_cards: list[Path] = typer.Argument([], exists=False, dir_okay=False),
) -> None:
    payload = recommend_web_scrape_strategy_cards_payload(
        page_profile=json.loads(page_profile.read_text(encoding="utf-8")),
        workload_profile=json.loads(workload_profile.read_text(encoding="utf-8")),
        config_root=config_root,
        strategy_card_paths=strategy_cards or None,
        limit=limit,
    )
    typer.echo(json.dumps(payload))

@strategy_app.command("audit-web-scrape")
def strategy_audit_web_scrape(
    page_profile: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Page profile JSON file"
    ),
    workload_profile: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Workload profile JSON file"
    ),
    benchmark_report: Path | None = typer.Option(
        None, exists=False, dir_okay=False, help="Optional benchmark report JSON file"
    ),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
    limit: int = typer.Option(4, help="Maximum recommendation count"),
    strategy_cards: list[Path] = typer.Argument([], exists=False, dir_okay=False),
) -> None:
    payload = build_web_scrape_audit_report_payload(
        page_profile=json.loads(page_profile.read_text(encoding="utf-8")),
        workload_profile=json.loads(workload_profile.read_text(encoding="utf-8")),
        config_root=config_root,
        strategy_card_paths=strategy_cards or None,
        limit=limit,
        benchmark_report_path=benchmark_report,
    )
    typer.echo(json.dumps(payload))

@strategy_app.command("build-web-scrape-audit-spec")
def strategy_build_web_scrape_audit_spec(
    page_profile: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Page profile JSON file"
    ),
    workload_profile: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Workload profile JSON file"
    ),
    output: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Output benchmark spec JSON file"
    ),
    config_root: Path = typer.Option(Path("configs"), exists=False, file_okay=False),
    baseline: str = typer.Option("current_strategy", help="Baseline variant name"),
    experiment: str = typer.Option("web_scrape_audit", help="Benchmark experiment name"),
    limit: int = typer.Option(4, help="Maximum recommendation count"),
    repeats: int = typer.Option(1, help="Benchmark repeat count"),
    strategy_cards: list[Path] = typer.Argument([], exists=False, dir_okay=False),
) -> None:
    payload = build_web_scrape_audit_benchmark_spec_payload(
        page_profile=json.loads(page_profile.read_text(encoding="utf-8")),
        workload_profile=json.loads(workload_profile.read_text(encoding="utf-8")),
        output_path=output,
        config_root=config_root,
        strategy_card_paths=strategy_cards or None,
        baseline_name=baseline,
        experiment=experiment,
        limit=limit,
        repeats=repeats,
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

@dataset_app.command("build-task-set")
def dataset_build_task_set(
    task_set: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Task set JSON path"
    ),
    dataset_id: str = typer.Option(..., help="Dataset id"),
    version: str = typer.Option("v1", help="Dataset version"),
    output: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Output dataset JSON path"
    ),
) -> None:
    payload = build_task_set_dataset_to_path(
        task_set_path=task_set,
        output_path=output,
        dataset_id=dataset_id,
        version=version,
    )
    typer.echo(payload["output_path"])

@dataset_app.command("ingest-annotations")
def dataset_ingest_annotations(
    dataset: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Dataset JSON path"
    ),
    annotations: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Annotation JSON/JSONL path"
    ),
    output: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Output dataset JSON path"
    ),
) -> None:
    payload = ingest_dataset_annotations_to_path(
        dataset_path=dataset,
        annotations_path=annotations,
        output_path=output,
    )
    typer.echo(payload["output_path"])

@dataset_app.command("derive-split")
def dataset_derive_split(
    dataset: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Dataset JSON path"
    ),
    split: str = typer.Option(..., help="Derived split name"),
    dataset_id: str = typer.Option(..., help="Target dataset id"),
    version: str = typer.Option("v1", help="Target dataset version"),
    output: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Output dataset JSON path"
    ),
) -> None:
    payload = derive_dataset_split_to_path(
        dataset_path=dataset,
        output_path=output,
        split=split,
        dataset_id=dataset_id,
        version=version,
    )
    typer.echo(payload["output_path"])

@dataset_app.command("promote")
def dataset_promote(
    datasets_root: Path = typer.Option(
        Path("datasets"), exists=False, file_okay=False, help="Datasets root"
    ),
    dataset_id: str = typer.Option(..., help="Dataset id"),
    version: str = typer.Option(..., help="Dataset version"),
    split: str | None = typer.Option(None, help="Optional promoted split"),
    promoted_by: str | None = typer.Option(None, help="Promotion operator"),
    reason: str | None = typer.Option(None, help="Promotion reason"),
) -> None:
    payload = promote_dataset_version(
        datasets_root=datasets_root,
        dataset_id=dataset_id,
        version=version,
        split=split,
        promoted_by=promoted_by,
        reason=reason,
    )
    typer.echo(json.dumps(payload))

@gate_app.command("evaluate")
def gate_evaluate(
    policy: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Gate policy JSON path"
    ),
    target: Path = typer.Option(
        ..., exists=False, dir_okay=False, help="Target artifact JSON path"
    ),
    target_type: str = typer.Option(..., help="Target type"),
    target_ref: str = typer.Option(..., help="Target reference"),
    evidence_ref: list[str] = typer.Option([], help="Optional evidence refs"),
    reports_root: Path = typer.Option(Path("reports"), exists=False, file_okay=False),
    persist_result: bool = typer.Option(
        False,
        "--persist-result",
        help="Persist gate result artifact and append history",
    ),
) -> None:
    payload = evaluate_gate_policy_from_paths(
        policy_path=policy,
        target_path=target,
        target_type=target_type,
        target_ref=target_ref,
        evidence_refs=evidence_ref,
        reports_root=reports_root,
        persist_result=persist_result,
    )
    typer.echo(json.dumps(payload))


@gate_app.command("list-results")
def gate_list_results(
    reports_root: Path = typer.Option(Path("reports"), exists=False, file_okay=False),
    policy_id: str | None = typer.Option(None, help="Optional policy id filter"),
    target_type: str | None = typer.Option(None, help="Optional target type filter"),
    status: str | None = typer.Option(None, help="Optional status filter"),
) -> None:
    payload = list_gate_results(
        reports_root=reports_root,
        policy_id=policy_id,
        target_type=target_type,
        status=status,
    )
    typer.echo(json.dumps(payload))


@gate_app.command("show-result")
def gate_show_result(
    gate_id: str = typer.Option(..., help="Gate result id"),
    reports_root: Path = typer.Option(Path("reports"), exists=False, file_okay=False),
) -> None:
    payload = load_gate_result(reports_root=reports_root, gate_id=gate_id)
    typer.echo(json.dumps(payload))


@gate_app.command("history")
def gate_history(
    reports_root: Path = typer.Option(Path("reports"), exists=False, file_okay=False),
    policy_id: str | None = typer.Option(None, help="Optional policy id filter"),
    target_type: str | None = typer.Option(None, help="Optional target type filter"),
    status: str | None = typer.Option(None, help="Optional status filter"),
) -> None:
    payload = list_gate_history(
        reports_root=reports_root,
        policy_id=policy_id,
        target_type=target_type,
        status=status,
    )
    typer.echo(json.dumps(payload))
