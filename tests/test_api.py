from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import meta_harness.api.app as api_app_module
from meta_harness.api.app import create_app
from meta_harness.api.contracts import (
    DatasetExtractFailuresRequest,
    OptimizeLoopRequest,
    PromoteCandidateRequest,
    RunExportTraceRequest,
    RunScoreRequest,
)
from meta_harness.services.gate_service import evaluate_gate_policy


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_api_healthcheck() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_serves_dashboard_shell(tmp_path: Path) -> None:
    client = TestClient(create_app())

    response = client.get(
        "/dashboard",
        params={
            "config_root": str(tmp_path / "configs"),
            "runs_root": str(tmp_path / "runs"),
            "reports_root": str(tmp_path / "reports"),
            "datasets_root": str(tmp_path / "datasets"),
            "candidates_root": str(tmp_path / "candidates"),
        },
    )

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Meta-Harness Dashboard" in response.text
    assert '"runsRoot": "' + str(tmp_path / "runs") + '"' in response.text
    assert '"benchmarks": "/dashboard/benchmarks"' in response.text
    assert '"candidatesCurrent": "/candidates/current"' in response.text


def test_api_lists_profiles_projects_runs_and_jobs(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    reports_root = tmp_path / "reports"

    write_json(config_root / "profiles" / "base.json", {"description": "base"})
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )
    run_dir = runs_root / "run123"
    (run_dir / "tasks").mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)
    write_json(
        run_dir / "run_metadata.json",
        {
            "run_id": "run123",
            "profile": "base",
            "project": "demo",
            "created_at": "2026-04-05T10:00:00Z",
        },
    )
    write_json(run_dir / "effective_config.json", {"budget": {"max_turns": 12}})
    write_json(
        reports_root / "jobs" / "job123.json",
        {
            "job_id": "job123",
            "job_type": "run.score",
            "status": "queued",
            "job_input": {"run_id": "run123"},
        },
    )

    client = TestClient(create_app())

    profiles = client.get("/profiles", params={"config_root": str(config_root)})
    projects = client.get("/projects", params={"config_root": str(config_root)})
    runs = client.get("/runs", params={"runs_root": str(runs_root)})
    jobs = client.get("/jobs", params={"reports_root": str(reports_root)})

    assert profiles.status_code == 200
    assert profiles.json()["items"] == ["base"]
    assert projects.status_code == 200
    assert projects.json()["items"] == ["demo"]
    assert runs.status_code == 200
    assert runs.json()["items"] == [
        {
            "run_id": "run123",
            "profile": "base",
            "project": "demo",
            "composite": "-",
        }
    ]
    assert jobs.status_code == 200
    assert jobs.json()["items"][0]["job_id"] == "job123"


