from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException

from meta_harness.api.contracts import (
    ObservationBenchmarkRequest,
    OptimizeLoopRequest,
    OptimizeMaterializeProposalRequest,
    OptimizeProposeRequest,
    PromoteCandidateRequest,
    RunExportTraceRequest,
    RunScoreRequest,
    StrategyAuditWebScrapeRequest,
    StrategyBenchmarkRequest,
    StrategyBuildWebScrapeAuditSpecRequest,
    StrategyCreateCandidateRequest,
    StrategyRecommendWebScrapeRequest,
    WorkflowBenchmarkRequest,
    WorkflowBenchmarkSuiteRequest,
    WorkflowCompileRequest,
    WorkflowRunRequest,
)


def register_execution_ops_routes(app: FastAPI) -> None:
    @app.get("/observations/summary")
    def observation_summary(
        profile: str,
        project: str,
        runs_root: str = "runs",
        config_root: str = "configs",
        limit: int | None = None,
    ) -> dict:
        import meta_harness.api.app as root_api

        return root_api.observe_summary_payload(
            runs_root=Path(runs_root),
            profile_name=profile,
            project_name=project,
            config_root=Path(config_root),
            limit=limit,
        )

    @app.post("/observations/benchmark")
    def observation_benchmark(request: ObservationBenchmarkRequest) -> dict:
        import meta_harness.api.app as root_api

        return root_api.submit_observation_benchmark_job(
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
        import meta_harness.api.app as root_api

        return root_api.inspect_strategy_card_payload(
            strategy_card_path=Path(strategy_card_path),
            profile_name=profile,
            project_name=project,
            config_root=Path(config_root),
        )

    @app.post("/strategies/recommend-web-scrape")
    def strategy_recommend_web_scrape(
        request: StrategyRecommendWebScrapeRequest,
    ) -> dict:
        import meta_harness.api.app as root_api

        return root_api.recommend_web_scrape_strategy_cards_payload(
            page_profile=dict(request.page_profile),
            workload_profile=dict(request.workload_profile),
            config_root=Path(request.config_root),
            strategy_card_paths=(
                [Path(path) for path in request.strategy_card_paths]
                if request.strategy_card_paths is not None
                else None
            ),
            limit=request.limit,
        )

    @app.post("/strategies/audit-web-scrape")
    def strategy_audit_web_scrape(
        request: StrategyAuditWebScrapeRequest,
    ) -> dict:
        import meta_harness.api.app as root_api

        return root_api.build_web_scrape_audit_report_payload(
            page_profile=dict(request.page_profile),
            workload_profile=dict(request.workload_profile),
            config_root=Path(request.config_root),
            strategy_card_paths=(
                [Path(path) for path in request.strategy_card_paths]
                if request.strategy_card_paths is not None
                else None
            ),
            benchmark_report_path=(
                Path(request.benchmark_report_path)
                if request.benchmark_report_path is not None
                else None
            ),
            limit=request.limit,
        )

    @app.post("/strategies/build-web-scrape-audit-spec")
    def strategy_build_web_scrape_audit_spec(
        request: StrategyBuildWebScrapeAuditSpecRequest,
    ) -> dict:
        import meta_harness.api.app as root_api

        return root_api.build_web_scrape_audit_benchmark_spec_payload(
            page_profile=dict(request.page_profile),
            workload_profile=dict(request.workload_profile),
            output_path=Path(request.output_path),
            config_root=Path(request.config_root),
            strategy_card_paths=(
                [Path(path) for path in request.strategy_card_paths]
                if request.strategy_card_paths is not None
                else None
            ),
            baseline_name=request.baseline,
            experiment=request.experiment,
            limit=request.limit,
            repeats=request.repeats,
        )

    @app.get("/workflows/inspect")
    def workflow_inspect(workflow_path: str, config_root: str = "configs") -> dict:
        import meta_harness.api.app as root_api

        try:
            return root_api.inspect_workflow_payload(
                workflow_path=Path(workflow_path),
                config_root=Path(config_root),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/workflows/compile")
    def workflow_compile(request: WorkflowCompileRequest) -> dict:
        import meta_harness.api.app as root_api

        try:
            return root_api.success_response(
                root_api.compile_workflow_payload(
                    workflow_path=Path(request.workflow_path),
                    output_path=Path(request.output_path),
                    config_root=Path(request.config_root),
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/workflows/run")
    def workflow_run(request: WorkflowRunRequest) -> dict:
        import meta_harness.api.app as root_api

        return root_api.submit_workflow_run_job(
            reports_root=Path(request.reports_root),
            workflow_path=Path(request.workflow_path),
            config_root=Path(request.config_root),
            runs_root=Path(request.runs_root),
            profile_name=request.profile,
            project_name=request.project,
            requested_by=request.requested_by,
        )

    @app.post("/workflows/benchmark")
    def workflow_benchmark(request: WorkflowBenchmarkRequest) -> dict:
        import meta_harness.api.app as root_api

        return root_api.submit_workflow_benchmark_job(
            reports_root=Path(request.reports_root),
            workflow_path=Path(request.workflow_path),
            spec_path=Path(request.spec_path),
            config_root=Path(request.config_root),
            runs_root=Path(request.runs_root),
            candidates_root=Path(request.candidates_root),
            profile_name=request.profile,
            project_name=request.project,
            focus=request.focus,
            requested_by=request.requested_by,
        )

    @app.post("/workflows/benchmark-suite")
    def workflow_benchmark_suite(request: WorkflowBenchmarkSuiteRequest) -> dict:
        import meta_harness.api.app as root_api

        return root_api.submit_workflow_benchmark_suite_job(
            reports_root=Path(request.reports_root),
            workflow_path=Path(request.workflow_path),
            suite_path=Path(request.suite_path),
            config_root=Path(request.config_root),
            runs_root=Path(request.runs_root),
            candidates_root=Path(request.candidates_root),
            profile_name=request.profile,
            project_name=request.project,
            requested_by=request.requested_by,
        )

    @app.post("/runs/{run_id}/score")
    def run_score(run_id: str, request: RunScoreRequest) -> dict:
        import meta_harness.api.app as root_api

        return root_api.submit_run_score_job(
            reports_root=Path(request.reports_root),
            runs_root=Path(request.runs_root),
            run_id=run_id,
            evaluator_names=request.evaluators,
            requested_by=request.requested_by,
        )

    @app.post("/runs/{run_id}/export-trace")
    def run_export_trace(run_id: str, request: RunExportTraceRequest) -> dict:
        import meta_harness.api.app as root_api

        return root_api.submit_run_export_trace_job(
            reports_root=Path(request.reports_root),
            runs_root=Path(request.runs_root),
            run_id=run_id,
            output_path=Path(request.output_path) if request.output_path is not None else None,
            export_format=request.format,
            destination=request.destination,
            config_root=Path(request.config_root),
            integration_name=request.integration_name,
            requested_by=request.requested_by,
        )

    @app.post("/optimize/propose")
    def optimize_propose(request: OptimizeProposeRequest) -> dict:
        import meta_harness.api.app as root_api

        return root_api.submit_optimize_propose_job(
            reports_root=Path(request.reports_root),
            config_root=Path(request.config_root),
            runs_root=Path(request.runs_root),
            candidates_root=Path(request.candidates_root),
            proposals_root=Path(request.proposals_root),
            profile_name=request.profile,
            project_name=request.project,
            proposal_only=request.proposal_only,
            requested_by=request.requested_by,
        )

    @app.post("/optimize/loop")
    def optimize_loop(request: OptimizeLoopRequest) -> dict:
        import meta_harness.api.app as root_api

        return root_api.submit_optimize_loop_job(
            reports_root=Path(request.reports_root),
            config_root=Path(request.config_root),
            runs_root=Path(request.runs_root),
            candidates_root=Path(request.candidates_root),
            proposals_root=Path(request.proposals_root),
            profile_name=request.profile,
            project_name=request.project,
            task_set_path=Path(request.task_set_path),
            loop_id=request.loop_id,
            plugin_id=request.plugin_id,
            proposer_id=request.proposer_id,
            max_iterations=request.max_iterations,
            focus=request.focus,
            requested_by=request.requested_by,
        )

    @app.post("/optimize/materialize-proposal/{proposal_id}")
    def optimize_materialize_proposal(
        proposal_id: str, request: OptimizeMaterializeProposalRequest
    ) -> dict:
        import meta_harness.api.app as root_api

        return root_api.success_response(
            root_api.materialize_proposal_payload(
                proposal_id=proposal_id,
                proposals_root=Path(request.proposals_root),
                candidates_root=Path(request.candidates_root),
                config_root=Path(request.config_root),
            )
        )

    @app.post("/strategies/create-candidate")
    def strategy_create_candidate(request: StrategyCreateCandidateRequest) -> dict:
        import meta_harness.api.app as root_api

        return root_api.success_response(
            root_api.create_candidate_from_strategy_card_payload(
                strategy_card_path=Path(request.strategy_card_path),
                profile_name=request.profile,
                project_name=request.project,
                config_root=Path(request.config_root),
                candidates_root=Path(request.candidates_root),
            )
        )

    @app.post("/strategies/benchmark")
    def strategy_benchmark(request: StrategyBenchmarkRequest) -> dict:
        import meta_harness.api.app as root_api

        return root_api.submit_strategy_benchmark_job(
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
        import meta_harness.api.app as root_api

        return root_api.success_response(
            root_api.promote_candidate_record(
                Path(request.candidates_root),
                candidate_id,
                promoted_by=request.promoted_by,
                promotion_reason=request.reason,
                evidence_run_ids=list(request.evidence_run_ids),
                runs_root=Path(request.runs_root) if request.runs_root else None,
            )
        )
