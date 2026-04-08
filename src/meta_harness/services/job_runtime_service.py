from __future__ import annotations

from pathlib import Path

from meta_harness.services.async_jobs import (
    submit_dataset_extract_job,
    submit_observation_benchmark_job,
    submit_optimize_loop_job,
    submit_optimize_propose_job,
    submit_run_export_trace_job,
    submit_run_score_job,
    submit_strategy_benchmark_job,
    submit_workflow_benchmark_job,
    submit_workflow_benchmark_suite_job,
    submit_workflow_run_job,
)
from meta_harness.services.job_service import load_job_record, load_job_result_payload


def retry_job(
    *,
    reports_root: Path,
    job_id: str,
) -> dict:
    job = load_job_record(reports_root=reports_root, job_id=job_id)
    job_input = dict(job.get("job_input") or {})
    requested_by = job.get("requested_by")
    next_attempt = int(job.get("attempt", 1) or 1) + 1
    job_type = str(job.get("job_type"))

    if job_type == "run.score":
        return submit_run_score_job(
            reports_root=Path(job_input["reports_root"]),
            runs_root=Path(job_input["runs_root"]),
            run_id=str(job_input["run_id"]),
            evaluator_names=list(job_input.get("evaluators") or []),
            requested_by=requested_by,
            parent_job_id=job_id,
            attempt=next_attempt,
        )
    if job_type == "run.export_trace":
        return submit_run_export_trace_job(
            reports_root=Path(job_input["reports_root"]),
            runs_root=Path(job_input["runs_root"]),
            run_id=str(job_input["run_id"]),
            output_path=(
                Path(str(job_input["output_path"]))
                if job_input.get("output_path")
                else None
            ),
            export_format=str(job_input.get("format") or "otel-json"),
            destination=str(job_input.get("destination") or "download"),
            config_root=(
                Path(str(job_input["config_root"]))
                if job_input.get("config_root")
                else None
            ),
            integration_name=(
                str(job_input["integration_name"])
                if job_input.get("integration_name") is not None
                else None
            ),
            requested_by=requested_by,
            parent_job_id=job_id,
            attempt=next_attempt,
        )
    if job_type == "dataset.extract_failures":
        return submit_dataset_extract_job(
            reports_root=Path(job_input["reports_root"]),
            runs_root=Path(job_input["runs_root"]),
            output_path=Path(job_input["output_path"]),
            profile_name=job_input.get("profile"),
            project_name=job_input.get("project"),
            requested_by=requested_by,
            parent_job_id=job_id,
            attempt=next_attempt,
        )
    if job_type == "optimize.propose":
        return submit_optimize_propose_job(
            reports_root=Path(job_input["reports_root"]),
            config_root=Path(job_input["config_root"]),
            runs_root=Path(job_input["runs_root"]),
            candidates_root=Path(job_input["candidates_root"]),
            proposals_root=(
                Path(job_input["proposals_root"])
                if job_input.get("proposals_root")
                else None
            ),
            profile_name=str(job_input["profile"]),
            project_name=str(job_input["project"]),
            proposal_only=bool(job_input.get("proposal_only", False)),
            requested_by=requested_by,
            parent_job_id=job_id,
            attempt=next_attempt,
        )
    if job_type == "optimize.loop":
        return submit_optimize_loop_job(
            reports_root=Path(job_input["reports_root"]),
            config_root=Path(job_input["config_root"]),
            runs_root=Path(job_input["runs_root"]),
            candidates_root=Path(job_input["candidates_root"]),
            proposals_root=(
                Path(job_input["proposals_root"])
                if job_input.get("proposals_root")
                else None
            ),
            profile_name=str(job_input["profile"]),
            project_name=str(job_input["project"]),
            task_set_path=Path(job_input["task_set_path"]),
            loop_id=(
                str(job_input["loop_id"])
                if job_input.get("loop_id") is not None
                else None
            ),
            plugin_id=str(job_input.get("plugin_id") or "default"),
            proposer_id=str(job_input.get("proposer_id") or "heuristic"),
            max_iterations=int(job_input.get("max_iterations") or 8),
            focus=str(job_input["focus"]) if job_input.get("focus") is not None else None,
            requested_by=requested_by,
            parent_job_id=job_id,
            attempt=next_attempt,
        )
    if job_type == "observation.benchmark":
        return submit_observation_benchmark_job(
            reports_root=Path(job_input["reports_root"]),
            config_root=Path(job_input["config_root"]),
            runs_root=Path(job_input["runs_root"]),
            candidates_root=Path(job_input["candidates_root"]),
            profile_name=str(job_input["profile"]),
            project_name=str(job_input["project"]),
            task_set_path=Path(job_input["task_set_path"]),
            spec_path=Path(job_input["spec_path"]),
            focus=job_input.get("focus"),
            auto_compact_runs=bool(job_input.get("auto_compact_runs", True)),
            requested_by=requested_by,
            parent_job_id=job_id,
            attempt=next_attempt,
        )
    if job_type == "strategy.benchmark":
        return submit_strategy_benchmark_job(
            reports_root=Path(job_input["reports_root"]),
            strategy_card_paths=[Path(path) for path in list(job_input.get("strategy_card_paths") or [])],
            config_root=Path(job_input["config_root"]),
            runs_root=Path(job_input["runs_root"]),
            candidates_root=Path(job_input["candidates_root"]),
            profile_name=str(job_input["profile"]),
            project_name=str(job_input["project"]),
            task_set_path=Path(job_input["task_set_path"]),
            experiment=str(job_input["experiment"]),
            baseline_name=str(job_input["baseline"]),
            focus=job_input.get("focus"),
            template=str(job_input.get("template") or "generic"),
            requested_by=requested_by,
            parent_job_id=job_id,
            attempt=next_attempt,
        )
    if job_type == "workflow.run":
        return submit_workflow_run_job(
            reports_root=Path(job_input["reports_root"]),
            workflow_path=Path(job_input["workflow_path"]),
            config_root=Path(job_input["config_root"]),
            runs_root=Path(job_input["runs_root"]),
            profile_name=str(job_input["profile"]),
            project_name=str(job_input["project"]),
            requested_by=requested_by,
            parent_job_id=job_id,
            attempt=next_attempt,
        )
    if job_type == "workflow.benchmark":
        return submit_workflow_benchmark_job(
            reports_root=Path(job_input["reports_root"]),
            workflow_path=Path(job_input["workflow_path"]),
            spec_path=Path(job_input["spec_path"]),
            config_root=Path(job_input["config_root"]),
            runs_root=Path(job_input["runs_root"]),
            candidates_root=Path(job_input["candidates_root"]),
            profile_name=str(job_input["profile"]),
            project_name=str(job_input["project"]),
            focus=job_input.get("focus"),
            requested_by=requested_by,
            parent_job_id=job_id,
            attempt=next_attempt,
        )
    if job_type == "workflow.benchmark_suite":
        return submit_workflow_benchmark_suite_job(
            reports_root=Path(job_input["reports_root"]),
            workflow_path=Path(job_input["workflow_path"]),
            suite_path=Path(job_input["suite_path"]),
            config_root=Path(job_input["config_root"]),
            runs_root=Path(job_input["runs_root"]),
            candidates_root=Path(job_input["candidates_root"]),
            profile_name=str(job_input["profile"]),
            project_name=str(job_input["project"]),
            requested_by=requested_by,
            parent_job_id=job_id,
            attempt=next_attempt,
        )
    raise ValueError(f"job type '{job_type}' is not retryable")


def load_job_result(
    *,
    reports_root: Path,
    job_id: str,
    repo_root: Path | None = None,
) -> dict:
    return load_job_result_payload(
        reports_root=reports_root,
        job_id=job_id,
        repo_root=repo_root,
    )
