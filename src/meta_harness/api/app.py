from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from importlib import import_module

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from meta_harness.api.routes_core import register_core_routes
from meta_harness.api.routes_data_ops import register_data_ops_routes
from meta_harness.api.routes_dashboard import register_dashboard_routes
from meta_harness.api.routes_execution_ops import register_execution_ops_routes
from meta_harness.api.routes_integrations import register_integration_routes


_LAZY_ATTRS: dict[str, tuple[str, str]] = {
    "analyze_integration_payload": (
        "meta_harness.services.integration_service",
        "analyze_integration_payload",
    ),
    "benchmark_integration_payload": (
        "meta_harness.services.integration_service",
        "benchmark_integration_payload",
    ),
    "build_task_set_dataset_to_path": (
        "meta_harness.services.dataset_service",
        "build_task_set_dataset_to_path",
    ),
    "build_web_scrape_audit_benchmark_spec_payload": (
        "meta_harness.services.strategy_service",
        "build_web_scrape_audit_benchmark_spec_payload",
    ),
    "build_web_scrape_audit_report_payload": (
        "meta_harness.services.strategy_service",
        "build_web_scrape_audit_report_payload",
    ),
    "cancel_job_record": ("meta_harness.services.job_service", "cancel_job_record"),
    "candidate_current_view_payload": (
        "meta_harness.services.catalog_service",
        "candidate_current_view_payload",
    ),
    "compile_workflow_payload": (
        "meta_harness.services.workflow_service",
        "compile_workflow_payload",
    ),
    "create_annotation_record": (
        "meta_harness.services.annotation_service",
        "create_annotation_record",
    ),
    "create_candidate_from_strategy_card_payload": (
        "meta_harness.services.strategy_service",
        "create_candidate_from_strategy_card_payload",
    ),
    "derive_dataset_split_to_path": (
        "meta_harness.services.dataset_service",
        "derive_dataset_split_to_path",
    ),
    "evaluate_gate_policy_from_paths": (
        "meta_harness.services.gate_service",
        "evaluate_gate_policy_from_paths",
    ),
    "list_gate_history": ("meta_harness.services.gate_service", "list_gate_history"),
    "list_gate_results": ("meta_harness.services.gate_service", "list_gate_results"),
    "export_run_to_named_integration": (
        "meta_harness.services.export_service",
        "export_run_to_named_integration",
    ),
    "grade_trace_events": ("meta_harness.services.trace_service", "grade_trace_events"),
    "harness_outer_loop_payload": (
        "meta_harness.services.integration_service",
        "harness_outer_loop_payload",
    ),
    "ingest_dataset_annotations_to_path": (
        "meta_harness.services.dataset_service",
        "ingest_dataset_annotations_to_path",
    ),
    "inspect_strategy_card_payload": (
        "meta_harness.services.strategy_service",
        "inspect_strategy_card_payload",
    ),
    "inspect_workflow_payload": (
        "meta_harness.services.workflow_service",
        "inspect_workflow_payload",
    ),
    "list_annotation_records": (
        "meta_harness.services.annotation_service",
        "list_annotation_records",
    ),
    "list_champions": ("meta_harness.services.candidate_service", "list_champions"),
    "list_dataset_versions": (
        "meta_harness.services.dataset_service",
        "list_dataset_versions",
    ),
    "list_evaluator_reports": (
        "meta_harness.services.run_query_service",
        "list_evaluator_reports",
    ),
    "list_gate_policies": (
        "meta_harness.services.gate_policy_service",
        "list_gate_policies",
    ),
    "list_integrations": ("meta_harness.services.integration_service", "list_integrations"),
    "list_job_views": ("meta_harness.services.job_service", "list_job_views"),
    "list_proposals_payload": (
        "meta_harness.services.optimize_service",
        "list_proposals_payload",
    ),
    "list_profile_names": ("meta_harness.services.profile_service", "list_profile_names"),
    "list_project_names": ("meta_harness.services.project_service", "list_project_names"),
    "list_run_summaries": (
        "meta_harness.services.run_query_service",
        "list_run_summaries",
    ),
    "list_task_results": (
        "meta_harness.services.run_query_service",
        "list_task_results",
    ),
    "list_trace_events": (
        "meta_harness.services.run_query_service",
        "list_trace_events",
    ),
    "load_dataset_summary": (
        "meta_harness.services.dataset_service",
        "load_dataset_summary",
    ),
    "load_dataset_version": (
        "meta_harness.services.dataset_service",
        "load_dataset_version",
    ),
    "load_evaluator_report": (
        "meta_harness.services.run_query_service",
        "load_evaluator_report",
    ),
    "load_gate_policy": (
        "meta_harness.services.gate_policy_service",
        "load_gate_policy",
    ),
    "load_gate_result": ("meta_harness.services.gate_service", "load_gate_result"),
    "load_job_result": (
        "meta_harness.services.job_runtime_service",
        "load_job_result",
    ),
    "load_job_view": ("meta_harness.services.job_service", "load_job_view"),
    "load_proposal_payload": (
        "meta_harness.services.optimize_service",
        "load_proposal_payload",
    ),
    "load_run_summary": (
        "meta_harness.services.run_query_service",
        "load_run_summary",
    ),
    "load_task_result": (
        "meta_harness.services.run_query_service",
        "load_task_result",
    ),
    "materialize_proposal_payload": (
        "meta_harness.services.optimize_service",
        "materialize_proposal_payload",
    ),
    "observe_summary_payload": (
        "meta_harness.services.observation_service",
        "observe_summary_payload",
    ),
    "paginate_items": ("meta_harness.services.pagination", "paginate_items"),
    "promote_candidate_record": (
        "meta_harness.services.candidate_service",
        "promote_candidate_record",
    ),
    "promote_dataset_version": (
        "meta_harness.services.dataset_service",
        "promote_dataset_version",
    ),
    "recommend_web_scrape_strategy_cards_payload": (
        "meta_harness.services.strategy_service",
        "recommend_web_scrape_strategy_cards_payload",
    ),
    "retry_job": ("meta_harness.services.job_runtime_service", "retry_job"),
    "review_harness_payload": (
        "meta_harness.services.integration_service",
        "review_harness_payload",
    ),
    "review_integration_payload": (
        "meta_harness.services.integration_service",
        "review_integration_payload",
    ),
    "scaffold_harness_payload": (
        "meta_harness.services.integration_service",
        "scaffold_harness_payload",
    ),
    "scaffold_integration_payload": (
        "meta_harness.services.integration_service",
        "scaffold_integration_payload",
    ),
    "submit_dataset_extract_job": (
        "meta_harness.services.async_jobs",
        "submit_dataset_extract_job",
    ),
    "submit_observation_benchmark_job": (
        "meta_harness.services.async_jobs",
        "submit_observation_benchmark_job",
    ),
    "submit_optimize_loop_job": (
        "meta_harness.services.async_jobs",
        "submit_optimize_loop_job",
    ),
    "submit_optimize_propose_job": (
        "meta_harness.services.async_jobs",
        "submit_optimize_propose_job",
    ),
    "submit_run_export_trace_job": (
        "meta_harness.services.async_jobs",
        "submit_run_export_trace_job",
    ),
    "submit_run_score_job": (
        "meta_harness.services.async_jobs",
        "submit_run_score_job",
    ),
    "submit_strategy_benchmark_job": (
        "meta_harness.services.async_jobs",
        "submit_strategy_benchmark_job",
    ),
    "submit_workflow_benchmark_job": (
        "meta_harness.services.async_jobs",
        "submit_workflow_benchmark_job",
    ),
    "submit_workflow_benchmark_suite_job": (
        "meta_harness.services.async_jobs",
        "submit_workflow_benchmark_suite_job",
    ),
    "submit_workflow_run_job": (
        "meta_harness.services.async_jobs",
        "submit_workflow_run_job",
    ),
    "success_response": (
        "meta_harness.services.service_response",
        "success_response",
    ),
    "test_integration": ("meta_harness.services.integration_service", "test_integration"),
}


