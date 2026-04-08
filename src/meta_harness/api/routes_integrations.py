from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException

from meta_harness.api.contracts import (
    IntegrationAnalyzeRequest,
    IntegrationBenchmarkRequest,
    IntegrationOuterLoopRequest,
    IntegrationReviewRequest,
    IntegrationScaffoldRequest,
)


def register_integration_routes(app: FastAPI) -> None:
    @app.get("/integrations")
    def integrations(
        config_root: str = "configs",
        limit: int | None = None,
        offset: int = 0,
    ) -> dict:
        import meta_harness.api.app as root_api

        return root_api.paginate_items(
            root_api.list_integrations(Path(config_root)),
            limit=limit,
            offset=offset,
        )

    @app.post("/integrations/{name}/test")
    def integration_test(name: str, config_root: str = "configs") -> dict:
        import meta_harness.api.app as root_api

        try:
            return root_api.success_response(root_api.test_integration(Path(config_root), name))
        except (FileNotFoundError, ValueError, ConnectionError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/integrations/{name}/export-runs/{run_id}")
    def integration_export_run(
        name: str,
        run_id: str,
        config_root: str = "configs",
        runs_root: str = "runs",
        format: str | None = None,
    ) -> dict:
        import meta_harness.api.app as root_api

        try:
            return root_api.success_response(
                root_api.export_run_to_named_integration(
                    runs_root=Path(runs_root),
                    run_id=run_id,
                    config_root=Path(config_root),
                    integration_name=name,
                    export_format=format,
                )
            )
        except (FileNotFoundError, ValueError, ConnectionError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/integrations/analyze")
    def integration_analyze(request: IntegrationAnalyzeRequest) -> dict:
        import meta_harness.api.app as root_api

        try:
            return root_api.success_response(
                root_api.analyze_integration_payload(
                    config_root=Path(request.config_root),
                    reports_root=Path(request.reports_root),
                    intent_text=request.intent_text,
                    target_project_path=request.target_project_path,
                    primitive_id=request.primitive_id,
                    workflow_paths=list(request.workflow_paths or []),
                    user_goal=request.user_goal,
                )
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/integrations/scaffold")
    def integration_scaffold(request: IntegrationScaffoldRequest) -> dict:
        import meta_harness.api.app as root_api

        try:
            if request.spec_path is not None:
                payload = root_api.scaffold_integration_payload(
                    config_root=Path(request.config_root),
                    spec_path=Path(request.spec_path),
                )
            elif request.harness_spec_path is not None:
                payload = root_api.scaffold_harness_payload(
                    config_root=Path(request.config_root),
                    harness_spec_path=Path(request.harness_spec_path),
                )
            else:
                raise ValueError("either spec_path or harness_spec_path is required")
            return root_api.success_response(payload)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/integrations/review")
    def integration_review(request: IntegrationReviewRequest) -> dict:
        import meta_harness.api.app as root_api

        try:
            if request.spec_path is not None:
                payload = root_api.review_integration_payload(
                    config_root=Path(request.config_root),
                    spec_path=Path(request.spec_path),
                    reviewer=request.reviewer,
                    approve_checks=list(request.approve_checks),
                    approve_all_checks=request.approve_all_checks,
                    overrides_path=Path(request.overrides_path)
                    if request.overrides_path is not None
                    else None,
                    notes=request.notes,
                    activate_binding=request.activate_binding,
                )
            elif request.harness_spec_path is not None:
                payload = root_api.review_harness_payload(
                    harness_spec_path=Path(request.harness_spec_path),
                    reviewer=request.reviewer,
                    approve_checks=list(request.approve_checks),
                    approve_all_checks=request.approve_all_checks,
                    overrides_path=Path(request.overrides_path)
                    if request.overrides_path is not None
                    else None,
                    notes=request.notes,
                )
            else:
                raise ValueError("either spec_path or harness_spec_path is required")
            return root_api.success_response(payload)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/integrations/benchmark")
    def integration_benchmark(request: IntegrationBenchmarkRequest) -> dict:
        import meta_harness.api.app as root_api

        try:
            return root_api.success_response(
                root_api.benchmark_integration_payload(
                    config_root=Path(request.config_root),
                    reports_root=Path(request.reports_root),
                    runs_root=Path(request.runs_root),
                    candidates_root=Path(request.candidates_root),
                    spec_path=Path(request.spec_path),
                    profile_name=request.profile,
                    project_name=request.project,
                    task_set_path=Path(request.task_set_path),
                    focus=request.focus,
                )
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/integrations/outer-loop")
    def integration_outer_loop(request: IntegrationOuterLoopRequest) -> dict:
        import meta_harness.api.app as root_api

        try:
            return root_api.success_response(
                root_api.harness_outer_loop_payload(
                    config_root=Path(request.config_root),
                    reports_root=Path(request.reports_root),
                    runs_root=Path(request.runs_root),
                    candidates_root=Path(request.candidates_root),
                    harness_spec_path=Path(request.harness_spec_path),
                    profile_name=request.profile,
                    project_name=request.project,
                    task_set_path=Path(request.task_set_path),
                    candidate_harness_patches=[
                        json.loads(Path(path).read_text(encoding="utf-8"))
                        for path in request.proposal_paths
                    ],
                    iteration_id=request.iteration_id,
                    focus=request.focus,
                )
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
