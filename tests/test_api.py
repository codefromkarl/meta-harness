from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from meta_harness.api.app import create_app
from meta_harness.api.contracts import (
    DatasetExtractFailuresRequest,
    PromoteCandidateRequest,
    RunExportTraceRequest,
    RunScoreRequest,
)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_api_healthcheck() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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

    client = TestClient(create_app())
    response = client.post(
        "/candidates/cand123/promote",
        json={"candidates_root": str(candidates_root)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["candidate_id"] == "cand123"


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
    assert payload["job"]["job_type"] == "workflow.benchmark"
    assert payload["job"]["result_ref"]["target_type"] == "benchmark_experiment"
    assert payload["job"]["result_ref"]["target_id"] == "workflow-ab"
    assert payload["job"]["result_ref"]["path"] == "reports/benchmarks/workflow-ab.json"
    assert (tmp_path / payload["job"]["result_ref"]["path"]).exists()


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


def test_api_submits_optimize_propose_job(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
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
            "profile": "java_to_rust",
            "project": "voidsector",
            "requested_by": "tester",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["candidate_id"]
    assert payload["job"]["job_type"] == "optimize.propose"


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
    assert PromoteCandidateRequest(candidates_root="candidates").candidates_root == "candidates"


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
    assert benchmark_response.json()["job"]["job_type"] == "strategy.benchmark"
    assert benchmark_response.json()["job"]["result_ref"]["target_type"] == "benchmark_experiment"
    assert benchmark_response.json()["job"]["result_ref"]["target_id"] == "strategy-ab"
    assert benchmark_response.json()["job"]["result_ref"]["path"] == "reports/benchmarks/strategy-ab.json"
    assert (tmp_path / benchmark_response.json()["job"]["result_ref"]["path"]).exists()