def __getattr__(name: str):
    target = _LAZY_ATTRS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


@dataclass(frozen=True)
class WorkspaceAuthContext:
    principal: str
    token_authenticated: bool
    workspace_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def create_app() -> FastAPI:
    app = FastAPI(title="Meta-Harness API", version="0.1.0")
    bearer_token = os.getenv("META_HARNESS_API_BEARER_TOKEN")
    workspace_header = os.getenv("META_HARNESS_API_WORKSPACE_HEADER", "X-Meta-Harness-Workspace")
    required_workspace_id = os.getenv("META_HARNESS_API_WORKSPACE_ID")
    app.state.idempotency_cache = {}

    @app.middleware("http")
    async def require_bearer_token(request: Request, call_next):
        if request.url.path == "/health":
            request.state.workspace_auth = WorkspaceAuthContext(
                principal="healthcheck",
                token_authenticated=False,
                workspace_id=required_workspace_id,
            )
            return await call_next(request)
        token_authenticated = False
        if bearer_token:
            if request.headers.get("Authorization") != f"Bearer {bearer_token}":
                return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
            token_authenticated = True
        requested_workspace_id = request.headers.get(workspace_header)
        if required_workspace_id and requested_workspace_id != required_workspace_id:
            return JSONResponse(status_code=403, content={"detail": "Workspace forbidden"})
        request.state.workspace_auth = WorkspaceAuthContext(
            principal="api_token" if token_authenticated else "anonymous",
            token_authenticated=token_authenticated,
            workspace_id=requested_workspace_id or required_workspace_id,
        )
        return await call_next(request)

    @app.middleware("http")
    async def apply_idempotency(request: Request, call_next):
        if request.method != "POST":
            return await call_next(request)
        key = request.headers.get("Idempotency-Key")
        if not key:
            return await call_next(request)

        body = await request.body()
        fingerprint = hashlib.sha256(
            b"|".join(
                [
                    request.method.encode("utf-8"),
                    request.url.path.encode("utf-8"),
                    body,
                ]
            )
        ).hexdigest()
        cache_key = f"{request.method}:{request.url.path}:{key}"
        cached = app.state.idempotency_cache.get(cache_key)
        if cached is not None:
            if cached["fingerprint"] != fingerprint:
                return JSONResponse(
                    status_code=409,
                    content={"detail": "Idempotency-Key conflict"},
                )
            return JSONResponse(
                status_code=int(cached["status_code"]),
                content=cached["body"],
            )

        async def receive() -> dict[str, object]:
            return {"type": "http.request", "body": body, "more_body": False}

        response = await call_next(Request(request.scope, receive))
        response_body = b""
        async for chunk in response.body_iterator:
            response_body += chunk

        media_type = response.media_type or response.headers.get("content-type")
        headers = dict(response.headers)
        rebuilt_response = Response(
            content=response_body,
            status_code=response.status_code,
            headers=headers,
            media_type=media_type,
        )
        if 200 <= response.status_code < 500 and "application/json" in str(media_type):
            app.state.idempotency_cache[cache_key] = {
                "fingerprint": fingerprint,
                "status_code": response.status_code,
                "body": json.loads(response_body.decode("utf-8") or "null"),
            }
        return rebuilt_response

    register_core_routes(app)
    register_data_ops_routes(app)
    register_integration_routes(app)
    register_execution_ops_routes(app)
    register_dashboard_routes(app)

    return app
