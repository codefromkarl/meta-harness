from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from meta_harness.api.contracts import (
    DatasetExtractFailuresRequest,
    ObservationBenchmarkRequest,
    OptimizeProposeRequest,
    PromoteCandidateRequest,
    RunExportTraceRequest,
    RunScoreRequest,
    StrategyBenchmarkRequest,
    StrategyCreateCandidateRequest,
    WorkflowCompileRequest,
    WorkflowRunRequest,
)
from meta_harness.services.async_jobs import (
    submit_dataset_extract_job,
    submit_observation_benchmark_job,
    submit_optimize_propose_job,
    submit_run_export_trace_job,
    submit_run_score_job,
    submit_strategy_benchmark_job,
)
from meta_harness.services.candidate_service import list_champions, promote_candidate_record
from meta_harness.services.catalog_service import candidate_current_view_payload
from meta_harness.services.job_service import list_job_records
from meta_harness.services.job_service import load_job_record
from meta_harness.services.observation_service import observe_summary_payload
from meta_harness.services.profile_service import list_profile_names
from meta_harness.services.project_service import list_project_names
from meta_harness.services.run_query_service import (
    list_evaluator_reports,
    list_run_summaries,
    list_task_results,
    list_trace_events,
    load_run_summary,
)
from meta_harness.services.service_execution import execute_inline_job
from meta_harness.services.service_response import success_response
from meta_harness.services.strategy_service import (
    create_candidate_from_strategy_card_payload,
    inspect_strategy_card_payload,
)
from meta_harness.services.workflow_service import (
    compile_workflow_payload,
    inspect_workflow_payload,
    run_workflow_payload,
)


