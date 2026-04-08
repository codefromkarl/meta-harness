from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from fastapi.testclient import TestClient

import meta_harness.services.integration_catalog_service as integration_catalog_service_module
import meta_harness.services.job_runtime_service as job_runtime_module
from meta_harness.api.app import create_app


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class _CaptureHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        self.__class__.requests.append(
            {
                "path": self.path,
                "headers": dict(self.headers.items()),
                "body": json.loads(body) if body else None,
            }
        )
        if self.path.endswith("/health"):
            payload = {"ok": True, "integration": "healthy"}
        else:
            payload = {"accepted": True}
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


class CaptureServer:
    def __init__(self) -> None:
        _CaptureHandler.requests = []
        self.server = HTTPServer(("127.0.0.1", 0), _CaptureHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    @property
    def requests(self) -> list[dict]:
        return list(_CaptureHandler.requests)

    def __enter__(self) -> "CaptureServer":
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def test_api_requires_bearer_token_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("META_HARNESS_API_BEARER_TOKEN", "secret-token")
    client = TestClient(create_app())

    missing = client.get("/runs")
    assert missing.status_code == 401

    authorized = client.get(
        "/runs",
        headers={"Authorization": "Bearer secret-token"},
    )
    assert authorized.status_code == 200


def test_api_runs_and_trace_support_filters_and_pagination(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    for run_id, profile, project, created_at in [
        ("run-001", "base", "demo", "2026-04-07T10:00:00Z"),
        ("run-002", "base", "demo", "2026-04-07T10:10:00Z"),
        ("run-003", "other", "demo", "2026-04-07T10:20:00Z"),
    ]:
        run_dir = runs_root / run_id
        task_dir = run_dir / "tasks" / "task-a"
        task_dir.mkdir(parents=True)
        write_json(
            run_dir / "run_metadata.json",
            {
                "run_id": run_id,
                "profile": profile,
                "project": project,
                "created_at": created_at,
            },
        )
        write_json(run_dir / "effective_config.json", {"evaluation": {"evaluators": ["basic"]}})
        write_json(
            task_dir / "task_result.json",
            {
                "task_id": "task-a",
                "success": True,
                "completed_phases": 2,
                "failed_phase": None,
            },
        )
        (task_dir / "steps.jsonl").write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "run_id": run_id,
                            "task_id": "task-a",
                            "step_id": "step-1",
                            "phase": "retrieval",
                            "status": "completed",
                            "latency_ms": 8,
                        }
                    ),
                    json.dumps(
                        {
                            "run_id": run_id,
                            "task_id": "task-a",
                            "step_id": "step-2",
                            "phase": "tool_call",
                            "status": "failed" if run_id == "run-002" else "completed",
                            "tool_name": "rg",
                            "latency_ms": 12,
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    client = TestClient(create_app())

    runs = client.get(
        "/runs",
        params={
            "runs_root": str(runs_root),
            "profile": "base",
            "limit": 1,
            "offset": 1,
        },
    )
    assert runs.status_code == 200
    runs_payload = runs.json()
    assert [item["run_id"] for item in runs_payload["items"]] == ["run-002"]
    assert runs_payload["page"] == {
        "limit": 1,
        "offset": 1,
        "total": 2,
        "has_more": False,
    }

    trace = client.get(
        "/runs/run-002/trace",
        params={
            "runs_root": str(runs_root),
            "phase": "tool_call",
            "status": "failed",
            "limit": 5,
            "offset": 0,
        },
    )
    assert trace.status_code == 200
    trace_payload = trace.json()
    assert len(trace_payload["items"]) == 1
    assert trace_payload["items"][0]["phase"] == "tool_call"
    assert trace_payload["items"][0]["status"] == "failed"
    assert trace_payload["page"]["total"] == 1


def test_api_can_cancel_job_records(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    write_json(
        reports_root / "jobs" / "job-123.json",
        {
            "job_id": "job-123",
            "job_type": "workflow.run",
            "status": "running",
            "job_input": {"workflow_path": "demo.json"},
        },
    )

    client = TestClient(create_app())
    response = client.post(
        "/jobs/job-123/cancel",
        params={"reports_root": str(reports_root)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["status"] == "cancelled"


def test_api_exposes_dataset_annotation_gate_and_integration_surfaces(tmp_path: Path) -> None:
    datasets_root = tmp_path / "datasets"
    annotations_root = tmp_path / "annotations"
    config_root = tmp_path / "configs"

    write_json(
        datasets_root / "benchmark-cases" / "v1" / "dataset.json",
        {
            "dataset_id": "benchmark-cases",
            "version": "v1",
            "schema_version": "2026-04-07",
            "case_count": 2,
            "cases": [
                {
                    "source_type": "task_set",
                    "run_id": "run-1",
                    "profile": "base",
                    "project": "demo",
                    "task_id": "task-a",
                    "phase": "retrieval",
                    "raw_error": "",
                    "failure_signature": "",
                },
                {
                    "source_type": "task_set",
                    "run_id": "run-2",
                    "profile": "base",
                    "project": "demo",
                    "task_id": "task-b",
                    "phase": "retrieval",
                    "raw_error": "",
                    "failure_signature": "",
                },
            ],
        },
    )
    write_json(
        config_root / "gate_policies" / "promotion.json",
        {
            "policy_id": "promotion",
            "policy_type": "promotion",
            "conditions": [],
        },
    )
    write_json(
        config_root / "integrations" / "otlp.json",
        {
            "name": "otlp",
            "kind": "otlp_http",
            "endpoint": "http://127.0.0.1:4318/v1/traces",
            "format": "otel-json",
        },
    )

    client = TestClient(create_app())

    datasets = client.get("/datasets", params={"datasets_root": str(datasets_root)})
    assert datasets.status_code == 200
    assert datasets.json()["items"][0]["dataset_id"] == "benchmark-cases"

    dataset_detail = client.get(
        "/datasets/benchmark-cases",
        params={"datasets_root": str(datasets_root)},
    )
    assert dataset_detail.status_code == 200
    assert dataset_detail.json()["versions"] == ["v1"]

    dataset_cases = client.get(
        "/datasets/benchmark-cases/versions/v1/cases",
        params={"datasets_root": str(datasets_root), "limit": 1, "offset": 1},
    )
    assert dataset_cases.status_code == 200
    assert len(dataset_cases.json()["items"]) == 1
    assert dataset_cases.json()["page"]["total"] == 2

    create_annotation = client.post(
        "/annotations",
        json={
            "annotations_root": str(annotations_root),
            "target_type": "run",
            "target_ref": "runs/run-1",
            "label": "verdict",
            "value": "needs-review",
            "notes": "manual spot check",
            "annotator": "tester",
        },
    )
    assert create_annotation.status_code == 200
    created = create_annotation.json()
    assert created["ok"] is True
    assert created["data"]["label"] == "verdict"

    annotations = client.get(
        "/annotations",
        params={
            "annotations_root": str(annotations_root),
            "target_type": "run",
            "label": "verdict",
        },
    )
    assert annotations.status_code == 200
    assert len(annotations.json()["items"]) == 1

    gate_policies = client.get(
        "/gate-policies",
        params={"config_root": str(config_root)},
    )
    assert gate_policies.status_code == 200
    assert gate_policies.json()["items"][0]["policy_id"] == "promotion"

    integrations = client.get(
        "/integrations",
        params={"config_root": str(config_root)},
    )
    assert integrations.status_code == 200
    assert integrations.json()["items"][0]["name"] == "otlp"


def test_api_grades_trace_semantics(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run-grade"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)
    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run-grade", "profile": "base", "project": "demo"},
    )
    write_json(run_dir / "effective_config.json", {"evaluation": {"evaluators": ["basic"]}})
    (task_dir / "steps.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "run_id": "run-grade",
                        "task_id": "task-a",
                        "step_id": "step-1",
                        "phase": "prompt",
                        "status": "completed",
                        "model": "gpt-5.4",
                        "latency_ms": 5,
                    }
                ),
                json.dumps(
                    {
                        "run_id": "run-grade",
                        "task_id": "task-a",
                        "step_id": "step-2",
                        "phase": "retrieval",
                        "status": "completed",
                        "retrieval_refs": ["memory://auth"],
                        "latency_ms": 9,
                    }
                ),
                json.dumps(
                    {
                        "run_id": "run-grade",
                        "task_id": "task-a",
                        "step_id": "step-3",
                        "phase": "tool_call",
                        "status": "failed",
                        "tool_name": "rg",
                        "error": "tool failed",
                        "latency_ms": 14,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    client = TestClient(create_app())
    response = client.get(
        "/runs/run-grade/trace/grade",
        params={"runs_root": str(runs_root)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == "run-grade"
    assert payload["event_count"] == 3
    assert payload["event_kind_counts"]["model"] == 1
    assert payload["event_kind_counts"]["retrieval"] == 1
    assert payload["event_kind_counts"]["tool"] == 1
    assert payload["failure_count"] == 1
    assert payload["issues"][0]["code"] == "trace.has_failures"


def test_api_exports_trace_to_configured_integration(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    reports_root = tmp_path / "reports"
    config_root = tmp_path / "configs"
    run_dir = runs_root / "run123"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)

    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run123", "profile": "base", "project": "demo"},
    )
    write_json(run_dir / "effective_config.json", {"evaluation": {"evaluators": ["basic"]}})
    (task_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "run_id": "run123",
                "task_id": "task-a",
                "step_id": "step-1",
                "phase": "tool_call",
                "status": "completed",
                "tool_name": "rg",
                "latency_ms": 12,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with CaptureServer() as server:
        write_json(
            config_root / "integrations" / "otlp.json",
            {
                "name": "otlp",
                "kind": "otlp_http",
                "endpoint": f"{server.base_url}/v1/traces",
                "healthcheck_endpoint": f"{server.base_url}/health",
                "format": "otel-json",
                "headers": {"Authorization": "Bearer integration-token"},
            },
        )
        client = TestClient(create_app())

        export_response = client.post(
            "/runs/run123/export-trace",
            json={
                "reports_root": str(reports_root),
                "runs_root": str(runs_root),
                "config_root": str(config_root),
                "destination": "integration",
                "integration_name": "otlp",
                "format": "otel-json",
            },
        )
        assert export_response.status_code == 200
        payload = export_response.json()
        assert payload["ok"] is True
        assert payload["data"]["destination"] == "integration"
        assert payload["data"]["integration"]["name"] == "otlp"

        integration_test = client.post(
            "/integrations/otlp/test",
            params={"config_root": str(config_root)},
        )
        assert integration_test.status_code == 200
        assert integration_test.json()["ok"] is True
        assert integration_test.json()["data"]["status_code"] == 200

        assert len(server.requests) == 2
        export_request = server.requests[0]
        assert export_request["path"] == "/v1/traces"
        assert export_request["headers"]["Authorization"] == "Bearer integration-token"
        assert export_request["body"]["run_id"] == "run123"


def test_api_returns_classified_integration_export_failure(tmp_path: Path, monkeypatch) -> None:
    runs_root = tmp_path / "runs"
    config_root = tmp_path / "configs"
    run_dir = runs_root / "run123"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)

    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run123", "profile": "base", "project": "demo"},
    )
    write_json(run_dir / "effective_config.json", {"evaluation": {"evaluators": ["basic"]}})
    (task_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "run_id": "run123",
                "task_id": "task-a",
                "step_id": "step-1",
                "phase": "tool_call",
                "status": "completed",
                "tool_name": "rg",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    write_json(
        config_root / "integrations" / "otlp.json",
        {
            "name": "otlp",
            "kind": "otlp_http",
            "endpoint": "http://127.0.0.1:4318/v1/traces",
            "retry_limit": 1,
            "retry_backoff_sec": 0.0,
        },
    )

    attempts = {"count": 0}

    def fake_post_json(**kwargs):  # type: ignore[no-untyped-def]
        attempts["count"] += 1
        return {"status_code": 503, "body": {"accepted": False}}

    monkeypatch.setattr(integration_catalog_service_module, "_post_json", fake_post_json)

    client = TestClient(create_app())
    response = client.post(
        "/integrations/otlp/export-runs/run123",
        params={"config_root": str(config_root), "runs_root": str(runs_root)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["integration"]["ok"] is False
    assert payload["data"]["integration"]["failure_kind"] == "retryable_http"
    assert payload["data"]["integration"]["retryable"] is True
    assert payload["data"]["integration"]["retry_exhausted"] is True
    assert payload["data"]["integration"]["attempt_count"] == 2
    assert attempts["count"] == 2


def test_api_returns_classified_connection_error_for_integration_export(
    tmp_path: Path, monkeypatch
) -> None:
    runs_root = tmp_path / "runs"
    config_root = tmp_path / "configs"
    run_dir = runs_root / "run123"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)

    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run123", "profile": "base", "project": "demo"},
    )
    write_json(run_dir / "effective_config.json", {"evaluation": {"evaluators": ["basic"]}})
    (task_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "run_id": "run123",
                "task_id": "task-a",
                "step_id": "step-1",
                "phase": "tool_call",
                "status": "completed",
                "tool_name": "rg",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    write_json(
        config_root / "integrations" / "otlp.json",
        {
            "name": "otlp",
            "kind": "otlp_http",
            "endpoint": "http://127.0.0.1:4318/v1/traces",
            "retry_limit": 1,
            "retry_backoff_sec": 0.0,
        },
    )

    attempts = {"count": 0}

    def fake_post_json(**kwargs):  # type: ignore[no-untyped-def]
        attempts["count"] += 1
        raise ConnectionError("connection refused")

    monkeypatch.setattr(integration_catalog_service_module, "_post_json", fake_post_json)

    client = TestClient(create_app())
    response = client.post(
        "/integrations/otlp/export-runs/run123",
        params={"config_root": str(config_root), "runs_root": str(runs_root)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["integration"]["ok"] is False
    assert payload["data"]["integration"]["failure_kind"] == "connection_error"
    assert payload["data"]["integration"]["retryable"] is True
    assert payload["data"]["integration"]["retry_exhausted"] is True
    assert payload["data"]["integration"]["attempt_count"] == 2
    assert payload["data"]["integration"]["error"] == "connection refused"
    assert attempts["count"] == 2


def test_api_returns_task_and_evaluator_detail_endpoints(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run-detail"
    task_dir = run_dir / "tasks" / "task-a"
    evaluators_dir = run_dir / "evaluators"
    task_dir.mkdir(parents=True)
    evaluators_dir.mkdir(parents=True)

    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run-detail", "profile": "base", "project": "demo"},
    )
    write_json(run_dir / "effective_config.json", {"evaluation": {"evaluators": ["basic"]}})
    write_json(
        task_dir / "task_result.json",
        {
            "task_id": "task-a",
            "success": False,
            "completed_phases": 1,
            "failed_phase": "tool_call",
        },
    )
    write_json(
        evaluators_dir / "basic.json",
        {
            "correctness": {"task_count": 1},
            "composite": 0.4,
        },
    )

    client = TestClient(create_app())
    task_response = client.get(
        "/runs/run-detail/tasks/task-a",
        params={"runs_root": str(runs_root)},
    )
    evaluator_response = client.get(
        "/runs/run-detail/evaluators/basic",
        params={"runs_root": str(runs_root)},
    )

    assert task_response.status_code == 200
    assert task_response.json()["task_id"] == "task-a"
    assert task_response.json()["failed_phase"] == "tool_call"
    assert evaluator_response.status_code == 200
    assert evaluator_response.json()["name"] == "basic"
    assert evaluator_response.json()["status"] == "completed"
    assert evaluator_response.json()["report"]["composite"] == 0.4


def test_api_returns_evaluator_profiling_and_trace_artifact_for_envelope(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run-evaluator-envelope"
    evaluators_dir = run_dir / "evaluators"
    evaluators_dir.mkdir(parents=True)

    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run-evaluator-envelope", "profile": "base", "project": "demo"},
    )
    write_json(run_dir / "effective_config.json", {"evaluation": {"evaluators": ["basic"]}})
    write_json(
        evaluators_dir / "basic.json",
        {
            "evaluator_name": "basic",
            "run_id": "run-evaluator-envelope",
            "status": "completed",
            "report": {"composite": 0.9},
            "trace_grade": {"event_count": 2},
            "profiling": {"input_task_count": 1, "input_trace_event_count": 4},
            "trace_artifact": "runs/run-evaluator-envelope/evaluators/basic.trace.jsonl",
            "artifact_refs": ["runs/run-evaluator-envelope/evaluators/basic.json"],
        },
    )

    client = TestClient(create_app())
    evaluator_response = client.get(
        "/runs/run-evaluator-envelope/evaluators/basic",
        params={"runs_root": str(runs_root)},
    )

    assert evaluator_response.status_code == 200
    payload = evaluator_response.json()
    assert payload["name"] == "basic"
    assert payload["profiling"]["input_task_count"] == 1
    assert payload["profiling"]["input_trace_event_count"] == 4
    assert payload["trace_artifact"] == "runs/run-evaluator-envelope/evaluators/basic.trace.jsonl"
    assert payload["trace_grade"]["event_count"] == 2


def test_api_evaluates_gate_policy_by_policy_id(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    policy_path = config_root / "gate_policies" / "promotion.json"
    target_path = tmp_path / "reports" / "promotion-target.json"

    write_json(
        policy_path,
        {
            "policy_id": "promotion",
            "policy_type": "promotion",
            "conditions": [
                {
                    "kind": "min_evidence_count",
                    "path": "promotion_summary.evidence_run_count",
                    "value": 2,
                }
            ],
        },
    )
    write_json(
        target_path,
        {
            "promotion_summary": {
                "evidence_run_count": 2,
            }
        },
    )

    client = TestClient(create_app())
    response = client.post(
        "/gate-policies/promotion/evaluate",
        json={
            "config_root": str(config_root),
            "target_path": str(target_path),
            "target_type": "promotion",
            "target_ref": "candidates/cand123/promotion_target.json",
            "evidence_refs": ["runs/run-1/score_report.json", "runs/run-2/score_report.json"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["status"] == "passed"
    assert payload["data"]["policy"]["policy_id"] == "promotion"


def test_api_honors_idempotency_key_for_post_jobs(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    reports_root = tmp_path / "reports"
    run_dir = runs_root / "run123"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)

    write_json(
        run_dir / "effective_config.json",
        {"evaluation": {"evaluators": ["basic"]}},
    )
    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run123", "profile": "base", "project": "demo"},
    )
    (task_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "step_id": "step-1",
                "phase": "review",
                "status": "completed",
                "latency_ms": 15,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    client = TestClient(create_app())
    headers = {"Idempotency-Key": "run-score-001"}
    request_payload = {
        "reports_root": str(reports_root),
        "runs_root": str(runs_root),
        "requested_by": "tester",
    }

    first = client.post("/runs/run123/score", json=request_payload, headers=headers)
    second = client.post("/runs/run123/score", json=request_payload, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["job"]["job_id"] == second.json()["job"]["job_id"]
    assert len(list((reports_root / "jobs").glob("*.json"))) == 1


def test_api_can_retry_job_and_fetch_full_result(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    reports_root = tmp_path / "reports"
    run_dir = runs_root / "run123"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)

    write_json(
        run_dir / "effective_config.json",
        {"evaluation": {"evaluators": ["basic"]}},
    )
    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run123", "profile": "base", "project": "demo"},
    )
    (task_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "step_id": "step-1",
                "phase": "review",
                "status": "completed",
                "latency_ms": 15,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    client = TestClient(create_app())
    first = client.post(
        "/runs/run123/score",
        json={
            "reports_root": str(reports_root),
            "runs_root": str(runs_root),
            "requested_by": "tester",
        },
    )
    assert first.status_code == 200
    first_job_id = first.json()["job"]["job_id"]

    retried = client.post(
        f"/jobs/{first_job_id}/retry",
        params={"reports_root": str(reports_root)},
    )
    assert retried.status_code == 200
    retried_payload = retried.json()
    assert retried_payload["ok"] is True
    assert retried_payload["job"]["parent_job_id"] == first_job_id
    assert retried_payload["job"]["attempt"] == 2

    result = client.get(
        f"/jobs/{retried_payload['job']['job_id']}/result",
        params={"reports_root": str(reports_root), "repo_root": str(tmp_path)},
    )
    assert result.status_code == 200
    assert result.json()["target_type"] == "run"
    assert result.json()["artifact"]["composite"] == 1.0


def test_api_job_detail_includes_loop_result_preview(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    loop_report = reports_root / "loops" / "loop-123" / "loop.json"
    write_json(
        loop_report,
        {
            "loop_id": "loop-123",
            "best_candidate_id": "cand-1",
            "best_run_id": "run-1",
            "iteration_count": 2,
            "stop_reason": "max iterations reached",
        },
    )
    job_path = reports_root / "jobs" / "job-loop.json"
    write_json(
        job_path,
        {
            "job_id": "job-loop",
            "job_type": "optimize.loop",
            "status": "succeeded",
            "job_input": {},
            "result_ref": {
                "target_type": "loop",
                "target_id": "loop-123",
                "path": "reports/loops/loop-123/loop.json",
            },
            "error": None,
            "created_at": "2026-04-08T00:00:00Z",
            "started_at": "2026-04-08T00:00:01Z",
            "completed_at": "2026-04-08T00:00:02Z",
        },
    )

    client = TestClient(create_app())
    response = client.get(
        "/jobs/job-loop",
        params={"reports_root": str(reports_root), "repo_root": str(tmp_path)},
    )

    assert response.status_code == 200
    assert response.json()["result_preview"] == {
        "target_type": "loop",
        "target_id": "loop-123",
        "best_candidate_id": "cand-1",
        "best_run_id": "run-1",
        "iteration_count": 2,
        "stop_reason": "max iterations reached",
    }


def test_api_lists_jobs_with_loop_result_preview(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    loop_report = reports_root / "loops" / "loop-123" / "loop.json"
    write_json(
        loop_report,
        {
            "loop_id": "loop-123",
            "best_candidate_id": "cand-1",
            "best_run_id": "run-1",
            "iteration_count": 2,
            "stop_reason": "max iterations reached",
        },
    )
    write_json(
        reports_root / "jobs" / "job-loop.json",
        {
            "job_id": "job-loop",
            "job_type": "optimize.loop",
            "status": "succeeded",
            "job_input": {},
            "result_ref": {
                "target_type": "loop",
                "target_id": "loop-123",
                "path": "reports/loops/loop-123/loop.json",
            },
            "error": None,
            "created_at": "2026-04-08T00:00:00Z",
            "started_at": "2026-04-08T00:00:01Z",
            "completed_at": "2026-04-08T00:00:02Z",
        },
    )

    client = TestClient(create_app())
    response = client.get(
        "/jobs",
        params={"reports_root": str(reports_root), "repo_root": str(tmp_path)},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["result_preview"] == {
        "target_type": "loop",
        "target_id": "loop-123",
        "best_candidate_id": "cand-1",
        "best_run_id": "run-1",
        "iteration_count": 2,
        "stop_reason": "max iterations reached",
    }


def test_api_can_retry_optimize_loop_job_and_fetch_loop_result(
    tmp_path: Path, monkeypatch
) -> None:
    reports_root = tmp_path / "reports"
    write_json(
        reports_root / "jobs" / "job-loop.json",
        {
            "job_id": "job-loop",
            "job_type": "optimize.loop",
            "status": "succeeded",
            "requested_by": "tester",
            "attempt": 1,
            "job_input": {
                "reports_root": str(reports_root),
                "config_root": str(tmp_path / "configs"),
                "runs_root": str(tmp_path / "runs"),
                "candidates_root": str(tmp_path / "candidates"),
                "proposals_root": str(tmp_path / "proposals"),
                "profile": "base",
                "project": "demo",
                "task_set_path": str(tmp_path / "task_set.json"),
                "loop_id": "loop-123",
                "plugin_id": "web_scrape",
                "proposer_id": "heuristic",
                "max_iterations": 3,
                "focus": "retrieval",
            },
            "result_ref": {
                "target_type": "loop",
                "target_id": "loop-123",
                "path": "reports/loops/loop-123/loop.json",
            },
            "error": None,
            "created_at": "2026-04-08T00:00:00Z",
            "started_at": "2026-04-08T00:00:01Z",
            "completed_at": "2026-04-08T00:00:02Z",
        },
    )

    def fake_submit_optimize_loop_job(**kwargs):
        assert kwargs["parent_job_id"] == "job-loop"
        assert kwargs["attempt"] == 2
        loop_report = reports_root / "loops" / "loop-123" / "loop.json"
        write_json(
            loop_report,
            {
                "loop_id": "loop-123",
                "best_candidate_id": "cand-2",
                "best_run_id": "run-2",
                "iteration_count": 3,
                "stop_reason": "target score reached",
            },
        )
        payload = {
            "ok": True,
            "data": {
                "loop_id": "loop-123",
                "best_candidate_id": "cand-2",
                "best_run_id": "run-2",
            },
            "job": {
                "job_id": "job-loop-retry",
                "job_type": "optimize.loop",
                "status": "succeeded",
                "parent_job_id": "job-loop",
                "attempt": 2,
                "result_ref": {
                    "target_type": "loop",
                    "target_id": "loop-123",
                    "path": "reports/loops/loop-123/loop.json",
                },
            },
        }
        write_json(reports_root / "jobs" / "job-loop-retry.json", payload["job"])
        return payload

    monkeypatch.setattr(
        job_runtime_module,
        "submit_optimize_loop_job",
        fake_submit_optimize_loop_job,
    )

    client = TestClient(create_app())
    retried = client.post(
        "/jobs/job-loop/retry",
        params={"reports_root": str(reports_root)},
    )

    assert retried.status_code == 200
    retried_payload = retried.json()
    assert retried_payload["ok"] is True
    assert retried_payload["job"]["job_type"] == "optimize.loop"
    assert retried_payload["job"]["parent_job_id"] == "job-loop"
    assert retried_payload["job"]["attempt"] == 2

    result = client.get(
        "/jobs/job-loop-retry/result",
        params={"reports_root": str(reports_root), "repo_root": str(tmp_path)},
    )
    assert result.status_code == 200
    assert result.json()["target_type"] == "loop"
    assert result.json()["artifact"]["best_candidate_id"] == "cand-2"


def test_api_can_export_run_directly_via_vendor_integration_kind(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    config_root = tmp_path / "configs"
    run_dir = runs_root / "run123"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)

    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run123", "profile": "base", "project": "demo"},
    )
    write_json(run_dir / "effective_config.json", {"evaluation": {"evaluators": ["basic"]}})
    (task_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "run_id": "run123",
                "task_id": "task-a",
                "step_id": "step-1",
                "phase": "tool_call",
                "status": "completed",
                "tool_name": "rg",
                "latency_ms": 12,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with CaptureServer() as server:
        write_json(
            config_root / "integrations" / "phoenix.json",
            {
                "name": "phoenix",
                "kind": "phoenix",
                "endpoint": f"{server.base_url}/phoenix/traces",
            },
        )
        write_json(
            config_root / "integrations" / "langfuse.json",
            {
                "name": "langfuse",
                "kind": "langfuse",
                "endpoint": f"{server.base_url}/langfuse/ingest",
            },
        )

        client = TestClient(create_app())
        phoenix = client.post(
            "/integrations/phoenix/export-runs/run123",
            params={"config_root": str(config_root), "runs_root": str(runs_root)},
        )
        langfuse = client.post(
            "/integrations/langfuse/export-runs/run123",
            params={"config_root": str(config_root), "runs_root": str(runs_root)},
        )

        assert phoenix.status_code == 200
        assert langfuse.status_code == 200
        assert phoenix.json()["ok"] is True
        assert langfuse.json()["ok"] is True
        assert phoenix.json()["data"]["format"] == "phoenix-json"
        assert langfuse.json()["data"]["format"] == "langfuse-json"

        assert len(server.requests) == 2
        phoenix_request = server.requests[0]
        langfuse_request = server.requests[1]
        assert phoenix_request["path"] == "/phoenix/traces"
        assert "project_name" in phoenix_request["body"]
        assert "traces" in phoenix_request["body"]
        assert langfuse_request["path"] == "/langfuse/ingest"
        assert "trace" in langfuse_request["body"]
        assert "observations" in langfuse_request["body"]
