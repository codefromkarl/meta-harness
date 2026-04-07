from __future__ import annotations

from pathlib import Path

from meta_harness.services.benchmark_service import (
    observe_benchmark_payload,
    write_benchmark_report,
    write_benchmark_suite_report,
)
from meta_harness.services.dataset_service import extract_failure_dataset_to_path
from meta_harness.services.export_service import export_run_trace_to_path
from meta_harness.services.optimize_service import propose_candidate_payload
from meta_harness.services.scoring_service import score_run_record
from meta_harness.services.service_execution import execute_inline_job
from meta_harness.services.strategy_service import run_strategy_benchmark_payload
from meta_harness.services.workflow_service import (
    benchmark_suite_workflow_payload,
    benchmark_workflow_payload,
    run_workflow_payload,
)


def submit_run_score_job(
    *,
    reports_root: Path,
    runs_root: Path,
    run_id: str,
    evaluator_names: list[str] | None = None,
    requested_by: str | None = None,
) -> dict:
    return execute_inline_job(
        reports_root=reports_root,
        job_type="run.score",
        requested_by=requested_by,
        job_input={
            "run_id": run_id,
            "evaluators": evaluator_names or [],
        },
        runner=lambda: score_run_record(
            runs_root=runs_root,
            run_id=run_id,
            evaluator_names=evaluator_names,
        ),
        result_ref_builder=lambda _data: {
            "target_type": "run",
            "target_id": run_id,
            "path": f"runs/{run_id}/score_report.json",
        },
    )


def submit_run_export_trace_job(
    *,
    reports_root: Path,
    runs_root: Path,
    run_id: str,
    output_path: Path,
    export_format: str = "otel-json",
    requested_by: str | None = None,
) -> dict:
    return execute_inline_job(
        reports_root=reports_root,
        job_type="run.export_trace",
        requested_by=requested_by,
        job_input={
            "run_id": run_id,
            "format": export_format,
            "output_path": str(output_path),
        },
        runner=lambda: export_run_trace_to_path(
            runs_root=runs_root,
            run_id=run_id,
            output_path=output_path,
            export_format=export_format,
        ),
        result_ref_builder=lambda data: {
            "target_type": "trace_export",
            "target_id": run_id,
            "path": data["output_path"],
        },
    )


def submit_dataset_extract_job(
    *,
    reports_root: Path,
    runs_root: Path,
    output_path: Path,
    profile_name: str | None = None,
    project_name: str | None = None,
    requested_by: str | None = None,
) -> dict:
    return execute_inline_job(
        reports_root=reports_root,
        job_type="dataset.extract_failures",
        requested_by=requested_by,
        job_input={
            "output_path": str(output_path),
            "profile": profile_name,
            "project": project_name,
        },
        runner=lambda: extract_failure_dataset_to_path(
            runs_root=runs_root,
            output_path=output_path,
            profile_name=profile_name,
            project_name=project_name,
        ),
        result_ref_builder=lambda data: {
            "target_type": "dataset",
            "target_id": data["dataset_id"],
            "path": data["output_path"],
        },
    )


def submit_optimize_propose_job(
    *,
    reports_root: Path,
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    profile_name: str,
    project_name: str,
    requested_by: str | None = None,
) -> dict:
    return execute_inline_job(
        reports_root=reports_root,
        job_type="optimize.propose",
        requested_by=requested_by,
        job_input={
            "profile": profile_name,
            "project": project_name,
        },
        runner=lambda: propose_candidate_payload(
            profile_name=profile_name,
            project_name=project_name,
            config_root=config_root,
            runs_root=runs_root,
            candidates_root=candidates_root,
        ),
        result_ref_builder=lambda data: {
            "target_type": "candidate",
            "target_id": data["candidate_id"],
            "path": f"candidates/{data['candidate_id']}/candidate.json",
        },
    )


def submit_observation_benchmark_job(
    *,
    reports_root: Path,
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    profile_name: str,
    project_name: str,
    task_set_path: Path,
    spec_path: Path,
    focus: str | None = None,
    auto_compact_runs: bool = True,
    requested_by: str | None = None,
) -> dict:
    return execute_inline_job(
        reports_root=reports_root,
        job_type="observation.benchmark",
        requested_by=requested_by,
        job_input={
            "profile": profile_name,
            "project": project_name,
            "task_set_path": str(task_set_path),
            "spec_path": str(spec_path),
            "focus": focus,
        },
        runner=lambda: observe_benchmark_payload(
            profile_name=profile_name,
            project_name=project_name,
            task_set_path=task_set_path,
            spec_path=spec_path,
            config_root=config_root,
            runs_root=runs_root,
            candidates_root=candidates_root,
            focus=focus,
            auto_compact_runs=auto_compact_runs,
        ),
        result_ref_builder=lambda data: {
            "target_type": "benchmark_experiment",
            "target_id": data["experiment"],
            "path": None,
        },
    )