def create_app() -> FastAPI:
    app = FastAPI(title="Meta-Harness API", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/profiles")
    def profiles(config_root: str = "configs") -> dict[str, list[str]]:
        return {"items": list_profile_names(Path(config_root))}

    @app.get("/projects")
    def projects(config_root: str = "configs") -> dict[str, list[str]]:
        return {"items": list_project_names(Path(config_root))}

    @app.get("/runs")
    def runs(runs_root: str = "runs") -> dict[str, list[dict[str, str]]]:
        return {"items": list_run_summaries(Path(runs_root))}

    @app.get("/runs/{run_id}")
    def run_detail(run_id: str, runs_root: str = "runs") -> dict:
        return load_run_summary(Path(runs_root), run_id)

    @app.get("/runs/{run_id}/tasks")
    def run_tasks(run_id: str, runs_root: str = "runs") -> dict[str, list[dict]]:
        return {"items": list_task_results(Path(runs_root), run_id)}

    @app.get("/runs/{run_id}/trace")
    def run_trace(run_id: str, runs_root: str = "runs") -> dict[str, list[dict]]:
        return {"items": list_trace_events(Path(runs_root), run_id)}

    @app.get("/runs/{run_id}/evaluators")
    def run_evaluators(run_id: str, runs_root: str = "runs") -> dict[str, list[dict]]:
        return {"items": list_evaluator_reports(Path(runs_root), run_id)}

    @app.get("/jobs")
    def jobs(
        reports_root: str = "reports",
        status: str | None = None,
        job_type: str | None = None,
    ) -> dict[str, list[dict]]:
        return {
            "items": list_job_records(
                reports_root=Path(reports_root),
                status=status,
                job_type=job_type,
            )
        }

    @app.get("/jobs/{job_id}")
    def job_detail(job_id: str, reports_root: str = "reports") -> dict:
        return load_job_record(reports_root=Path(reports_root), job_id=job_id)

    @app.get("/candidates/current")
    def candidates_current(
        candidates_root: str = "candidates",
        runs_root: str | None = None,
    ) -> dict:
        resolved_runs_root = Path(runs_root) if runs_root is not None else None
        return candidate_current_view_payload(
            candidates_root=Path(candidates_root),
            runs_root=resolved_runs_root,
        )

    @app.get("/champions")
    def champions(candidates_root: str = "candidates") -> dict[str, dict[str, str]]:
        return {"items": list_champions(Path(candidates_root))}

    @app.get("/observations/summary")
    def observation_summary(
        profile: str,
        project: str,
        runs_root: str = "runs",
        config_root: str = "configs",
        limit: int | None = None,
    ) -> dict:
        return observe_summary_payload(
            runs_root=Path(runs_root),
            profile_name=profile,
            project_name=project,
            config_root=Path(config_root),
            limit=limit,
        )

    @app.post("/observations/benchmark")
    def observation_benchmark(request: ObservationBenchmarkRequest) -> dict:
        return submit_observation_benchmark_job(
            reports_root=Path(request.reports_root),
            config_root=Path(request.config_root),
            runs_root=Path(request.runs_root),
            candidates_root=Path(request.candidates_root),
            profile_name=request.profile,
            project_name=request.project,
            task_set_path=Path(request.task_set_path),
            spec_path=Path(request.spec_path),
            focus=request.focus,
            auto_compact_runs=request.auto_compact_runs,
            requested_by=request.requested_by,
        )

    @app.get("/strategies/inspect")
    def strategy_inspect(
        strategy_card_path: str,
        config_root: str,
        profile: str,
        project: str,
    ) -> dict:
        return inspect_strategy_card_payload(
            strategy_card_path=Path(strategy_card_path),
            profile_name=profile,
            project_name=project,
            config_root=Path(config_root),
        )

    @app.get("/workflows/inspect")
    def workflow_inspect(workflow_path: str) -> dict:
        return inspect_workflow_payload(workflow_path=Path(workflow_path))

    @app.post("/workflows/compile")
    def workflow_compile(request: WorkflowCompileRequest) -> dict:
        return success_response(
            compile_workflow_payload(
                workflow_path=Path(request.workflow_path),
                output_path=Path(request.output_path),
            )
        )

    @app.post("/workflows/run")
    def workflow_run(request: WorkflowRunRequest) -> dict:
        return execute_inline_job(
            reports_root=Path(request.reports_root),
            job_type="workflow.run",
            requested_by=request.requested_by,
            job_input={
                "workflow_path": request.workflow_path,
                "profile": request.profile,
                "project": request.project,
            },
            runner=lambda: run_workflow_payload(
                workflow_path=Path(request.workflow_path),
                profile_name=request.profile,
                project_name=request.project,
                config_root=Path(request.config_root),
                runs_root=Path(request.runs_root),
            ),
            result_ref_builder=lambda data: {
                "target_type": "run",
                "target_id": data["run_id"],
                "path": f"runs/{data['run_id']}/score_report.json",
            },
        )

    @app.post("/runs/{run_id}/score")
    def run_score(run_id: str, request: RunScoreRequest) -> dict:
        return submit_run_score_job(
            reports_root=Path(request.reports_root),
            runs_root=Path(request.runs_root),
            run_id=run_id,
            evaluator_names=request.evaluators,
            requested_by=request.requested_by,
        )

    @app.post("/runs/{run_id}/export-trace")
    def run_export_trace(run_id: str, request: RunExportTraceRequest) -> dict:
        return submit_run_export_trace_job(
            reports_root=Path(request.reports_root),
            runs_root=Path(request.runs_root),
            run_id=run_id,
            output_path=Path(request.output_path),
            export_format=request.format,
            requested_by=request.requested_by,
        )

    @app.post("/datasets/extract-failures")
    def dataset_extract_failures(request: DatasetExtractFailuresRequest) -> dict:
        return submit_dataset_extract_job(
            reports_root=Path(request.reports_root),
            runs_root=Path(request.runs_root),
            output_path=Path(request.output_path),
            profile_name=request.profile,
            project_name=request.project,
            requested_by=request.requested_by,
        )

    @app.post("/optimize/propose")
    def optimize_propose(request: OptimizeProposeRequest) -> dict:
        return submit_optimize_propose_job(
            reports_root=Path(request.reports_root),
            config_root=Path(request.config_root),
            runs_root=Path(request.runs_root),
            candidates_root=Path(request.candidates_root),
            profile_name=request.profile,
            project_name=request.project,
            requested_by=request.requested_by,
        )

    @app.post("/strategies/create-candidate")
    def strategy_create_candidate(request: StrategyCreateCandidateRequest) -> dict:
        return success_response(
            create_candidate_from_strategy_card_payload(
                strategy_card_path=Path(request.strategy_card_path),
                profile_name=request.profile,
                project_name=request.project,
                config_root=Path(request.config_root),
                candidates_root=Path(request.candidates_root),
            )
        )

    @app.post("/strategies/benchmark")
    def strategy_benchmark(request: StrategyBenchmarkRequest) -> dict:
        return submit_strategy_benchmark_job(
            reports_root=Path(request.reports_root),
            strategy_card_paths=[Path(path) for path in request.strategy_card_paths],
            config_root=Path(request.config_root),
            runs_root=Path(request.runs_root),
            candidates_root=Path(request.candidates_root),
            profile_name=request.profile,
            project_name=request.project,
            task_set_path=Path(request.task_set_path),
            experiment=request.experiment,
            baseline_name=request.baseline,
            focus=request.focus,
            template=request.template,
            requested_by=request.requested_by,
        )

    @app.post("/candidates/{candidate_id}/promote")
    def candidate_promote(candidate_id: str, request: PromoteCandidateRequest) -> dict:
        return success_response(
            promote_candidate_record(Path(request.candidates_root), candidate_id)
        )

    return app