def test_api_submits_run_score_job(tmp_path: Path) -> None:
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
    response = client.post(
        "/runs/run123/score",
        json={
            "reports_root": str(reports_root),
            "runs_root": str(runs_root),
            "requested_by": "tester",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["composite"] == 1.0
    assert payload["job"]["job_type"] == "run.score"


def test_api_submits_run_export_trace_job(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    reports_root = tmp_path / "reports"
    output_path = tmp_path / "exports" / "trace.json"
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

    client = TestClient(create_app())
    response = client.post(
        "/runs/run123/export-trace",
        json={
            "reports_root": str(reports_root),
            "runs_root": str(runs_root),
            "output_path": str(output_path),
            "format": "otel-json",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["output_path"] == str(output_path)
    assert payload["job"]["job_type"] == "run.export_trace"


def test_api_builds_task_set_dataset_artifact(tmp_path: Path) -> None:
    task_set_path = tmp_path / "task_set.json"
    output_path = tmp_path / "datasets" / "benchmark-cases" / "v1" / "dataset.json"
    write_json(
        task_set_path,
        {
            "tasks": [
                {
                    "task_id": "task-a",
                    "dataset_case": {
                        "query": "find SearchService",
                        "expected_paths": ["src/search/SearchService.ts"],
                    },
                    "phases": [{"phase": "benchmark_probe", "command": ["python", "-c", "print('ok')"]}],
                }
            ]
        },
    )

    client = TestClient(create_app())
    response = client.post(
        "/datasets/build-task-set",
        json={
            "task_set_path": str(task_set_path),
            "output_path": str(output_path),
            "dataset_id": "benchmark-cases",
            "version": "v1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["dataset_id"] == "benchmark-cases"
    assert output_path.exists()


def test_api_ingests_annotations_and_derives_dataset_split(tmp_path: Path) -> None:
    dataset_path = tmp_path / "datasets" / "benchmark-cases" / "v1" / "dataset.json"
    enriched_output = tmp_path / "datasets" / "benchmark-cases" / "v2" / "dataset.json"
    split_output = tmp_path / "datasets" / "benchmark-cases-hard" / "v1" / "dataset.json"
    annotations_path = tmp_path / "annotations.json"
    write_json(
        dataset_path,
        {
            "dataset_id": "benchmark-cases",
            "version": "v1",
            "schema_version": "2026-04-06",
            "case_count": 1,
            "cases": [
                {
                    "case_id": "task_set:task-a",
                    "source_type": "task_set",
                    "run_id": "task-set",
                    "profile": "task-set",
                    "project": "task-set",
                    "task_id": "task-a",
                    "phase": "benchmark_probe",
                    "raw_error": "",
                    "failure_signature": "",
                }
            ],
        },
    )
    write_json(
        annotations_path,
        [
            {
                "annotation_id": "ann-1",
                "target_type": "dataset_case",
                "target_ref": "task_set:task-a",
                "label": "hard_case",
                "value": True,
                "annotator": "reviewer",
            }
        ],
    )

    client = TestClient(create_app())
    ingest = client.post(
        "/datasets/ingest-annotations",
        json={
            "dataset_path": str(dataset_path),
            "annotations_path": str(annotations_path),
            "output_path": str(enriched_output),
        },
    )
    derive = client.post(
        "/datasets/derive-split",
        json={
            "dataset_path": str(enriched_output),
            "output_path": str(split_output),
            "split": "hard_case",
            "dataset_id": "benchmark-cases-hard",
            "version": "v1",
        },
    )

    assert ingest.status_code == 200
    assert derive.status_code == 200
    assert ingest.json()["data"]["annotation_count"] == 1
    assert derive.json()["data"]["case_count"] == 1
    assert split_output.exists()


def test_api_promotes_dataset_version(tmp_path: Path) -> None:
    datasets_root = tmp_path / "datasets"
    dataset_path = datasets_root / "benchmark-cases" / "v2" / "dataset.json"
    write_json(
        dataset_path,
        {
            "dataset_id": "benchmark-cases",
            "version": "v2",
            "schema_version": "2026-04-06",
            "case_count": 1,
            "cases": [],
            "split": "adversarial",
        },
    )

    client = TestClient(create_app())
    response = client.post(
        "/datasets/promote",
        json={
            "datasets_root": str(datasets_root),
            "dataset_id": "benchmark-cases",
            "version": "v2",
            "split": "adversarial",
            "promoted_by": "api-user",
            "reason": "use in nightly",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["promotion_record"]["promoted_by"] == "api-user"


def test_api_evaluates_gate_policy(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.json"
    target_path = tmp_path / "target.json"
    write_json(
        policy_path,
        {
            "policy_id": "default-benchmark",
            "policy_type": "benchmark",
            "conditions": [
                {
                    "kind": "benchmark_has_valid_variant",
                    "path": "variants",
                    "value": True,
                }
            ],
        },
    )
    write_json(target_path, {"variants": [{"name": "baseline"}]})

    client = TestClient(create_app())
    response = client.post(
        "/gates/evaluate",
        json={
            "policy_path": str(policy_path),
            "target_path": str(target_path),
            "target_type": "benchmark_experiment",
            "target_ref": "reports/benchmarks/demo.json",
            "evidence_refs": [],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["status"] == "passed"


def test_api_lists_and_loads_gate_results(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    payload = evaluate_gate_policy(
        policy={"policy_id": "benchmark-a", "policy_type": "benchmark", "conditions": []},
        target_payload={"variants": []},
        target_type="benchmark_experiment",
        target_ref="reports/benchmarks/a.json",
        reports_root=reports_root,
        persist_result=True,
    )

    client = TestClient(create_app())
    listed = client.get(
        "/gates/results",
        params={"reports_root": str(reports_root), "policy_id": "benchmark-a"},
    )
    shown = client.get(
        f"/gates/results/{payload['gate_id']}",
        params={"reports_root": str(reports_root)},
    )

    assert listed.status_code == 200
    assert shown.status_code == 200
    assert listed.json()["items"][0]["gate_id"] == payload["gate_id"]
    assert shown.json()["policy_id"] == "benchmark-a"
    history = client.get(
        "/gates/history",
        params={"reports_root": str(reports_root), "policy_id": "benchmark-a"},
    )
    assert history.status_code == 200
    assert history.json()["items"][0]["gate_id"] == payload["gate_id"]


def test_api_workflow_compile_rejects_artifact_drift_early(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    workflow_path = tmp_path / "workflows" / "news_aggregation.json"
    output_path = tmp_path / "compiled" / "news_aggregation.task_set.json"
    write_json(
        config_root / "primitives" / "web_scrape.json",
        {
            "primitive_id": "web_scrape",
            "kind": "browser_interaction",
            "evaluation_contract": {
                "artifact_requirements": ["page.html", "extracted.json"],
            },
        },
    )
    write_json(
        config_root / "evaluator_packs" / "web_scrape_core.json",
        {
            "pack_id": "web_scrape/core",
            "supported_primitives": ["web_scrape"],
            "command": ["python", "scripts/eval_web_scrape.py"],
            "artifact_requirements": ["page.html"],
        },
    )
    write_json(
        workflow_path,
        {
            "workflow_id": "news_aggregation",
            "evaluator_packs": ["web_scrape/core"],
            "steps": [
                {
                    "step_id": "fetch_homepages",
                    "primitive_id": "web_scrape",
                    "command": ["python", "scripts/fetch.py"],
                }
            ],
        },
    )

    client = TestClient(create_app())
    response = client.post(
        "/workflows/compile",
        json={
            "workflow_path": str(workflow_path),
            "output_path": str(output_path),
            "config_root": str(config_root),
        },
    )

    assert response.status_code == 400
    assert "artifact requirements" in response.json()["detail"]


def test_api_recommends_web_scrape_strategy_cards() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    client = TestClient(create_app())

    response = client.post(
        "/strategies/recommend-web-scrape",
        json={
            "config_root": str(repo_root / "configs"),
            "page_profile": {
                "complexity": "high",
                "requires_rendering": True,
                "anti_bot_level": "high",
            },
            "workload_profile": {
                "usage_mode": "ad_hoc",
            },
            "limit": 2,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_strategy_id"] == "web_scrape/vlm-visual-extract"
    assert len(payload["recommendations"]) == 2
    assert payload["assessment"]["page_bucket"] == "high"
    assert payload["primary_recommendation"]["strategy_id"] == "web_scrape/vlm-visual-extract"


def test_api_builds_web_scrape_audit_report(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    benchmark_report = tmp_path / "reports" / "benchmarks" / "api-web-scrape-audit.json"
    benchmark_report.parent.mkdir(parents=True, exist_ok=True)
    benchmark_report.write_text(
        json.dumps(
            {
                "experiment": "api-web-scrape-audit",
                "best_variant": "selector_only",
                "best_by_quality": "selector_only",
                "best_by_stability": "selector_only",
            }
        ),
        encoding="utf-8",
    )

    client = TestClient(create_app())
    response = client.post(
        "/strategies/audit-web-scrape",
        json={
            "config_root": str(repo_root / "configs"),
            "page_profile": {
                "complexity": "high",
                "requires_rendering": True,
                "anti_bot_level": "high",
            },
            "workload_profile": {
                "usage_mode": "ad_hoc",
            },
            "benchmark_report_path": str(benchmark_report),
            "limit": 2,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["primary_recommendation"]["strategy_id"] == "web_scrape/vlm-visual-extract"
    assert payload["alignment"]["benchmark_best_variant"] == "selector_only"
    assert payload["alignment"]["aligned"] is False


def test_api_builds_web_scrape_audit_benchmark_spec(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    output_path = tmp_path / "audit-benchmark.json"
    client = TestClient(create_app())

    response = client.post(
        "/strategies/build-web-scrape-audit-spec",
        json={
            "config_root": str(repo_root / "configs"),
            "page_profile": {
                "complexity": "low",
                "requires_rendering": False,
            },
            "workload_profile": {
                "usage_mode": "recurring",
                "batch_size": 50,
            },
            "output_path": str(output_path),
            "limit": 2,
            "repeats": 2,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["output_path"] == str(output_path)
    assert payload["benchmark_spec"]["repeats"] == 2
    assert output_path.exists()


def test_api_submits_dataset_extract_failures_job(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    reports_root = tmp_path / "reports"
    output_path = tmp_path / "datasets" / "failure_cases.json"
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
                "phase": "compile",
                "status": "failed",
                "error": "Trait bound `Foo: Clone` is not satisfied",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    client = TestClient(create_app())
    response = client.post(
        "/datasets/extract-failures",
        json={
            "reports_root": str(reports_root),
            "runs_root": str(runs_root),
            "output_path": str(output_path),
            "requested_by": "tester",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["dataset_id"] == "failure-signatures"
    assert payload["job"]["job_type"] == "dataset.extract_failures"


def test_api_returns_run_detail_and_task_list(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run123"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)

    write_json(
        run_dir / "run_metadata.json",
        {
            "run_id": "run123",
            "profile": "base",
            "project": "demo",
            "created_at": "2026-04-05T10:00:00Z",
        },
    )
    write_json(run_dir / "effective_config.json", {"budget": {"max_turns": 12}})
    write_json(
        run_dir / "score_report.json",
        {
            "correctness": {"task_count": 1, "completed_steps": 2},
            "cost": {"trace_event_count": 2},
            "maintainability": {},
            "architecture": {},
            "retrieval": {},
            "human_collaboration": {},
            "composite": 2.0,
        },
    )
    write_json(
        task_dir / "task_result.json",
        {
            "task_id": "task-a",
            "success": True,
            "completed_phases": 2,
            "failed_phase": None,
        },
    )

    client = TestClient(create_app())

    run_response = client.get("/runs/run123", params={"runs_root": str(runs_root)})
    tasks_response = client.get(
        "/runs/run123/tasks",
        params={"runs_root": str(runs_root)},
    )

    assert run_response.status_code == 200
    assert run_response.json()["run_id"] == "run123"
    assert run_response.json()["score"]["composite"] == 2.0
    assert tasks_response.status_code == 200
    assert tasks_response.json()["items"] == [
        {
            "task_id": "task-a",
            "success": True,
            "completed_phases": 2,
            "failed_phase": None,
        }
    ]


def test_api_returns_single_job_detail(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    run_dir = tmp_path / "runs" / "run123"
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "score_report.json", {"composite": 1.5})
    write_json(
        reports_root / "jobs" / "job123.json",
        {
            "job_id": "job123",
            "job_type": "run.score",
            "status": "queued",
            "job_input": {"run_id": "run123"},
            "result_ref": {
                "target_type": "run",
                "target_id": "run123",
                "path": "runs/run123/score_report.json",
            },
        },
    )

    client = TestClient(create_app())
    response = client.get(
        "/jobs/job123",
        params={
            "reports_root": str(reports_root),
            "repo_root": str(tmp_path),
        },
    )

    assert response.status_code == 200
    assert response.json()["job_id"] == "job123"
    assert response.json()["job_type"] == "run.score"
    assert response.json()["result_preview"] == {
        "target_type": "run",
        "target_id": "run123",
        "composite": 1.5,
    }


def test_api_promotes_candidate(tmp_path: Path) -> None:
    candidates_root = tmp_path / "candidates"
    runs_root = tmp_path / "runs"
    candidate_dir = candidates_root / "cand123"
    candidate_dir.mkdir(parents=True)
    write_json(
        candidate_dir / "candidate.json",
        {
            "candidate_id": "cand123",
            "profile": "base",
            "project": "demo",
            "notes": "candidate",
        },
    )
    write_json(candidate_dir / "effective_config.json", {"budget": {"max_turns": 12}})
    run_dir = runs_root / "run-1"
    (run_dir / "tasks").mkdir(parents=True)
    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run-1", "profile": "base", "project": "demo", "candidate_id": "cand123"},
    )
    write_json(run_dir / "score_report.json", {"composite": 1.0})

    client = TestClient(create_app())
    response = client.post(
        "/candidates/cand123/promote",
        json={
            "candidates_root": str(candidates_root),
            "runs_root": str(runs_root),
            "promoted_by": "api-user",
            "reason": "promotion test",
            "evidence_run_ids": ["run-1"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["candidate_id"] == "cand123"
    assert payload["data"]["champion_record"]["promoted_by"] == "api-user"
    promotion_target = json.loads(
        (candidate_dir / "promotion_target.json").read_text(encoding="utf-8")
    )
    assert promotion_target["evidence_refs"] == ["runs/run-1/score_report.json"]


def test_api_inspects_and_compiles_workflow(tmp_path: Path) -> None:
    workflow_path = tmp_path / "workflows" / "news_aggregation.json"
    output_path = tmp_path / "compiled" / "workflow.task_set.json"
    write_json(
        workflow_path,
        {
            "workflow_id": "news_aggregation",
            "evaluator_packs": ["web_scrape/core"],
            "steps": [
                {
                    "step_id": "fetch_homepages",
                    "primitive_id": "web_scrape",
                    "command": ["python", "scripts/fetch.py"],
                }
            ],
        },
    )

    client = TestClient(create_app())
    inspect_response = client.get(
        "/workflows/inspect",
        params={"workflow_path": str(workflow_path)},
    )
    compile_response = client.post(
        "/workflows/compile",
        json={
            "workflow_path": str(workflow_path),
            "output_path": str(output_path),
        },
    )

    assert inspect_response.status_code == 200
    assert inspect_response.json()["workflow_id"] == "news_aggregation"
    assert compile_response.status_code == 200
    payload = compile_response.json()
    assert payload["ok"] is True
    assert payload["data"]["output_path"] == str(output_path)


def test_api_runs_workflow_inline_job(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    reports_root = tmp_path / "reports"
    repo_root = tmp_path / "repo"
    workflow_path = tmp_path / "workflows" / "news_aggregation.json"
    repo_root.mkdir(parents=True, exist_ok=True)
    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {
            "description": "workflow",
            "defaults": {"evaluation": {"evaluators": ["basic"]}},
        },
    )
    write_json(
        config_root / "projects" / "demo.json",
        {
            "workflow": "base",
            "overrides": {"runtime": {"workspace": {"source_repo": str(repo_root)}}},
        },
    )
    write_json(
        config_root / "evaluator_packs" / "web_scrape_core.json",
        {
            "pack_id": "web_scrape/core",
            "supported_primitives": ["web_scrape"],
            "command": [
                "python",
                "-c",
                "import json; print(json.dumps({'capability_scores': {'web_scrape': {'success_rate': 1.0}}}))",
            ],
        },
    )
    write_json(
        workflow_path,
        {
            "workflow_id": "news_aggregation",
            "steps": [
                {
                    "step_id": "fetch_homepages",
                    "primitive_id": "web_scrape",
                    "command": ["python", "-c", "print('ok')"],
                }
            ],
        },
    )

    client = TestClient(create_app())
    response = client.post(
        "/workflows/run",
        json={
            "reports_root": str(reports_root),
            "workflow_path": str(workflow_path),
            "profile": "base",
            "project": "demo",
            "config_root": str(config_root),
            "runs_root": str(runs_root),
            "requested_by": "tester",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["run_id"]
    assert payload["job"]["job_type"] == "workflow.run"
    assert payload["job"]["result_ref"]["target_type"] == "run"
    assert payload["job"]["result_ref"]["target_id"] == payload["data"]["run_id"]
    assert payload["job"]["result_ref"]["path"] == (
        f"runs/{payload['data']['run_id']}/score_report.json"
    )
    assert payload["data"]["score"]["composite"] == 1.0


def test_api_runs_workflow_benchmark_inline_job(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    reports_root = tmp_path / "reports"
    repo_root = tmp_path / "repo"
    candidates_root = tmp_path / "candidates"
    workflow_path = tmp_path / "workflows" / "news_aggregation.json"
    spec_path = tmp_path / "benchmark.json"
    repo_root.mkdir(parents=True, exist_ok=True)
    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {
            "description": "workflow",
            "defaults": {"evaluation": {"evaluators": ["basic"]}},
        },
    )
    write_json(
        config_root / "projects" / "demo.json",
        {
            "workflow": "base",
            "overrides": {"runtime": {"workspace": {"source_repo": str(repo_root)}}},
        },
    )
    write_json(
        config_root / "evaluator_packs" / "web_scrape_core.json",
        {
            "pack_id": "web_scrape/core",
            "supported_primitives": ["web_scrape"],
            "command": [
                "python",
                "-c",
                "import json; print(json.dumps({'capability_scores': {'web_scrape': {'success_rate': 1.0}}}))",
            ],
        },
    )
    write_json(
        workflow_path,
        {
            "workflow_id": "news_aggregation",
            "steps": [
                {
                    "step_id": "fetch_homepages",
                    "primitive_id": "web_scrape",
                    "command": ["python", "-c", "print('ok')"],
                }
            ],
        },
    )
    write_json(
        spec_path,
        {
            "experiment": "workflow-ab",
            "baseline": "baseline",
            "variants": [{"name": "baseline"}],
        },
    )

    client = TestClient(create_app())
    response = client.post(
        "/workflows/benchmark",
        json={
            "reports_root": str(reports_root),
            "workflow_path": str(workflow_path),
            "profile": "base",
            "project": "demo",
            "config_root": str(config_root),
            "runs_root": str(runs_root),
            "candidates_root": str(candidates_root),
            "spec_path": str(spec_path),
            "requested_by": "tester",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["experiment"] == "workflow-ab"
    assert payload["data"]["artifact_path"] == "reports/benchmarks/workflow-ab.json"
    assert payload["job"]["job_type"] == "workflow.benchmark"
    assert payload["job"]["result_ref"]["target_type"] == "benchmark_experiment"
    assert payload["job"]["result_ref"]["target_id"] == "workflow-ab"
    assert payload["job"]["result_ref"]["path"] == "reports/benchmarks/workflow-ab.json"
    assert (tmp_path / payload["job"]["result_ref"]["path"]).exists()


def test_api_exposes_integration_generation_endpoints(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_analyze_integration_payload(**kwargs):
        captured["analyze"] = kwargs
        return {"spec_id": "spec-a", "integration_spec_path": str(tmp_path / "reports" / "integration" / "spec-a" / "integration_spec.json")}

    def fake_scaffold_integration_payload(**kwargs):
        captured["scaffold"] = kwargs
        return {"spec_id": "spec-a", "binding_path": str(tmp_path / "configs" / "claw_bindings" / "generated" / "a.json")}

    def fake_review_integration_payload(**kwargs):
        captured["review"] = kwargs
        return {"spec_id": "spec-a", "status": "activated", "activation_path": str(tmp_path / "reports" / "integration" / "spec-a" / "activation.json")}

    def fake_benchmark_integration_payload(**kwargs):
        captured["benchmark"] = kwargs
        return {"experiment": "integration-demo", "artifact_path": "reports/benchmarks/integration-demo.json"}

    monkeypatch.setattr(api_app_module, "analyze_integration_payload", fake_analyze_integration_payload)
    monkeypatch.setattr(api_app_module, "scaffold_integration_payload", fake_scaffold_integration_payload)
    monkeypatch.setattr(api_app_module, "review_integration_payload", fake_review_integration_payload)
    monkeypatch.setattr(api_app_module, "benchmark_integration_payload", fake_benchmark_integration_payload)

    client = TestClient(create_app())
    analyze = client.post(
        "/integrations/analyze",
        json={
            "config_root": str(tmp_path / "configs"),
            "reports_root": str(tmp_path / "reports"),
            "target_project_path": str(tmp_path / "project"),
            "primitive_id": "web_scrape",
            "workflow_paths": [str(tmp_path / "workflow.yaml")],
        },
    )
    scaffold = client.post(
        "/integrations/scaffold",
        json={
            "config_root": str(tmp_path / "configs"),
            "spec_path": str(tmp_path / "reports" / "integration" / "spec-a" / "integration_spec.json"),
        },
    )
    review = client.post(
        "/integrations/review",
        json={
            "config_root": str(tmp_path / "configs"),
            "spec_path": str(tmp_path / "reports" / "integration" / "spec-a" / "integration_spec.json"),
            "reviewer": "reviewer-a",
            "approve_all_checks": True,
            "activate_binding": True,
        },
    )
    benchmark = client.post(
        "/integrations/benchmark",
        json={
            "config_root": str(tmp_path / "configs"),
            "reports_root": str(tmp_path / "reports"),
            "runs_root": str(tmp_path / "runs"),
            "candidates_root": str(tmp_path / "candidates"),
            "spec_path": str(tmp_path / "reports" / "integration" / "spec-a" / "integration_spec.json"),
            "profile": "base",
            "project": "demo",
            "task_set_path": str(tmp_path / "task_set.json"),
        },
    )

    assert analyze.status_code == 200
    assert analyze.json()["data"]["spec_id"] == "spec-a"
    assert scaffold.status_code == 200
    assert scaffold.json()["data"]["spec_id"] == "spec-a"
    assert review.status_code == 200
    assert review.json()["data"]["status"] == "activated"
    assert benchmark.status_code == 200
    assert benchmark.json()["data"]["experiment"] == "integration-demo"


def test_api_runs_workflow_benchmark_suite_inline_job(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    reports_root = tmp_path / "reports"
    repo_root = tmp_path / "repo"
    candidates_root = tmp_path / "candidates"
    workflow_path = tmp_path / "workflows" / "news_aggregation.json"
    spec_path = tmp_path / "benchmark.json"
    suite_path = tmp_path / "suite.json"
    repo_root.mkdir(parents=True, exist_ok=True)
    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {
            "description": "workflow",
            "defaults": {"evaluation": {"evaluators": ["basic"]}},
        },
    )
    write_json(
        config_root / "projects" / "demo.json",
        {
            "workflow": "base",
            "overrides": {"runtime": {"workspace": {"source_repo": str(repo_root)}}},
        },
    )
    write_json(
        config_root / "evaluator_packs" / "web_scrape_core.json",
        {
            "pack_id": "web_scrape/core",
            "supported_primitives": ["web_scrape"],
            "command": [
                "python",
                "-c",
                "import json; print(json.dumps({'capability_scores': {'web_scrape': {'success_rate': 1.0}}}))",
            ],
        },
    )
    write_json(
        workflow_path,
        {
            "workflow_id": "news_aggregation",
            "steps": [
                {
                    "step_id": "fetch_homepages",
                    "primitive_id": "web_scrape",
                    "command": ["python", "-c", "print('ok')"],
                }
            ],
        },
    )
    write_json(
        spec_path,
        {
            "experiment": "workflow-ab",
            "baseline": "baseline",
            "variants": [{"name": "baseline"}],
        },
    )
    write_json(
        suite_path,
        {
            "suite": "workflow-suite",
            "benchmarks": [
                {"spec": str(spec_path)},
            ],
        },
    )

    client = TestClient(create_app())
    response = client.post(
        "/workflows/benchmark-suite",
        json={
            "reports_root": str(reports_root),
            "workflow_path": str(workflow_path),
            "profile": "base",
            "project": "demo",
            "suite_path": str(suite_path),
            "config_root": str(config_root),
            "runs_root": str(runs_root),
            "candidates_root": str(candidates_root),
            "requested_by": "tester",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["suite"] == "workflow-suite"
    assert payload["data"]["artifact_path"] == "reports/benchmark-suites/workflow-suite.json"
    assert payload["job"]["job_type"] == "workflow.benchmark_suite"
    assert payload["job"]["result_ref"]["target_type"] == "benchmark_suite"
    assert payload["job"]["result_ref"]["target_id"] == "workflow-suite"
    assert payload["job"]["result_ref"]["path"] == "reports/benchmark-suites/workflow-suite.json"
    assert (tmp_path / payload["job"]["result_ref"]["path"]).exists()


def test_api_returns_observation_summary(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"

    for run_id, created_at, composite, consistency in [
        ("run-old-best", "2026-04-05T10:00:00Z", 4.0, True),
        ("run-latest-gap", "2026-04-05T11:00:00Z", 2.0, False),
    ]:
        run_dir = runs_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            run_dir / "run_metadata.json",
            {
                "run_id": run_id,
                "profile": "base",
                "project": "demo",
                "created_at": created_at,
            },
        )
        write_json(
            run_dir / "effective_config.json",
            {"evaluation": {"evaluators": ["basic", "command"]}},
        )
        write_json(
            run_dir / "score_report.json",
            {
                "correctness": {"task_count": 1, "completed_steps": 1},
                "cost": {"trace_event_count": 1, "command_evaluators_run": 1},
                "maintainability": {
                    "profile_present": True,
                    "memory_consistency_ok": consistency,
                },
                "architecture": {
                    "snapshot_ready": True,
                    "vector_index_ready": True,
                    "db_integrity_ok": True,
                },
                "retrieval": {},
                "human_collaboration": {"manual_interventions": 0},
                "composite": composite,
            },
        )

    client = TestClient(create_app())
    response = client.get(
        "/observations/summary",
        params={
            "runs_root": str(runs_root),
            "profile": "base",
            "project": "demo",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["latest_run_id"] == "run-latest-gap"
    assert payload["best_run_id"] == "run-old-best"
    assert payload["recommended_focus"] == "memory"


def test_api_returns_run_trace_and_evaluators(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run123"
    task_dir = run_dir / "tasks" / "task-a"
    evaluators_dir = run_dir / "evaluators"
    task_dir.mkdir(parents=True)
    evaluators_dir.mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)

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
    write_json(
        evaluators_dir / "basic.json",
        {"correctness": {"task_count": 1}, "composite": 1.0},
    )

    client = TestClient(create_app())
    trace = client.get("/runs/run123/trace", params={"runs_root": str(runs_root)})
    evaluators = client.get("/runs/run123/evaluators", params={"runs_root": str(runs_root)})

    assert trace.status_code == 200
    assert trace.json()["items"][0]["phase"] == "tool_call"
    assert evaluators.status_code == 200
    assert evaluators.json()["items"][0]["name"] == "basic"
    assert evaluators.json()["items"][0]["report"]["composite"] == 1.0


def test_api_returns_current_candidates_and_champions(tmp_path: Path) -> None:
    candidates_root = tmp_path / "candidates"
    runs_root = tmp_path / "runs"
    candidate_dir = candidates_root / "cand123"
    candidate_dir.mkdir(parents=True)
    write_json(
        candidate_dir / "candidate.json",
        {
            "candidate_id": "cand123",
            "profile": "base",
            "project": "demo",
            "notes": "candidate",
        },
    )
    write_json(candidate_dir / "effective_config.json", {"budget": {"max_turns": 12}})
    write_json(candidates_root / "champions.json", {"base:demo": "cand123"})

    client = TestClient(create_app())
    current = client.get(
        "/candidates/current",
        params={"candidates_root": str(candidates_root), "runs_root": str(runs_root)},
    )
    champions = client.get("/champions", params={"candidates_root": str(candidates_root)})

    assert current.status_code == 200
    assert current.json()["current_recommended_candidate_by_experiment"] == {}
    assert champions.status_code == 200
    assert champions.json()["items"] == {"base:demo": "cand123"}


def test_api_current_candidates_projects_canonical_lineage(tmp_path: Path) -> None:
    candidates_root = tmp_path / "candidates"
    runs_root = tmp_path / "runs"
    candidate_dir = candidates_root / "cand123"
    candidate_dir.mkdir(parents=True)
    write_json(
        candidate_dir / "candidate.json",
        {
            "candidate_id": "cand123",
            "profile": "base",
            "project": "demo",
            "notes": "candidate",
            "proposal_id": "proposal-1",
            "source_proposal_ids": ["proposal-1"],
            "iteration_id": "iter-1",
            "source_iteration_ids": ["iter-1"],
            "source_run_ids": ["run-1"],
            "source_artifacts": ["reports/loops/loop-1/iteration.json"],
        },
    )
    write_json(candidate_dir / "effective_config.json", {"budget": {"max_turns": 12}})

    client = TestClient(create_app())
    current = client.get(
        "/candidates/current",
        params={"candidates_root": str(candidates_root), "runs_root": str(runs_root)},
    )

    assert current.status_code == 200
    candidate = current.json()["candidates"][0]
    assert candidate["lineage"] == {
        "parent_candidate_id": None,
        "proposal_id": "proposal-1",
        "source_proposal_ids": ["proposal-1"],
        "iteration_id": "iter-1",
        "source_iteration_ids": ["iter-1"],
        "source_run_ids": ["run-1"],
        "source_artifacts": ["reports/loops/loop-1/iteration.json"],
    }


def test_api_submits_optimize_propose_job(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    proposals_root = tmp_path / "proposals"
    reports_root = tmp_path / "reports"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "java_to_rust.json",
        {"description": "workflow", "defaults": {"retrieval": {"top_k": 8}}},
    )
    write_json(
        config_root / "projects" / "voidsector.json",
        {"workflow": "java_to_rust", "overrides": {"budget": {"max_turns": 16}}},
    )

    for run_id, error in [
        ("run-a", "Trait bound `Foo: Clone` is not satisfied"),
        ("run-b", "Trait bound `Bar: Debug` is not satisfied"),
    ]:
        run_dir = runs_root / run_id
        task_dir = run_dir / "tasks" / "task-a"
        task_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        write_json(
            run_dir / "run_metadata.json",
            {"run_id": run_id, "profile": "java_to_rust", "project": "voidsector"},
        )
        write_json(
            run_dir / "effective_config.json",
            {"budget": {"max_turns": 16}, "evaluation": {"evaluators": ["basic"]}},
        )
        (task_dir / "steps.jsonl").write_text(
            json.dumps(
                {
                    "step_id": "step-1",
                    "phase": "compile",
                    "status": "failed",
                    "latency_ms": 10,
                    "error": error,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    client = TestClient(create_app())
    response = client.post(
        "/optimize/propose",
        json={
            "reports_root": str(reports_root),
            "config_root": str(config_root),
            "runs_root": str(runs_root),
            "candidates_root": str(candidates_root),
            "proposals_root": str(proposals_root),
            "profile": "java_to_rust",
            "project": "voidsector",
            "requested_by": "tester",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["candidate_id"]
    assert payload["data"]["proposal_id"]
    assert payload["job"]["job_type"] == "optimize.propose"


def test_api_submits_optimize_loop_job(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_submit_optimize_loop_job(**kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "data": {
                "loop_id": "loop-123",
                "best_candidate_id": "cand-1",
            },
            "job": {
                "job_type": "optimize.loop",
                "result_ref": {
                    "target_type": "loop",
                    "target_id": "loop-123",
                    "path": "reports/loops/loop-123/loop.json",
                },
            },
        }

    monkeypatch.setattr(
        api_app_module,
        "submit_optimize_loop_job",
        fake_submit_optimize_loop_job,
        raising=False,
    )

    client = TestClient(create_app())
    response = client.post(
        "/optimize/loop",
        json={
            "reports_root": str(tmp_path / "reports"),
            "config_root": str(tmp_path / "configs"),
            "runs_root": str(tmp_path / "runs"),
            "candidates_root": str(tmp_path / "candidates"),
            "proposals_root": str(tmp_path / "proposals"),
            "task_set_path": str(tmp_path / "task_set.json"),
            "profile": "base",
            "project": "demo",
            "loop_id": "loop-123",
            "plugin_id": "web_scrape",
            "proposer_id": "heuristic",
            "max_iterations": 3,
            "focus": "retrieval",
            "requested_by": "tester",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["loop_id"] == "loop-123"
    assert payload["job"]["job_type"] == "optimize.loop"
    assert captured["profile_name"] == "base"
    assert captured["project_name"] == "demo"
    assert captured["loop_id"] == "loop-123"
    assert captured["proposals_root"] == tmp_path / "proposals"


def test_api_can_materialize_candidate_from_proposal_artifact(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    proposals_root = tmp_path / "proposals"
    reports_root = tmp_path / "reports"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "java_to_rust.json",
        {"description": "workflow", "defaults": {"retrieval": {"top_k": 8}}},
    )
    write_json(
        config_root / "projects" / "voidsector.json",
        {"workflow": "java_to_rust", "overrides": {"budget": {"max_turns": 16}}},
    )
    run_dir = runs_root / "run-a"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run-a", "profile": "java_to_rust", "project": "voidsector"},
    )
    write_json(
        run_dir / "effective_config.json",
        {"budget": {"max_turns": 16}, "evaluation": {"evaluators": ["basic"]}},
    )
    (task_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "step_id": "step-1",
                "phase": "compile",
                "status": "failed",
                "latency_ms": 10,
                "error": "Trait bound `Foo: Clone` is not satisfied",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    client = TestClient(create_app())
    propose = client.post(
        "/optimize/propose",
        json={
            "reports_root": str(reports_root),
            "config_root": str(config_root),
            "runs_root": str(runs_root),
            "candidates_root": str(candidates_root),
            "proposals_root": str(proposals_root),
            "profile": "java_to_rust",
            "project": "voidsector",
            "proposal_only": True,
        },
    )
    proposal_id = propose.json()["data"]["proposal_id"]
    materialize = client.post(
        f"/optimize/materialize-proposal/{proposal_id}",
        json={
            "config_root": str(config_root),
            "candidates_root": str(candidates_root),
            "proposals_root": str(proposals_root),
        },
    )

    assert propose.status_code == 200
    assert propose.json()["data"].get("candidate_id") is None
    assert materialize.status_code == 200
    candidate_id = materialize.json()["data"]["candidate_id"]
    assert candidate_id
    candidate_metadata = json.loads(
        (candidates_root / candidate_id / "candidate.json").read_text(encoding="utf-8")
    )
    assert candidate_metadata["source_proposal_ids"] == [proposal_id]
    assert candidate_metadata["source_run_ids"] == ["run-a"]


def test_api_lists_and_loads_proposals(tmp_path: Path) -> None:
    proposals_root = tmp_path / "proposals"
    proposal_dir = proposals_root / "proposal-1"
    proposal_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        proposal_dir / "proposal.json",
        {
            "proposal_id": "proposal-1",
            "profile": "java_to_rust",
            "project": "voidsector",
            "proposer_kind": "heuristic_failure_family",
            "strategy": "increase_budget_on_repeated_failures",
            "status": "proposed",
            "proposal": {"strategy": "increase_budget_on_repeated_failures"},
            "source_run_ids": ["run-a"],
        },
    )

    client = TestClient(create_app())
    listed = client.get(
        "/proposals",
        params={"proposals_root": str(proposals_root), "project": "voidsector"},
    )
    shown = client.get(
        "/proposals/proposal-1",
        params={"proposals_root": str(proposals_root)},
    )

    assert listed.status_code == 200
    assert shown.status_code == 200
    assert listed.json()["items"][0]["proposal_id"] == "proposal-1"
    assert shown.json()["proposal_id"] == "proposal-1"
    assert shown.json()["strategy"] == "increase_budget_on_repeated_failures"


def test_api_submits_integration_outer_loop_job(tmp_path: Path, monkeypatch) -> None:
    harness_spec_path = tmp_path / "harness_spec.json"
    task_set_path = tmp_path / "task_set.json"
    proposal_one = tmp_path / "proposal-1.json"
    proposal_two = tmp_path / "proposal-2.json"

    write_json(
        harness_spec_path,
        {
            "spec_id": "harness-demo",
            "target_project_path": str(tmp_path / "project"),
            "execution_model": {"kind": "json_stdout_cli"},
        },
    )
    write_json(task_set_path, {"tasks": []})
    write_json(
        proposal_one,
        {
            "candidate_id": "cand-1",
            "harness_spec_id": "harness-demo",
            "iteration_id": "iter-1",
            "title": "Patch 1",
            "summary": "First proposal",
            "change_kind": "wrapper_patch",
            "target_files": ["scripts/generated/harness_wrapper.py"],
            "patch": {},
            "rationale": ["baseline refinement"],
            "provenance": {"source": "test"},
        },
    )
    write_json(
        proposal_two,
        {
            "candidate_id": "cand-2",
            "harness_spec_id": "harness-demo",
            "iteration_id": "iter-1",
            "title": "Patch 2",
            "summary": "Second proposal",
            "change_kind": "wrapper_patch",
            "target_files": ["scripts/generated/harness_wrapper.py"],
            "patch": {},
            "rationale": ["stronger refinement"],
            "provenance": {"source": "test"},
        },
    )

    captured: dict[str, object] = {}

    def fake_harness_outer_loop_payload(**kwargs):
        captured.update(kwargs)
        return {"iteration_id": "iter-1", "selected_candidate_id": "cand-2"}

    monkeypatch.setattr(api_app_module, "harness_outer_loop_payload", fake_harness_outer_loop_payload)

    client = TestClient(create_app())
    response = client.post(
        "/integrations/outer-loop",
        json={
            "harness_spec_path": str(harness_spec_path),
            "task_set_path": str(task_set_path),
            "proposal_paths": [str(proposal_one), str(proposal_two)],
            "profile": "base",
            "project": "demo",
            "config_root": str(tmp_path / "configs"),
            "reports_root": str(tmp_path / "reports"),
            "runs_root": str(tmp_path / "runs"),
            "candidates_root": str(tmp_path / "candidates"),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["selected_candidate_id"] == "cand-2"
    assert captured["candidate_harness_patches"][0]["candidate_id"] == "cand-1"
    assert captured["candidate_harness_patches"][1]["candidate_id"] == "cand-2"


def test_api_contracts_validate_request_models() -> None:
    assert RunScoreRequest(
        reports_root="reports",
        runs_root="runs",
    ).runs_root == "runs"
    assert RunExportTraceRequest(
        reports_root="reports",
        runs_root="runs",
        output_path="out.json",
    ).format == "otel-json"
    assert DatasetExtractFailuresRequest(
        reports_root="reports",
        runs_root="runs",
        output_path="dataset.json",
    ).output_path == "dataset.json"
    assert RunExportTraceRequest(
        reports_root="reports",
        runs_root="runs",
        candidates_root="candidates",
    ).candidates_root == "candidates"
    assert PromoteCandidateRequest(candidates_root="candidates").candidates_root == "candidates"
    assert OptimizeLoopRequest(
        reports_root="reports",
        config_root="configs",
        runs_root="runs",
        candidates_root="candidates",
        task_set_path="task-set.json",
        profile="base",
        project="demo",
    ).proposals_root == "proposals"
    assert OptimizeLoopRequest(
        reports_root="reports",
        config_root="configs",
        runs_root="runs",
        candidates_root="candidates",
        task_set_path="task-set.json",
        profile="base",
        project="demo",
        proposer_id="heuristic,llm_harness",
    ).proposer_id == "heuristic,llm_harness"


def test_api_submits_observation_benchmark_job(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    reports_root = tmp_path / "reports"
    repo_root = tmp_path / "repo"
    task_set = tmp_path / "task_set.json"
    evaluator_script = tmp_path / "score_from_config.py"
    spec_path = tmp_path / "benchmark.json"

    repo_root.mkdir(parents=True, exist_ok=True)
    evaluator_script.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "from pathlib import Path",
                "payload = json.loads(Path('effective_config.json').read_text(encoding='utf-8'))",
                "top_k = int(payload.get('retrieval', {}).get('top_k', 8))",
                "print(json.dumps({'composite_adjustment': 2.0 if top_k > 8 else 0.5}))",
            ]
        ),
        encoding="utf-8",
    )
    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {
            "description": "workflow",
            "defaults": {
                "retrieval": {"top_k": 8},
                "evaluation": {
                    "evaluators": ["basic", "command"],
                    "command_evaluators": [
                        {"name": "benchmark-score", "command": ["python", str(evaluator_script)]}
                    ],
                },
            },
        },
    )
    write_json(
        config_root / "projects" / "demo.json",
        {
            "workflow": "base",
            "overrides": {"runtime": {"workspace": {"source_repo": str(repo_root)}}},
        },
    )
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "benchmark-task",
                    "workdir": str(repo_root),
                    "phases": [{"phase": "prepare", "command": ["python", "-c", "print('ok')"]}],
                }
            ]
        },
    )
    write_json(
        spec_path,
        {
            "experiment": "retrieval-memory-ab",
            "baseline": "baseline",
            "variants": [
                {"name": "baseline"},
                {"name": "larger_top_k", "config_patch": {"retrieval": {"top_k": 12}}},
            ],
        },
    )

    client = TestClient(create_app())
    response = client.post(
        "/observations/benchmark",
        json={
            "reports_root": str(reports_root),
            "config_root": str(config_root),
            "runs_root": str(runs_root),
            "candidates_root": str(candidates_root),
            "profile": "base",
            "project": "demo",
            "task_set_path": str(task_set),
            "spec_path": str(spec_path),
            "auto_compact_runs": False,
            "requested_by": "tester",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["best_variant"] == "larger_top_k"
    assert payload["data"]["artifact_path"] == "reports/benchmarks/retrieval-memory-ab.json"
    assert payload["job"]["job_type"] == "observation.benchmark"
    assert payload["job"]["result_ref"]["target_type"] == "benchmark_experiment"
    assert payload["job"]["result_ref"]["target_id"] == "retrieval-memory-ab"
    assert payload["job"]["result_ref"]["path"] == "reports/benchmarks/retrieval-memory-ab.json"
    assert (tmp_path / payload["job"]["result_ref"]["path"]).exists()


def test_api_inspects_and_runs_strategy_actions(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"
    runs_root = tmp_path / "runs"
    reports_root = tmp_path / "reports"
    repo_root = tmp_path / "repo"
    task_set = tmp_path / "task_set.json"
    card_path = tmp_path / "freshness_guard.json"
    repo_root.mkdir(parents=True, exist_ok=True)

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {
            "description": "workflow",
            "defaults": {"evaluation": {"evaluators": ["basic"]}},
        },
    )
    write_json(
        config_root / "projects" / "demo.json",
        {
            "workflow": "base",
            "overrides": {"runtime": {"workspace": {"source_repo": str(repo_root)}}},
        },
    )
    write_json(
        card_path,
        {
            "strategy_id": "indexing/freshness-guard-v1",
            "title": "Freshness Guard",
            "source": "reference://freshness-guard",
            "category": "indexing",
            "change_type": "config_only",
            "config_patch": {"retrieval": {"top_k": 12}},
        },
    )
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "benchmark-task",
                    "workdir": str(repo_root),
                    "phases": [{"phase": "prepare", "command": ["python", "-c", "print('ok')"]}],
                }
            ]
        },
    )

    client = TestClient(create_app())
    inspect_response = client.get(
        "/strategies/inspect",
        params={
            "strategy_card_path": str(card_path),
            "config_root": str(config_root),
            "profile": "base",
            "project": "demo",
        },
    )
    create_response = client.post(
        "/strategies/create-candidate",
        json={
            "strategy_card_path": str(card_path),
            "config_root": str(config_root),
            "candidates_root": str(candidates_root),
            "profile": "base",
            "project": "demo",
        },
    )
    benchmark_response = client.post(
        "/strategies/benchmark",
        json={
            "reports_root": str(reports_root),
            "strategy_card_paths": [str(card_path)],
            "config_root": str(config_root),
            "runs_root": str(runs_root),
            "candidates_root": str(candidates_root),
            "profile": "base",
            "project": "demo",
            "task_set_path": str(task_set),
            "experiment": "strategy-ab",
            "baseline": "baseline",
            "requested_by": "tester",
        },
    )

    assert inspect_response.status_code == 200
    assert inspect_response.json()["status"] == "executable"
    assert create_response.status_code == 200
    assert create_response.json()["ok"] is True
    assert create_response.json()["data"]["candidate_id"]
    assert benchmark_response.status_code == 200
    assert benchmark_response.json()["ok"] is True
    assert (
        benchmark_response.json()["data"]["artifact_path"]
        == "reports/benchmarks/strategy-ab.json"
    )
    assert benchmark_response.json()["job"]["job_type"] == "strategy.benchmark"
    assert benchmark_response.json()["job"]["result_ref"]["target_type"] == "benchmark_experiment"
    assert benchmark_response.json()["job"]["result_ref"]["target_id"] == "strategy-ab"
    assert benchmark_response.json()["job"]["result_ref"]["path"] == "reports/benchmarks/strategy-ab.json"
    assert (tmp_path / benchmark_response.json()["job"]["result_ref"]["path"]).exists()
