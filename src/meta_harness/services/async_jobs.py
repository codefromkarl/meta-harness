from __future__ import annotations

from pathlib import Path

from meta_harness.services.benchmark_service import (
    observe_benchmark_payload,
    persist_benchmark_payload,
)
from meta_harness.services.dataset_service import extract_failure_dataset_to_path
from meta_harness.services.export_service import (
    export_run_trace_to_integration,
    export_run_trace_to_path,
)
from meta_harness.services.optimize_loop_service import optimize_loop_payload
from meta_harness.services.optimize_service import propose_candidate_payload
from meta_harness.services.scoring_service import score_run_record
from meta_harness.services.service_execution import execute_inline_job
from meta_harness.services.strategy_service import run_strategy_benchmark_payload
from meta_harness.services.workflow_service import (
    benchmark_suite_workflow_payload,
    benchmark_workflow_payload,
    run_workflow_payload,
)


def _benchmark_result_ref(*, reports_root: Path, data: dict) -> dict:
    payload = persist_benchmark_payload(reports_root=reports_root, payload=data)
    if payload is not data:
        data.clear()
        data.update(payload)
    if "suite" in data:
        return {
            "target_type": "benchmark_suite",
            "target_id": data["suite"],
            "path": data["artifact_path"],
        }
    return {
        "target_type": "benchmark_experiment",
        "target_id": data["experiment"],
        "path": data["artifact_path"],
    }