def submit_strategy_benchmark_job(
    *,
    reports_root: Path,
    strategy_card_paths: list[Path],
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    profile_name: str,
    project_name: str,
    task_set_path: Path,
    experiment: str,
    baseline_name: str,
    focus: str | None = None,
    template: str = "generic",
    requested_by: str | None = None,
) -> dict:
    return execute_inline_job(
        reports_root=reports_root,
        job_type="strategy.benchmark",
        requested_by=requested_by,
        job_input={
            "profile": profile_name,
            "project": project_name,
            "strategy_card_paths": [str(path) for path in strategy_card_paths],
            "experiment": experiment,
        },
        runner=lambda: run_strategy_benchmark_payload(
            strategy_card_paths=strategy_card_paths,
            profile_name=profile_name,
            project_name=project_name,
            task_set_path=task_set_path,
            experiment=experiment,
            baseline_name=baseline_name,
            config_root=config_root,
            runs_root=runs_root,
            candidates_root=candidates_root,
            focus=focus,
            template=template,
        ),
        result_ref_builder=lambda data: {
            "target_type": "benchmark_experiment",
            "target_id": data["experiment"],
            "path": None,
        },
    )


def submit_workflow_run_job(
    *,
    reports_root: Path,
    workflow_path: Path,
    config_root: Path,
    runs_root: Path,
    profile_name: str,
    project_name: str,
    requested_by: str | None = None,
) -> dict:
    return execute_inline_job(
        reports_root=reports_root,
        job_type="workflow.run",
        requested_by=requested_by,
        job_input={
            "workflow_path": str(workflow_path),
            "profile": profile_name,
            "project": project_name,
        },
        runner=lambda: run_workflow_payload(
            workflow_path=workflow_path,
            profile_name=profile_name,
            project_name=project_name,
            config_root=config_root,
            runs_root=runs_root,
        ),
        result_ref_builder=lambda data: {
            "target_type": "run",
            "target_id": data["run_id"],
            "path": f"runs/{data['run_id']}/score_report.json",
        },
    )


def submit_workflow_benchmark_job(
    *,
    reports_root: Path,
    workflow_path: Path,
    spec_path: Path,
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    profile_name: str,
    project_name: str,
    focus: str | None = None,
    requested_by: str | None = None,
    runner_override=None,
) -> dict:
    return execute_inline_job(
        reports_root=reports_root,
        job_type="workflow.benchmark",
        requested_by=requested_by,
        job_input={
            "workflow_path": str(workflow_path),
            "profile": profile_name,
            "project": project_name,
            "spec_path": str(spec_path),
            "focus": focus,
        },
        runner=(
            runner_override
            if runner_override is not None
            else lambda: benchmark_workflow_payload(
                workflow_path=workflow_path,
                profile_name=profile_name,
                project_name=project_name,
                spec_path=spec_path,
                config_root=config_root,
                runs_root=runs_root,
                candidates_root=candidates_root,
                focus=focus,
            )
        ),
        result_ref_builder=lambda data: {
            "target_type": "benchmark_experiment",
            "target_id": data["experiment"],
            "path": str(
                write_benchmark_report(
                    reports_root=reports_root,
                    payload=data,
                ).relative_to(reports_root.parent)
            ),
        },
    )


def submit_workflow_benchmark_suite_job(
    *,
    reports_root: Path,
    workflow_path: Path,
    suite_path: Path,
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    profile_name: str,
    project_name: str,
    requested_by: str | None = None,
    runner_override=None,
) -> dict:
    return execute_inline_job(
        reports_root=reports_root,
        job_type="workflow.benchmark_suite",
        requested_by=requested_by,
        job_input={
            "workflow_path": str(workflow_path),
            "profile": profile_name,
            "project": project_name,
            "suite_path": str(suite_path),
        },
        runner=(
            runner_override
            if runner_override is not None
            else lambda: benchmark_suite_workflow_payload(
                workflow_path=workflow_path,
                profile_name=profile_name,
                project_name=project_name,
                suite_path=suite_path,
                config_root=config_root,
                runs_root=runs_root,
                candidates_root=candidates_root,
            )
        ),
        result_ref_builder=lambda data: {
            "target_type": "benchmark_suite",
            "target_id": data["suite"],
            "path": str(
                write_benchmark_suite_report(
                    reports_root=reports_root,
                    payload=data,
                ).relative_to(reports_root.parent)
            ),
        },
    )