def submit_run_score_job(
    *,
    reports_root: Path,
    runs_root: Path,
    run_id: str,
    evaluator_names: list[str] | None = None,
    requested_by: str | None = None,
    parent_job_id: str | None = None,
    attempt: int = 1,
) -> dict:
    return execute_inline_job(
        reports_root=reports_root,
        job_type="run.score",
        requested_by=requested_by,
        job_input={
            "reports_root": str(reports_root),
            "runs_root": str(runs_root),
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
        parent_job_id=parent_job_id,
        attempt=attempt,
    )


def submit_run_export_trace_job(
    *,
    reports_root: Path,
    runs_root: Path,
    candidates_root: Path | None = None,
    run_id: str,
    output_path: Path | None = None,
    export_format: str = "otel-json",
    destination: str = "download",
    config_root: Path | None = None,
    integration_name: str | None = None,
    requested_by: str | None = None,
    parent_job_id: str | None = None,
    attempt: int = 1,
) -> dict:
    if destination == "download" and output_path is None:
        raise ValueError("output_path is required when destination=download")
    if destination == "integration" and (
        config_root is None or integration_name is None
    ):
        raise ValueError(
            "config_root and integration_name are required when destination=integration"
        )
    return execute_inline_job(
        reports_root=reports_root,
        job_type="run.export_trace",
        requested_by=requested_by,
        job_input={
            "reports_root": str(reports_root),
            "runs_root": str(runs_root),
            "candidates_root": str(candidates_root) if candidates_root is not None else None,
            "run_id": run_id,
            "format": export_format,
            "destination": destination,
            "output_path": str(output_path) if output_path is not None else None,
            "config_root": str(config_root) if config_root is not None else None,
            "integration_name": integration_name,
        },
        runner=lambda: (
            export_run_trace_to_path(
                runs_root=runs_root,
                candidates_root=candidates_root,
                run_id=run_id,
                output_path=output_path,
                export_format=export_format,
            )
            if destination == "download"
            else export_run_trace_to_integration(
                runs_root=runs_root,
                candidates_root=candidates_root,
                run_id=run_id,
                config_root=config_root,
                integration_name=integration_name,
                export_format=export_format,
                reports_root=reports_root,
            )
        ),
        result_ref_builder=lambda data: {
            "target_type": "trace_export",
            "target_id": run_id,
            "path": data.get("artifact_path") or data.get("output_path"),
        },
        parent_job_id=parent_job_id,
        attempt=attempt,
    )


def submit_dataset_extract_job(
    *,
    reports_root: Path,
    runs_root: Path,
    output_path: Path,
    profile_name: str | None = None,
    project_name: str | None = None,
    requested_by: str | None = None,
    parent_job_id: str | None = None,
    attempt: int = 1,
) -> dict:
    return execute_inline_job(
        reports_root=reports_root,
        job_type="dataset.extract_failures",
        requested_by=requested_by,
        job_input={
            "reports_root": str(reports_root),
            "runs_root": str(runs_root),
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
        parent_job_id=parent_job_id,
        attempt=attempt,
    )


def submit_optimize_propose_job(
    *,
    reports_root: Path,
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    proposals_root: Path | None,
    profile_name: str,
    project_name: str,
    proposal_only: bool = False,
    requested_by: str | None = None,
    parent_job_id: str | None = None,
    attempt: int = 1,
) -> dict:
    return execute_inline_job(
        reports_root=reports_root,
        job_type="optimize.propose",
        requested_by=requested_by,
        job_input={
            "reports_root": str(reports_root),
            "config_root": str(config_root),
            "runs_root": str(runs_root),
            "candidates_root": str(candidates_root),
            "proposals_root": str(proposals_root) if proposals_root is not None else None,
            "profile": profile_name,
            "project": project_name,
            "proposal_only": proposal_only,
        },
        runner=lambda: propose_candidate_payload(
            profile_name=profile_name,
            project_name=project_name,
            config_root=config_root,
            runs_root=runs_root,
            candidates_root=candidates_root,
            proposals_root=proposals_root,
            proposal_only=proposal_only,
        ),
        result_ref_builder=lambda data: (
            {
                "target_type": "proposal",
                "target_id": data["proposal_id"],
                "path": f"proposals/{data['proposal_id']}/proposal.json",
            }
            if "candidate_id" not in data
            else {
                "target_type": "candidate",
                "target_id": data["candidate_id"],
                "path": f"candidates/{data['candidate_id']}/candidate.json",
            }
        ),
        parent_job_id=parent_job_id,
        attempt=attempt,
    )


def submit_optimize_loop_job(
    *,
    reports_root: Path,
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    proposals_root: Path | None,
    profile_name: str,
    project_name: str,
    task_set_path: Path,
    loop_id: str | None = None,
    plugin_id: str = "default",
    proposer_id: str = "heuristic",
    max_iterations: int = 8,
    focus: str | None = None,
    requested_by: str | None = None,
    parent_job_id: str | None = None,
    attempt: int = 1,
) -> dict:
    return execute_inline_job(
        reports_root=reports_root,
        job_type="optimize.loop",
        requested_by=requested_by,
        job_input={
            "reports_root": str(reports_root),
            "config_root": str(config_root),
            "runs_root": str(runs_root),
            "candidates_root": str(candidates_root),
            "proposals_root": str(proposals_root) if proposals_root is not None else None,
            "profile": profile_name,
            "project": project_name,
            "task_set_path": str(task_set_path),
            "loop_id": loop_id,
            "plugin_id": plugin_id,
            "proposer_id": proposer_id,
            "max_iterations": max_iterations,
            "focus": focus,
        },
        runner=lambda: optimize_loop_payload(
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
        ),
        result_ref_builder=lambda data: {
            "target_type": "loop",
            "target_id": str(data["loop_id"]),
            "path": f"reports/loops/{data['loop_id']}/loop.json",
        },
        parent_job_id=parent_job_id,
        attempt=attempt,
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
    runner_override=None,
    parent_job_id: str | None = None,
    attempt: int = 1,
) -> dict:
    return execute_inline_job(
        reports_root=reports_root,
        job_type="observation.benchmark",
        requested_by=requested_by,
        job_input={
            "reports_root": str(reports_root),
            "config_root": str(config_root),
            "runs_root": str(runs_root),
            "candidates_root": str(candidates_root),
            "profile": profile_name,
            "project": project_name,
            "task_set_path": str(task_set_path),
            "spec_path": str(spec_path),
            "focus": focus,
            "auto_compact_runs": auto_compact_runs,
        },
        runner=(
            runner_override
            if runner_override is not None
            else lambda: observe_benchmark_payload(
                profile_name=profile_name,
                project_name=project_name,
                task_set_path=task_set_path,
                spec_path=spec_path,
                reports_root=reports_root,
                config_root=config_root,
                runs_root=runs_root,
                candidates_root=candidates_root,
                focus=focus,
                auto_compact_runs=auto_compact_runs,
            )
        ),
        result_ref_builder=lambda data: _benchmark_result_ref(
            reports_root=reports_root,
            data=data,
        ),
        parent_job_id=parent_job_id,
        attempt=attempt,
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
    runner_override=None,
    parent_job_id: str | None = None,
    attempt: int = 1,
) -> dict:
    return execute_inline_job(
        reports_root=reports_root,
        job_type="strategy.benchmark",
        requested_by=requested_by,
        job_input={
            "reports_root": str(reports_root),
            "config_root": str(config_root),
            "runs_root": str(runs_root),
            "candidates_root": str(candidates_root),
            "profile": profile_name,
            "project": project_name,
            "strategy_card_paths": [str(path) for path in strategy_card_paths],
            "task_set_path": str(task_set_path),
            "experiment": experiment,
            "baseline": baseline_name,
            "focus": focus,
            "template": template,
        },
        runner=(
            runner_override
            if runner_override is not None
            else lambda: run_strategy_benchmark_payload(
                strategy_card_paths=strategy_card_paths,
                profile_name=profile_name,
                project_name=project_name,
                task_set_path=task_set_path,
                experiment=experiment,
                baseline_name=baseline_name,
                reports_root=reports_root,
                config_root=config_root,
                runs_root=runs_root,
                candidates_root=candidates_root,
                focus=focus,
                template=template,
            )
        ),
        result_ref_builder=lambda data: _benchmark_result_ref(
            reports_root=reports_root,
            data=data,
        ),
        parent_job_id=parent_job_id,
        attempt=attempt,
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
    parent_job_id: str | None = None,
    attempt: int = 1,
) -> dict:
    return execute_inline_job(
        reports_root=reports_root,
        job_type="workflow.run",
        requested_by=requested_by,
        job_input={
            "reports_root": str(reports_root),
            "workflow_path": str(workflow_path),
            "config_root": str(config_root),
            "runs_root": str(runs_root),
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
        parent_job_id=parent_job_id,
        attempt=attempt,
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
    parent_job_id: str | None = None,
    attempt: int = 1,
) -> dict:
    return execute_inline_job(
        reports_root=reports_root,
        job_type="workflow.benchmark",
        requested_by=requested_by,
        job_input={
            "reports_root": str(reports_root),
            "workflow_path": str(workflow_path),
            "config_root": str(config_root),
            "runs_root": str(runs_root),
            "candidates_root": str(candidates_root),
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
                reports_root=reports_root,
                config_root=config_root,
                runs_root=runs_root,
                candidates_root=candidates_root,
                focus=focus,
            )
        ),
        result_ref_builder=lambda data: _benchmark_result_ref(
            reports_root=reports_root,
            data=data,
        ),
        parent_job_id=parent_job_id,
        attempt=attempt,
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
    parent_job_id: str | None = None,
    attempt: int = 1,
) -> dict:
    return execute_inline_job(
        reports_root=reports_root,
        job_type="workflow.benchmark_suite",
        requested_by=requested_by,
        job_input={
            "reports_root": str(reports_root),
            "workflow_path": str(workflow_path),
            "config_root": str(config_root),
            "runs_root": str(runs_root),
            "candidates_root": str(candidates_root),
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
                reports_root=reports_root,
                config_root=config_root,
                runs_root=runs_root,
                candidates_root=candidates_root,
            )
        ),
        result_ref_builder=lambda data: _benchmark_result_ref(
            reports_root=reports_root,
            data=data,
        ),
        parent_job_id=parent_job_id,
        attempt=attempt,
    )
