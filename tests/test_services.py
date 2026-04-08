from __future__ import annotations

import json
from pathlib import Path

import meta_harness.services.async_jobs as async_jobs_module
import meta_harness.services.benchmark_service as benchmark_service_module
import meta_harness.services.integration_catalog_service as integration_catalog_service_module
import meta_harness.services.strategy_service as strategy_service_module
import pytest
from meta_harness.services.candidate_service import (
    create_candidate_record,
    promote_candidate_record,
)
from meta_harness.services.catalog_service import (
    build_candidate_index_payload,
    build_run_index_payload,
)
from meta_harness.services.benchmark_service import (
    observe_benchmark_payload,
    write_benchmark_report,
    write_benchmark_suite_report,
)
from meta_harness.services.dataset_service import extract_failure_dataset_to_path
from meta_harness.services.export_service import export_run_trace_to_path
from meta_harness.services.integration_catalog_service import export_payload_to_integration
from meta_harness.services.job_service import (
    cancel_job_record,
    complete_job_record,
    create_job_record,
    fail_job_record,
    list_job_views,
    list_job_records,
    load_job_record,
    load_job_view,
    start_job_record,
)
from meta_harness.services.async_jobs import (
    submit_dataset_extract_job,
    submit_observation_benchmark_job,
    submit_optimize_loop_job,
    submit_run_export_trace_job,
    submit_run_score_job,
    submit_strategy_benchmark_job,
    submit_workflow_benchmark_job,
    submit_workflow_benchmark_suite_job,
    submit_workflow_run_job,
)
from meta_harness.services.service_execution import execute_inline_job
from meta_harness.services.service_response import error_response, success_response
from meta_harness.services.observation_service import (
    observe_once_payload,
    observe_summary_payload,
)
from meta_harness.services.optimize_service import propose_candidate_payload
from meta_harness.services.optimize_loop_service import build_search_loop_request
from meta_harness.services.optimize_service import run_optimize_loop_payload
from meta_harness.services.optimize_service import (
    list_proposals_payload,
    load_proposal_payload,
)
from meta_harness.services.profile_service import list_profile_names
from meta_harness.services.run_query_service import (
    list_run_summaries,
    load_run_summary,
    search_failure_records,
)
from meta_harness.services.run_service import initialize_run_record
from meta_harness.services.scoring_service import score_run_record
from meta_harness.services.strategy_service import (
    build_web_scrape_audit_benchmark_spec_payload,
    build_web_scrape_audit_report_payload,
    create_candidate_from_strategy_card_payload,
    inspect_strategy_card_payload,
    recommend_web_scrape_strategy_cards_payload,
    run_strategy_benchmark_payload,
)
from meta_harness.services.workflow_service import (
    benchmark_suite_workflow_payload,
    benchmark_workflow_payload,
    compile_workflow_payload,
    inspect_workflow_payload,
    run_workflow_payload,
)
from meta_harness.services.integration_service import harness_outer_loop_payload
from meta_harness.schemas import WorkflowHarnessRef
from meta_harness.proposals import create_proposal_record


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_profile_service_lists_sorted_profile_names(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    write_json(config_root / "profiles" / "zeta.json", {"description": "zeta"})
    write_json(config_root / "profiles" / "alpha.json", {"description": "alpha"})

    assert list_profile_names(config_root) == ["alpha", "zeta"]


def test_run_service_initializes_run_from_profile_project(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 10}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "Base workflow", "defaults": {"tools": ["rg"]}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {"budget": {"max_turns": 14}}},
    )

    result = initialize_run_record(
        profile_name="base",
        project_name="demo",
        config_root=config_root,
        candidates_root=tmp_path / "candidates",
        runs_root=runs_root,
    )

    assert result["profile"] == "base"
    assert result["project"] == "demo"
    run_dir = runs_root / str(result["run_id"])
    assert run_dir.exists()
    effective_config = json.loads((run_dir / "effective_config.json").read_text(encoding="utf-8"))
    assert effective_config["budget"] == {"max_turns": 14}


def test_candidate_service_creates_and_promotes_candidate(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {"retrieval": {"top_k": 8}}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {"budget": {"max_turns": 16}}},
    )
    patch_path = tmp_path / "patch.json"
    write_json(patch_path, {"budget": {"max_turns": 20}})

    created = create_candidate_record(
        profile_name="base",
        project_name="demo",
        config_root=config_root,
        candidates_root=candidates_root,
        config_patch_path=patch_path,
        notes="service candidate",
    )
    candidate_id = str(created["candidate_id"])
    candidate_dir = candidates_root / candidate_id
    assert candidate_dir.exists()

    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run-1"
    (run_dir / "tasks").mkdir(parents=True)
    write_json(
        run_dir / "run_metadata.json",
        {
            "run_id": "run-1",
            "profile": "base",
            "project": "demo",
            "candidate_id": candidate_id,
            "status": "completed",
        },
    )
    write_json(run_dir / "score_report.json", {"composite": 1.5})

    promoted = promote_candidate_record(
        candidates_root,
        candidate_id,
        promoted_by="tester",
        promotion_reason="benchmark winner",
        evidence_run_ids=["run-1"],
        runs_root=runs_root,
    )
    assert promoted["candidate_id"] == candidate_id
    assert promoted["champions"]["base:demo"] == candidate_id
    assert promoted["champion_record"]["promoted_by"] == "tester"
    assert promoted["champion_record"]["promotion_reason"] == "benchmark winner"
    assert promoted["champion_record"]["evidence_run_ids"] == ["run-1"]
    promotion_target = json.loads(
        (candidate_dir / "promotion_target.json").read_text(encoding="utf-8")
    )
    assert promotion_target["candidate"]["candidate_id"] == candidate_id
    assert promotion_target["evidence_refs"] == ["runs/run-1/score_report.json"]
    assert promotion_target["evidence_runs"][0]["score_report_path"] == "runs/run-1/score_report.json"
    assert promotion_target["promotion_summary"]["evidence_run_count"] == 1
    assert promotion_target["promotion_summary"]["all_evidence_runs_scored"] is True


def test_strategy_service_recommends_web_scrape_method_family() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    payload = recommend_web_scrape_strategy_cards_payload(
        config_root=repo_root / "configs",
        page_profile={
            "complexity": "high",
            "requires_rendering": True,
            "anti_bot_level": "high",
        },
        workload_profile={
            "usage_mode": "recurring",
            "batch_size": 100,
        },
        limit=2,
    )

    assert payload["selected_strategy_id"] == "web_scrape/headless-fingerprint-proxy"
    assert len(payload["recommendations"]) == 2


def test_strategy_service_builds_web_scrape_audit_report_without_benchmark() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    payload = build_web_scrape_audit_report_payload(
        config_root=repo_root / "configs",
        page_profile={
            "complexity": "low",
            "requires_rendering": False,
        },
        workload_profile={
            "usage_mode": "ad_hoc",
        },
        limit=2,
    )

    assert payload["primary_recommendation"]["strategy_id"] == "web_scrape/html-to-markdown-llm"
    assert payload["benchmark_summary"] is None
    assert payload["alignment"]["has_benchmark_evidence"] is False
    assert payload["alignment"]["aligned"] is None
    assert payload["audit_summary"]


def test_strategy_service_builds_web_scrape_audit_report_with_benchmark_alignment(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    benchmark_report = tmp_path / "reports" / "benchmarks" / "web_scrape-audit-test.json"
    benchmark_report.parent.mkdir(parents=True, exist_ok=True)
    benchmark_report.write_text(
        json.dumps(
            {
                "experiment": "web-scrape-audit",
                "best_variant": "selector_only",
                "best_by_quality": "selector_only",
                "best_by_stability": "selector_only",
                "report_summary": {
                    "best_variant": "selector_only",
                },
            }
        ),
        encoding="utf-8",
    )

    payload = build_web_scrape_audit_report_payload(
        config_root=repo_root / "configs",
        page_profile={
            "complexity": "high",
            "requires_rendering": True,
            "anti_bot_level": "high",
        },
        workload_profile={
            "usage_mode": "ad_hoc",
        },
        benchmark_report_path=benchmark_report,
        limit=2,
    )

    assert payload["primary_recommendation"]["strategy_id"] == "web_scrape/vlm-visual-extract"
    assert payload["benchmark_summary"]["best_variant"] == "selector_only"
    assert payload["alignment"]["has_benchmark_evidence"] is True
    assert payload["alignment"]["aligned"] is False


def test_strategy_service_builds_web_scrape_audit_benchmark_spec_payload(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    output_path = tmp_path / "benchmark-spec.json"

    payload = build_web_scrape_audit_benchmark_spec_payload(
        config_root=repo_root / "configs",
        page_profile={
            "complexity": "low",
            "requires_rendering": False,
        },
        workload_profile={
            "usage_mode": "recurring",
            "batch_size": 50,
        },
        output_path=output_path,
        limit=2,
        repeats=2,
    )

    assert payload["output_path"] == str(output_path)
    assert output_path.exists()
    assert payload["audit_report"]["selected_strategy_id"] == "web_scrape/selector-only"
    assert payload["benchmark_spec"]["baseline"] == "current_strategy"
    assert payload["benchmark_spec"]["repeats"] == 2
    assert [variant["name"] for variant in payload["benchmark_spec"]["variants"]] == [
        "current_strategy",
        "selector_only",
        "html_to_markdown_llm",
    ]


def test_dataset_service_extracts_failure_dataset_to_output_path(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
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

    result = extract_failure_dataset_to_path(
        runs_root=runs_root,
        output_path=output_path,
    )

    assert result["output_path"] == str(output_path)
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["case_count"] == 1
    assert payload["cases"][0]["failure_signature"] == "trait bound foo clone is not satisfied"


def test_scoring_service_scores_run_and_returns_report(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
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

    report = score_run_record(runs_root=runs_root, run_id="run123")

    assert report["correctness"]["task_count"] == 1
    assert report["composite"] == 1.0


def test_export_service_writes_selected_trace_format(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run123"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)
    output_path = tmp_path / "trace-export.json"

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

    payload = export_run_trace_to_path(
        runs_root=runs_root,
        run_id="run123",
        output_path=output_path,
        export_format="phoenix-json",
    )

    assert payload["output_path"] == str(output_path)
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["project_name"] == "meta-harness/demo"


def test_integration_catalog_service_retries_retryable_status_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_root = tmp_path / "configs"
    write_json(
        config_root / "integrations" / "otlp.json",
        {
            "name": "otlp",
            "kind": "otlp_http",
            "endpoint": "http://127.0.0.1:4318/v1/traces",
            "retry_limit": 2,
            "retry_backoff_sec": 0.0,
        },
    )

    attempts: list[dict[str, object]] = []

    def fake_post_json(**kwargs):  # type: ignore[no-untyped-def]
        attempts.append(kwargs)
        if len(attempts) == 1:
            return {"status_code": 503, "body": {"accepted": False}}
        return {"status_code": 200, "body": {"accepted": True}}

    monkeypatch.setattr(integration_catalog_service_module, "_post_json", fake_post_json)

    payload = export_payload_to_integration(
        config_root=config_root,
        name="otlp",
        payload={"run_id": "run123"},
    )

    assert payload["status_code"] == 200
    assert payload["attempt_count"] == 2
    assert payload["response"] == {"accepted": True}
    assert len(attempts) == 2


def test_integration_catalog_service_classifies_non_retryable_http_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_root = tmp_path / "configs"
    write_json(
        config_root / "integrations" / "phoenix.json",
        {
            "name": "phoenix",
            "kind": "phoenix",
            "endpoint": "http://127.0.0.1:6006/phoenix/traces",
        },
    )

    def fake_post_json(**kwargs):  # type: ignore[no-untyped-def]
        return {"status_code": 422, "body": {"error": "invalid payload"}}

    monkeypatch.setattr(integration_catalog_service_module, "_post_json", fake_post_json)

    payload = export_payload_to_integration(
        config_root=config_root,
        name="phoenix",
        payload={"run_id": "run123"},
    )

    assert payload["status_code"] == 422
    assert payload["ok"] is False
    assert payload["failure_kind"] == "remote_rejected"
    assert payload["retryable"] is False
    assert payload["retry_exhausted"] is False


def test_catalog_service_builds_run_and_candidate_index_payloads(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"

    candidate_dir = candidates_root / "cand-a"
    candidate_dir.mkdir(parents=True)
    write_json(
        candidate_dir / "candidate.json",
        {
            "candidate_id": "cand-a",
            "profile": "base",
            "project": "demo",
            "notes": "benchmark variant",
        },
    )
    write_json(candidate_dir / "effective_config.json", {"budget": {"max_turns": 12}})
    write_json(
        candidate_dir / "proposal.json",
        {
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
        },
    )

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
            "candidate_id": "cand-a",
            "created_at": "2026-04-06T10:00:00Z",
        },
    )
    write_json(run_dir / "effective_config.json", {"evaluation": {"evaluators": ["basic"]}})
    write_json(
        run_dir / "score_report.json",
        {
            "correctness": {"task_count": 1, "completed_steps": 2},
            "cost": {"trace_event_count": 2},
            "maintainability": {},
            "architecture": {},
            "retrieval": {},
            "human_collaboration": {},
            "composite": 2.5,
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

    run_payload = build_run_index_payload(
        runs_root=runs_root,
        candidates_root=candidates_root,
    )
    candidate_payload = build_candidate_index_payload(
        candidates_root=candidates_root,
        runs_root=runs_root,
    )

    assert run_payload["runs"][0]["experiment"] == "benchmark_combo_validation"
    assert candidate_payload["candidates"][0]["run_ids"] == ["run123"]


def test_run_query_service_lists_and_loads_runs(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"

    run_dir = runs_root / "run-a"
    (run_dir / "tasks").mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)
    write_json(
        run_dir / "run_metadata.json",
        {
            "run_id": "run-a",
            "profile": "base",
            "project": "demo",
            "created_at": "2026-04-05T10:00:00Z",
        },
    )
    write_json(run_dir / "effective_config.json", {"tools": ["rg"]})
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

    summaries = list_run_summaries(runs_root)
    loaded = load_run_summary(runs_root, "run-a")

    assert summaries == [{"run_id": "run-a", "profile": "base", "project": "demo", "composite": "2.0"}]
    assert loaded["run_id"] == "run-a"
    assert loaded["score"]["composite"] == 2.0


def test_run_query_service_searches_failure_records(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run-a"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)
    write_json(
        run_dir / "run_metadata.json",
        {
            "run_id": "run-a",
            "profile": "base",
            "project": "demo",
            "created_at": "2026-04-05T10:00:00Z",
        },
    )
    write_json(run_dir / "effective_config.json", {"evaluation": {"evaluators": ["basic"]}})
    (task_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "step_id": "step-1",
                "phase": "compile",
                "status": "failed",
                "error": "Trait bound `Foo: Clone` is not satisfied",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    records = search_failure_records(runs_root, "trait bound")

    assert records == [
        {
            "run_id": "run-a",
            "task_id": "task-a",
            "phase": "compile",
            "signature": "trait bound foo clone is not satisfied",
        }
    ]


def test_observation_service_summarizes_runs(tmp_path: Path) -> None:
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

    payload = observe_summary_payload(
        runs_root=runs_root,
        profile_name="base",
        project_name="demo",
    )

    assert payload["latest_run_id"] == "run-latest-gap"
    assert payload["best_run_id"] == "run-old-best"
    assert payload["recommended_focus"] == "memory"
    assert payload["needs_optimization"] is True


def test_observation_service_runs_once_and_returns_payload(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    repo_root = tmp_path / "repo"
    task_set = tmp_path / "observe_task_set.json"

    repo_root.mkdir(parents=True, exist_ok=True)
    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {"evaluation": {"evaluators": ["basic"]}}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {
            "workflow": "base",
            "overrides": {
                "runtime": {
                    "workspace": {
                        "source_repo": str(repo_root),
                    }
                }
            },
        },
    )
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "observe-task",
                    "workdir": str(repo_root),
                    "phases": [{"phase": "prepare", "command": ["python", "-c", "print('ready')"]}],
                }
            ]
        },
    )

    payload = observe_once_payload(
        profile_name="base",
        project_name="demo",
        task_set_path=task_set,
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        auto_propose=False,
    )

    assert payload["run_id"]
    assert payload["score"]["composite"] == 1.0
    assert payload["needs_optimization"] is False
    assert payload["recommended_focus"] == "none"


def test_optimize_service_proposes_candidate_from_failures(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"

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

    payload = propose_candidate_payload(
        profile_name="java_to_rust",
        project_name="voidsector",
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        proposals_root=tmp_path / "proposals",
    )

    candidate_dir = candidates_root / str(payload["candidate_id"])
    proposal = json.loads((candidate_dir / "proposal.json").read_text(encoding="utf-8"))
    proposal_record = json.loads(
        (
            tmp_path
            / "proposals"
            / str(payload["proposal_id"])
            / "proposal.json"
        ).read_text(encoding="utf-8")
    )
    assert proposal["strategy"] == "increase_budget_on_repeated_failures"
    assert proposal_record["candidate_id"] == payload["candidate_id"]


def test_optimize_loop_service_delegates_to_search_loop(tmp_path: Path, monkeypatch) -> None:
    from meta_harness.services import optimize_loop_service as optimize_loop_module

    config_root = tmp_path / "configs"
    proposals_root = tmp_path / "proposals"
    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "demo_public.json",
        {"description": "workflow", "defaults": {"evaluation": {"evaluators": ["basic"]}}},
    )
    write_json(
        config_root / "projects" / "demo_openclaw.json",
        {"workflow": "demo_public", "overrides": {"optimization": {"proposal_command": ["python", "-c", "print('{}')"]}}},
    )

    captured: dict[str, object] = {}

    def fake_run_search_loop(request, **kwargs):
        captured["request"] = request
        captured.update(kwargs)
        return {
            "loop_id": "loop-0001",
            "best_candidate_id": "cand-123",
            "best_run_id": "run-123",
            "completed_iterations": 2,
            "stop_reason": "max_iterations_reached",
        }

    monkeypatch.setattr(optimize_loop_module, "run_search_loop", fake_run_search_loop)

    payload = run_optimize_loop_payload(
        profile_name="demo_public",
        project_name="demo_openclaw",
        task_set_path=tmp_path / "task-set.json",
        config_root=config_root,
        runs_root=tmp_path / "runs",
        candidates_root=tmp_path / "candidates",
        reports_root=tmp_path / "reports",
        proposals_root=proposals_root,
        plugin_id="web_scrape",
        proposer_id="command",
        max_iterations=4,
        focus="retrieval",
    )

    assert payload["loop_id"] == "loop-0001"
    assert payload["best_candidate_id"] == "cand-123"
    request = captured["request"]
    assert request.profile_name == "demo_public"
    assert request.project_name == "demo_openclaw"
    assert request.task_plugin_id == "web_scrape"
    assert request.proposer_id == "command"
    assert request.max_iterations == 4
    assert request.focus == "retrieval"
    assert captured["proposals_root"] == proposals_root
    assert captured["task_plugin"].plugin_id == "web_scrape"
    assert captured["proposer"].proposer_id == "command"


def test_async_job_submits_optimize_loop_and_persists_loop_result_ref(
    tmp_path: Path, monkeypatch
) -> None:
    reports_root = tmp_path / "reports"
    proposals_root = tmp_path / "proposals"

    monkeypatch.setattr(
        async_jobs_module,
        "optimize_loop_payload",
        lambda **kwargs: {
            "loop_id": "loop-123",
            "best_candidate_id": "cand-1",
            "best_run_id": "run-1",
            "loop_dir": str(tmp_path / "reports" / "loops" / "loop-123"),
            "loop_request": kwargs,
        },
    )

    payload = submit_optimize_loop_job(
        reports_root=reports_root,
        config_root=tmp_path / "configs",
        runs_root=tmp_path / "runs",
        candidates_root=tmp_path / "candidates",
        proposals_root=proposals_root,
        profile_name="base",
        project_name="demo",
        task_set_path=tmp_path / "task_set.json",
        requested_by="tester",
        loop_id="loop-123",
        plugin_id="web_scrape",
        proposer_id="heuristic",
        max_iterations=3,
        focus="retrieval",
    )

    assert payload["ok"] is True
    assert payload["data"]["loop_id"] == "loop-123"
    assert payload["job"]["job_type"] == "optimize.loop"
    assert payload["job"]["result_ref"]["target_type"] == "loop"
    assert payload["job"]["result_ref"]["target_id"] == "loop-123"
    assert payload["job"]["result_ref"]["path"] == "reports/loops/loop-123/loop.json"


def test_build_search_loop_request_is_shared_request_builder(tmp_path: Path) -> None:
    request = build_search_loop_request(
        profile_name="base",
        project_name="demo",
        task_set_path=tmp_path / "task-set.json",
        config_root=tmp_path / "configs",
        runs_root=tmp_path / "runs",
        candidates_root=tmp_path / "candidates",
        reports_root=tmp_path / "reports",
        proposals_root=tmp_path / "proposals",
        loop_id="loop-1",
        plugin_id="web_scrape",
        proposer_id="heuristic,llm_harness",
        max_iterations=4,
        focus="retrieval",
    )

    assert request.profile_name == "base"
    assert request.project_name == "demo"
    assert request.task_plugin_id == "web_scrape"
    assert request.proposer_id == "heuristic,llm_harness"
    assert request.loop_id == "loop-1"
    assert request.focus == "retrieval"


def test_optimize_service_lists_and_loads_proposals_with_filters(tmp_path: Path) -> None:
    proposals_root = tmp_path / "proposals"
    proposal_a = create_proposal_record(
        proposals_root=proposals_root,
        profile_name="java_to_rust",
        project_name="voidsector",
        proposer_kind="heuristic_failure_family",
        proposal={"strategy": "increase_budget_on_repeated_failures"},
        notes="increase budget",
        source_run_ids=["run-a"],
    )
    proposal_b = create_proposal_record(
        proposals_root=proposals_root,
        profile_name="demo_public",
        project_name="demo_openclaw",
        proposer_kind="command",
        proposal={"strategy": "external_command"},
        notes="external command",
        source_run_ids=["run-b"],
    )

    proposal_b_path = proposals_root / proposal_b / "proposal.json"
    proposal_b_payload = json.loads(proposal_b_path.read_text(encoding="utf-8"))
    proposal_b_payload["status"] = "materialized"
    proposal_b_payload["candidate_id"] = "cand-123"
    proposal_b_path.write_text(json.dumps(proposal_b_payload, indent=2), encoding="utf-8")

    listed = list_proposals_payload(
        proposals_root=proposals_root,
        project_name="demo_openclaw",
        status="materialized",
    )
    detail = load_proposal_payload(proposals_root=proposals_root, proposal_id=proposal_a)

    assert [item["proposal_id"] for item in listed] == [proposal_b]
    assert listed[0]["candidate_id"] == "cand-123"
    assert detail["proposal_id"] == proposal_a
    assert detail["strategy"] == "increase_budget_on_repeated_failures"
    assert detail["proposal_dir"].endswith(proposal_a)


def test_benchmark_service_runs_variants_and_selects_best(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
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

    payload = observe_benchmark_payload(
        profile_name="base",
        project_name="demo",
        task_set_path=task_set,
        spec_path=spec_path,
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        reports_root=tmp_path / "reports",
        auto_compact_runs=False,
    )

    assert payload["best_variant"] == "larger_top_k"
    assert payload["artifact_path"] == "reports/benchmarks/retrieval-memory-ab.json"
    assert (tmp_path / payload["artifact_path"]).exists()


def test_benchmark_service_persists_observation_reports_and_returns_artifact_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    reports_root = tmp_path / "reports"

    monkeypatch.setattr(
        benchmark_service_module,
        "run_benchmark",
        lambda **kwargs: {"experiment": "observation-ab", "best_variant": "baseline"},
    )

    payload = observe_benchmark_payload(
        profile_name="base",
        project_name="demo",
        task_set_path=Path("task_set.json"),
        spec_path=Path("benchmark.json"),
        config_root=tmp_path / "configs",
        runs_root=tmp_path / "runs",
        candidates_root=tmp_path / "candidates",
        reports_root=reports_root,
        auto_compact_runs=False,
    )

    assert payload["artifact_path"] == "reports/benchmarks/observation-ab.json"
    artifact_path = tmp_path / payload["artifact_path"]
    assert json.loads(artifact_path.read_text(encoding="utf-8"))["best_variant"] == "baseline"


def test_strategy_service_inspects_and_creates_candidate(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"
    card_path = tmp_path / "freshness_guard.json"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )
    write_json(
        card_path,
        {
            "strategy_id": "indexing/freshness-guard-v1",
            "title": "Freshness Guard",
            "source": "reference://freshness-guard",
            "category": "indexing",
            "change_type": "config_only",
            "config_patch": {"indexing": {"freshness_guard": True}},
        },
    )

    report = inspect_strategy_card_payload(
        strategy_card_path=card_path,
        profile_name="base",
        project_name="demo",
        config_root=config_root,
    )
    created = create_candidate_from_strategy_card_payload(
        strategy_card_path=card_path,
        profile_name="base",
        project_name="demo",
        config_root=config_root,
        candidates_root=candidates_root,
    )

    assert report["status"] == "executable"
    assert created["candidate_id"]


def test_job_service_persists_and_updates_job_lifecycle(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"

    created = create_job_record(
        reports_root=reports_root,
        job_type="run.score",
        job_input={"run_id": "run123"},
        requested_by="tester",
    )
    job_id = str(created["job_id"])

    started = start_job_record(reports_root=reports_root, job_id=job_id)
    completed = complete_job_record(
        reports_root=reports_root,
        job_id=job_id,
        result_ref={
            "target_type": "run",
            "target_id": "run123",
            "path": "runs/run123/score_report.json",
        },
    )

    assert created["status"] == "queued"
    assert started["status"] == "running"
    assert completed["status"] == "succeeded"
    assert completed["result_ref"]["target_id"] == "run123"
    persisted = load_job_record(reports_root=reports_root, job_id=job_id)
    assert persisted["status"] == "succeeded"


def test_job_service_lists_and_filters_jobs(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"

    job_a = create_job_record(reports_root=reports_root, job_type="run.score")
    job_b = create_job_record(reports_root=reports_root, job_type="benchmark.run")
    fail_job_record(
        reports_root=reports_root,
        job_id=str(job_b["job_id"]),
        error_code="benchmark_failed",
        message="benchmark exploded",
    )
    cancel_job_record(reports_root=reports_root, job_id=str(job_a["job_id"]))

    failed = list_job_records(reports_root=reports_root, status="failed")
    benchmark = list_job_records(reports_root=reports_root, job_type="benchmark.run")

    assert len(failed) == 1
    assert failed[0]["job_id"] == job_b["job_id"]
    assert len(benchmark) == 1
    assert benchmark[0]["job_type"] == "benchmark.run"


def test_job_service_resolves_result_preview_for_run_and_workflow_benchmark(
    tmp_path: Path,
) -> None:
    reports_root = tmp_path / "reports"
    runs_root = tmp_path / "runs"

    run_dir = runs_root / "run123"
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        run_dir / "score_report.json",
        {
            "composite": 2.5,
            "capability_scores": {"web_scrape": {"success_rate": 0.9}},
        },
    )

    benchmark_report = reports_root / "workflow_benchmarks" / "workflow-ab.json"
    write_json(
        benchmark_report,
        {
            "experiment": "workflow-ab",
            "best_variant": "baseline",
        },
    )

    run_job = create_job_record(reports_root=reports_root, job_type="workflow.run")
    benchmark_job = create_job_record(
        reports_root=reports_root,
        job_type="workflow.benchmark",
    )

    complete_job_record(
        reports_root=reports_root,
        job_id=str(run_job["job_id"]),
        result_ref={
            "target_type": "run",
            "target_id": "run123",
            "path": "runs/run123/score_report.json",
        },
    )
    complete_job_record(
        reports_root=reports_root,
        job_id=str(benchmark_job["job_id"]),
        result_ref={
            "target_type": "benchmark_experiment",
            "target_id": "workflow-ab",
            "path": str(benchmark_report),
        },
    )

    run_view = load_job_view(
        reports_root=reports_root,
        job_id=str(run_job["job_id"]),
    )
    benchmark_view = load_job_view(
        reports_root=reports_root,
        job_id=str(benchmark_job["job_id"]),
    )
    listed = list_job_views(reports_root=reports_root)

    assert run_view["result_preview"] == {
        "target_type": "run",
        "target_id": "run123",
        "composite": 2.5,
    }
    assert benchmark_view["result_preview"] == {
        "target_type": "benchmark_experiment",
        "target_id": "workflow-ab",
        "best_variant": "baseline",
    }
    assert listed[0]["result_preview"] is not None


def test_job_service_resolves_result_preview_for_loop(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    loop_report = reports_root / "loops" / "loop-123" / "loop.json"
    write_json(
        loop_report,
        {
            "loop_id": "loop-123",
            "best_candidate_id": "cand-1",
            "best_run_id": "run-1",
            "iteration_count": 3,
            "stop_reason": "target score reached",
        },
    )

    loop_job = create_job_record(reports_root=reports_root, job_type="optimize.loop")
    complete_job_record(
        reports_root=reports_root,
        job_id=str(loop_job["job_id"]),
        result_ref={
            "target_type": "loop",
            "target_id": "loop-123",
            "path": "reports/loops/loop-123/loop.json",
        },
    )

    loop_view = load_job_view(
        reports_root=reports_root,
        job_id=str(loop_job["job_id"]),
        repo_root=tmp_path,
    )

    assert loop_view["result_preview"] == {
        "target_type": "loop",
        "target_id": "loop-123",
        "best_candidate_id": "cand-1",
        "best_run_id": "run-1",
        "iteration_count": 3,
        "stop_reason": "target score reached",
    }


def test_service_response_builders_return_consistent_envelopes() -> None:
    success = success_response({"run_id": "run123"})
    failure = error_response("job_failed", "boom", details={"job_type": "run.score"})

    assert success["ok"] is True
    assert success["data"]["run_id"] == "run123"
    assert success["error"] is None

    assert failure["ok"] is False
    assert failure["data"] is None
    assert failure["error"]["code"] == "job_failed"
    assert failure["error"]["details"]["job_type"] == "run.score"


def test_execute_inline_job_runs_lifecycle_and_returns_success_envelope(
    tmp_path: Path,
) -> None:
    reports_root = tmp_path / "reports"

    payload = execute_inline_job(
        reports_root=reports_root,
        job_type="run.score",
        job_input={"run_id": "run123"},
        requested_by="tester",
        runner=lambda: {"run_id": "run123", "composite": 1.5},
        result_ref_builder=lambda data: {
            "target_type": "run",
            "target_id": data["run_id"],
            "path": "runs/run123/score_report.json",
        },
    )

    assert payload["ok"] is True
    assert payload["data"]["run_id"] == "run123"
    assert payload["job"]["status"] == "succeeded"
    assert payload["job"]["result_ref"]["target_id"] == "run123"


def test_execute_inline_job_captures_failure_in_job_and_response(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"

    payload = execute_inline_job(
        reports_root=reports_root,
        job_type="benchmark.run",
        job_input={"experiment": "demo"},
        runner=lambda: (_ for _ in ()).throw(RuntimeError("kaboom")),
    )

    assert payload["ok"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "job_failed"
    assert payload["job"]["status"] == "failed"
    assert payload["job"]["error"]["message"] == "kaboom"


def test_async_job_facade_submits_run_score_job(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    runs_root = tmp_path / "runs"
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

    payload = submit_run_score_job(
        reports_root=reports_root,
        runs_root=runs_root,
        run_id="run123",
        requested_by="tester",
    )

    assert payload["ok"] is True
    assert payload["data"]["composite"] == 1.0
    assert payload["job"]["job_type"] == "run.score"
    assert payload["job"]["result_ref"]["path"] == "runs/run123/score_report.json"


def test_async_job_facade_submits_run_export_trace_job(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run123"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)
    output_path = tmp_path / "exports" / "trace.json"
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

    payload = submit_run_export_trace_job(
        reports_root=reports_root,
        runs_root=runs_root,
        run_id="run123",
        output_path=output_path,
        export_format="otel-json",
    )

    assert payload["ok"] is True
    assert payload["data"]["output_path"] == str(output_path)
    assert payload["job"]["job_type"] == "run.export_trace"
    assert payload["job"]["result_ref"]["target_type"] == "trace_export"


def test_async_job_facade_submits_dataset_extract_job(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    runs_root = tmp_path / "runs"
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

    payload = submit_dataset_extract_job(
        reports_root=reports_root,
        runs_root=runs_root,
        output_path=output_path,
        requested_by="tester",
    )

    assert payload["ok"] is True
    assert payload["data"]["dataset_id"] == "failure-signatures"
    assert payload["job"]["job_type"] == "dataset.extract_failures"


def test_workflow_service_inspects_and_compiles_workflow(tmp_path: Path) -> None:
    workflow_path = tmp_path / "workflows" / "news_aggregation.json"
    output_path = tmp_path / "compiled" / "workflow.task_set.json"
    config_root = tmp_path / "configs"
    write_json(
        config_root / "evaluator_packs" / "web_scrape_core.json",
        {
            "pack_id": "web_scrape/core",
            "supported_primitives": ["web_scrape"],
            "command": ["python", "scripts/eval_web_scrape.py"],
        },
    )
    write_json(
        workflow_path,
        {
            "workflow_id": "news_aggregation",
            "evaluator_packs": ["web_scrape/core"],
            "page_profile": {
                "complexity": "high",
                "dynamicity": "heavily_dynamic",
                "anti_bot_level": "high",
                "requires_rendering": True,
                "requires_interaction": True,
                "schema_stability": "volatile",
                "media_dependency": "medium",
            },
            "workload_profile": {
                "usage_mode": "recurring",
                "batch_size": 32,
                "latency_sla_ms": 2500,
                "budget_mode": "high_success",
                "freshness_requirement": "high",
                "allowed_failure_rate": 0.05,
            },
            "steps": [
                {
                    "step_id": "fetch_homepages",
                    "primitive_id": "web_scrape",
                    "page_profile": {
                        "complexity": "medium",
                        "requires_rendering": True,
                    },
                    "workload_profile": {
                        "usage_mode": "ad_hoc",
                        "latency_sla_ms": 1800,
                    },
                    "command": ["python", "scripts/fetch.py"],
                }
            ],
        },
    )

    inspect_payload = inspect_workflow_payload(
        workflow_path=workflow_path,
        config_root=config_root,
    )
    compile_payload = compile_workflow_payload(
        workflow_path=workflow_path,
        output_path=output_path,
        config_root=config_root,
    )

    assert inspect_payload["workflow_id"] == "news_aggregation"
    assert inspect_payload["evaluator_packs"] == ["web_scrape/core"]
    assert compile_payload["output_path"] == str(output_path)
    assert compile_payload["task_set"]["tasks"][0]["task_id"] == "fetch_homepages"
    assert compile_payload["task_set"]["metadata"]["page_profile"] == {
        "complexity": "high",
        "dynamicity": "heavily_dynamic",
        "anti_bot_level": "high",
        "requires_rendering": True,
        "requires_interaction": True,
        "schema_stability": "volatile",
        "media_dependency": "medium",
    }
    assert compile_payload["task_set"]["metadata"]["workload_profile"] == {
        "usage_mode": "recurring",
        "batch_size": 32,
        "latency_sla_ms": 2500,
        "budget_mode": "high_success",
        "freshness_requirement": "high",
        "allowed_failure_rate": 0.05,
    }
    assert compile_payload["task_set"]["tasks"][0]["expectations"]["page_profile"] == {
        "complexity": "medium",
        "dynamicity": "heavily_dynamic",
        "anti_bot_level": "high",
        "requires_rendering": True,
        "requires_interaction": True,
        "schema_stability": "volatile",
        "media_dependency": "medium",
    }
    assert compile_payload["task_set"]["tasks"][0]["expectations"]["workload_profile"] == {
        "usage_mode": "ad_hoc",
        "batch_size": 32,
        "latency_sla_ms": 1800,
        "budget_mode": "high_success",
        "freshness_requirement": "high",
        "allowed_failure_rate": 0.05,
    }


def test_workflow_service_inspect_rejects_evaluator_pack_artifact_drift(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    workflow_path = tmp_path / "workflows" / "news_aggregation.json"
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

    with pytest.raises(ValueError, match="artifact requirements"):
        inspect_workflow_payload(workflow_path=workflow_path, config_root=config_root)


def test_workflow_service_compile_rejects_evaluator_pack_artifact_drift(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    workflow_path = tmp_path / "workflows" / "news_aggregation.json"
    output_path = tmp_path / "compiled" / "workflow.task_set.json"
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

    with pytest.raises(ValueError, match="artifact requirements"):
        compile_workflow_payload(
            workflow_path=workflow_path,
            output_path=output_path,
            config_root=config_root,
        )


def test_workflow_service_compile_supports_harness_refs(tmp_path: Path) -> None:
    workflow_path = tmp_path / "workflows" / "harness_workflow.json"
    output_path = tmp_path / "compiled" / "harness_workflow.task_set.json"
    write_json(
        workflow_path,
        {
            "workflow_id": "harness_workflow",
            "steps": [
                {
                    "step_id": "run_candidate_harness",
                    "command": ["python", "scripts/run.py"],
                    "harness_ref": {
                        "harness_id": "harness/demo",
                        "wrapper_path": "scripts/generated/demo_harness_wrapper.py",
                    },
                    "candidate_harness_ref": {
                        "harness_id": "harness/demo",
                        "candidate_harness_id": "cand-harness-1",
                        "proposal_id": "proposal-1",
                        "iteration_id": "iter-1",
                        "wrapper_path": "scripts/generated/demo_harness_wrapper.py",
                        "source_artifacts": ["runs/run-1/artifacts"],
                        "provenance": {"source": "agent"},
                    },
                }
            ],
        },
    )

    inspect_payload = inspect_workflow_payload(
        workflow_path=workflow_path,
        config_root=tmp_path / "configs",
    )
    compile_payload = compile_workflow_payload(
        workflow_path=workflow_path,
        output_path=output_path,
        config_root=tmp_path / "configs",
    )

    assert inspect_payload["primitive_ids"] == []
    task = compile_payload["task_set"]["tasks"][0]
    assert task["scenario"] == "cand-harness-1"
    assert task["harness_ref"]["harness_id"] == "harness/demo"
    assert task["candidate_harness_ref"]["candidate_harness_id"] == "cand-harness-1"
    assert task["execution_unit"]["kind"] == "harness"
    assert task["expectations"]["execution_kind"] == "harness"


def test_workflow_service_run_and_benchmark_bind_evaluator_packs(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    reports_root = tmp_path / "reports"
    repo_root = tmp_path / "repo"
    workflow_path = tmp_path / "workflows" / "news_aggregation.json"
    benchmark_spec = tmp_path / "benchmark.json"
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
            "command": ["python", "scripts/eval_web_scrape.py"],
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
                    "command": ["python", "scripts/fetch.py"],
                }
            ],
        },
    )
    write_json(
        benchmark_spec,
        {
            "experiment": "workflow-ab",
            "baseline": "baseline",
            "variants": [{"name": "baseline"}],
        },
    )

    captured_run: dict[str, object] = {}
    captured_benchmark: dict[str, object] = {}

    def fake_execute_managed_run(**kwargs):
        captured_run.update(kwargs)
        return {
            "run_id": "run123",
            "task_summary": {"succeeded": 1, "total": 1},
            "score": {"composite": 1.0},
        }

    def fake_run_benchmark(**kwargs):
        captured_benchmark.update(kwargs)
        return {"experiment": "workflow-ab", "best_variant": "baseline", "variants": []}

    run_payload = run_workflow_payload(
        workflow_path=workflow_path,
        profile_name="base",
        project_name="demo",
        config_root=config_root,
        runs_root=runs_root,
        execute_managed_run_fn=fake_execute_managed_run,
    )
    benchmark_payload = benchmark_workflow_payload(
        workflow_path=workflow_path,
        profile_name="base",
        project_name="demo",
        spec_path=benchmark_spec,
        reports_root=reports_root,
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=tmp_path / "candidates",
        run_benchmark_fn=fake_run_benchmark,
        compact_runs_fn=lambda *args, **kwargs: {"compacted_runs": []},
    )

    assert run_payload["run_id"] == "run123"
    assert captured_run["effective_config"]["evaluation"]["command_evaluators"] == [
        {
            "name": "web_scrape/core",
            "command": ["python", "scripts/eval_web_scrape.py"],
        }
    ]
    assert benchmark_payload["experiment"] == "workflow-ab"
    assert benchmark_payload["artifact_path"] == "reports/benchmarks/workflow-ab.json"
    assert (tmp_path / benchmark_payload["artifact_path"]).exists()
    assert captured_benchmark["effective_config_override"]["evaluation"]["command_evaluators"] == [
        {
            "name": "web_scrape/core",
            "command": ["python", "scripts/eval_web_scrape.py"],
        }
    ]


def test_workflow_benchmark_payload_can_auto_evaluate_gate(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    reports_root = tmp_path / "reports"
    workflow_path = tmp_path / "workflows" / "news_aggregation.json"
    benchmark_spec = tmp_path / "benchmark.json"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {"evaluation": {"evaluators": ["basic"]}}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )
    write_json(
        config_root / "gate_policies" / "benchmark-pass.json",
        {
            "policy_id": "benchmark-pass",
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
    write_json(
        workflow_path,
        {
            "workflow_id": "news_aggregation",
            "steps": [
                {
                    "step_id": "fetch_homepages",
                    "primitive_id": "web_scrape",
                    "command": ["python", "scripts/fetch.py"],
                }
            ],
        },
    )
    write_json(
        benchmark_spec,
        {
            "experiment": "workflow-gated",
            "baseline": "baseline",
            "variants": [{"name": "baseline"}],
        },
    )

    def fake_run_benchmark(**kwargs):
        return {
            "experiment": "workflow-gated",
            "best_variant": "baseline",
            "variants": [{"name": "baseline", "ranking_score": 1.0}],
        }

    payload = benchmark_workflow_payload(
        workflow_path=workflow_path,
        profile_name="base",
        project_name="demo",
        spec_path=benchmark_spec,
        reports_root=reports_root,
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=tmp_path / "candidates",
        run_benchmark_fn=fake_run_benchmark,
        compact_runs_fn=lambda *args, **kwargs: {"compacted_runs": []},
        gate_policy_id="benchmark-pass",
    )

    assert payload["artifact_path"] == "reports/benchmarks/workflow-gated.json"
    assert payload["gate_result"]["status"] == "passed"
    assert payload["gate_result"]["target_ref"] == "reports/benchmarks/workflow-gated.json"
    assert (tmp_path / payload["gate_result"]["artifact_path"]).exists()


def test_workflow_service_run_inherits_primitive_evaluation_contract_into_task_set(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
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
        config_root / "primitives" / "web_scrape.json",
        {
            "primitive_id": "web_scrape",
            "kind": "browser_interaction",
            "evaluation_contract": {
                "artifact_requirements": ["page.html", "extracted.json"],
                "required_fields": ["title", "price"],
                "latency_budget_ms": 1200,
                "quality_thresholds": {
                    "field_completeness": 0.8,
                    "grounded_field_rate": 0.75,
                },
            },
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
                    "command": ["python", "scripts/fetch.py"],
                }
            ],
        },
    )

    captured: dict[str, object] = {}

    def fake_execute_managed_run(**kwargs):
        captured.update(kwargs)
        task_set = json.loads(Path(str(kwargs["task_set_path"])).read_text(encoding="utf-8"))
        captured["compiled_task_set"] = task_set
        return {
            "run_id": "run123",
            "task_summary": {"succeeded": 1, "total": 1},
            "score": {"composite": 1.0},
        }

    payload = run_workflow_payload(
        workflow_path=workflow_path,
        profile_name="base",
        project_name="demo",
        config_root=config_root,
        runs_root=runs_root,
        execute_managed_run_fn=fake_execute_managed_run,
    )

    assert payload["run_id"] == "run123"
    expectations = captured["compiled_task_set"]["tasks"][0]["expectations"]
    assert expectations["artifact_requirements"] == ["page.html", "extracted.json"]
    assert expectations["required_fields"] == ["title", "price"]
    assert expectations["latency_budget_ms"] == 1200
    assert expectations["quality_thresholds"] == {
        "field_completeness": 0.8,
        "grounded_field_rate": 0.75,
    }


def test_workflow_service_run_rejects_evaluator_pack_artifact_drift(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
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

    with pytest.raises(ValueError, match="artifact requirements"):
        run_workflow_payload(
            workflow_path=workflow_path,
            profile_name="base",
            project_name="demo",
            config_root=config_root,
            runs_root=runs_root,
        )


def test_workflow_service_benchmark_suite_binds_evaluator_packs(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    reports_root = tmp_path / "reports"
    repo_root = tmp_path / "repo"
    workflow_path = tmp_path / "workflows" / "news_aggregation.json"
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
            "command": ["python", "scripts/eval_web_scrape.py"],
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
                    "command": ["python", "scripts/fetch.py"],
                }
            ],
        },
    )
    write_json(
        suite_path,
        {
            "suite": "workflow-suite",
            "benchmarks": [
                {"spec": "benchmarks/a.json"},
                {"spec": "benchmarks/b.json", "focus": "workflow"},
            ],
        },
    )

    captured: dict[str, object] = {}

    def fake_run_benchmark_suite(**kwargs):
        captured.update(kwargs)
        return {"suite": "workflow-suite", "benchmark_count": 2, "benchmarks": []}

    payload = benchmark_suite_workflow_payload(
        workflow_path=workflow_path,
        profile_name="base",
        project_name="demo",
        suite_path=suite_path,
        reports_root=reports_root,
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=tmp_path / "candidates",
        run_benchmark_suite_fn=fake_run_benchmark_suite,
        compact_runs_fn=lambda *args, **kwargs: {"compacted_runs": []},
    )

    assert payload["suite"] == "workflow-suite"
    assert payload["artifact_path"] == "reports/benchmark-suites/workflow-suite.json"
    assert (tmp_path / payload["artifact_path"]).exists()
    assert captured["effective_config_override"]["evaluation"]["command_evaluators"] == [
        {
            "name": "web_scrape/core",
            "command": ["python", "scripts/eval_web_scrape.py"],
        }
    ]


def test_async_job_facade_submits_workflow_jobs(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
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

    run_payload = submit_workflow_run_job(
        reports_root=reports_root,
        workflow_path=workflow_path,
        config_root=config_root,
        runs_root=runs_root,
        profile_name="base",
        project_name="demo",
        requested_by="tester",
    )
    benchmark_payload = submit_workflow_benchmark_job(
        reports_root=reports_root,
        workflow_path=workflow_path,
        spec_path=spec_path,
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        profile_name="base",
        project_name="demo",
        requested_by="tester",
    )
    suite_payload = submit_workflow_benchmark_suite_job(
        reports_root=reports_root,
        workflow_path=workflow_path,
        suite_path=suite_path,
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        profile_name="base",
        project_name="demo",
        requested_by="tester",
    )

    assert run_payload["ok"] is True
    assert run_payload["job"]["job_type"] == "workflow.run"
    assert run_payload["job"]["result_ref"]["target_type"] == "run"
    assert benchmark_payload["ok"] is True
    assert benchmark_payload["job"]["job_type"] == "workflow.benchmark"
    assert benchmark_payload["job"]["result_ref"]["target_type"] == "benchmark_experiment"
    assert suite_payload["ok"] is True
    assert suite_payload["job"]["job_type"] == "workflow.benchmark_suite"
    assert suite_payload["job"]["result_ref"]["target_type"] == "benchmark_suite"


def test_benchmark_service_persists_benchmark_reports(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"

    benchmark_path = write_benchmark_report(
        reports_root=reports_root,
        payload={"experiment": "workflow-ab", "best_variant": "baseline"},
    )
    suite_path = write_benchmark_suite_report(
        reports_root=reports_root,
        payload={
            "suite": "workflow-suite",
            "best_by_experiment": {"workflow-ab": "baseline"},
        },
    )

    assert benchmark_path.name == "workflow-ab.json"
    assert suite_path.name == "workflow-suite.json"
    assert json.loads(benchmark_path.read_text(encoding="utf-8"))["best_variant"] == "baseline"
    assert json.loads(suite_path.read_text(encoding="utf-8"))["suite"] == "workflow-suite"


def test_async_benchmark_jobs_persist_result_refs_to_artifacts(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"

    benchmark_payload = submit_workflow_benchmark_job(
        reports_root=reports_root,
        workflow_path=Path("workflow.json"),
        spec_path=Path("benchmark.json"),
        config_root=tmp_path / "configs",
        runs_root=tmp_path / "runs",
        candidates_root=tmp_path / "candidates",
        profile_name="base",
        project_name="demo",
        requested_by="tester",
        runner_override=lambda: {"experiment": "workflow-ab", "best_variant": "baseline"},
    )
    suite_payload = submit_workflow_benchmark_suite_job(
        reports_root=reports_root,
        workflow_path=Path("workflow.json"),
        suite_path=Path("suite.json"),
        config_root=tmp_path / "configs",
        runs_root=tmp_path / "runs",
        candidates_root=tmp_path / "candidates",
        profile_name="base",
        project_name="demo",
        requested_by="tester",
        runner_override=lambda: {
            "suite": "workflow-suite",
            "best_by_experiment": {"workflow-ab": "baseline"},
        },
    )

    benchmark_ref = benchmark_payload["job"]["result_ref"]
    suite_ref = suite_payload["job"]["result_ref"]

    assert benchmark_payload["data"]["artifact_path"] == benchmark_ref["path"]
    assert suite_payload["data"]["artifact_path"] == suite_ref["path"]
    assert benchmark_ref["path"] == "reports/benchmarks/workflow-ab.json"
    assert suite_ref["path"] == "reports/benchmark-suites/workflow-suite.json"
    assert (tmp_path / benchmark_ref["path"]).exists()
    assert (tmp_path / suite_ref["path"]).exists()


def test_async_observation_and_strategy_benchmark_jobs_persist_result_refs(
    tmp_path: Path,
) -> None:
    reports_root = tmp_path / "reports"

    observation_payload = submit_observation_benchmark_job(
        reports_root=reports_root,
        config_root=tmp_path / "configs",
        runs_root=tmp_path / "runs",
        candidates_root=tmp_path / "candidates",
        profile_name="base",
        project_name="demo",
        task_set_path=Path("task_set.json"),
        spec_path=Path("benchmark.json"),
        requested_by="tester",
        runner_override=lambda: {"experiment": "observation-ab", "best_variant": "baseline"},
    )
    strategy_payload = submit_strategy_benchmark_job(
        reports_root=reports_root,
        strategy_card_paths=[Path("strategy.json")],
        config_root=tmp_path / "configs",
        runs_root=tmp_path / "runs",
        candidates_root=tmp_path / "candidates",
        profile_name="base",
        project_name="demo",
        task_set_path=Path("task_set.json"),
        experiment="strategy-ab",
        baseline_name="baseline",
        requested_by="tester",
        runner_override=lambda: {"experiment": "strategy-ab", "best_variant": "variant-a"},
    )

    observation_ref = observation_payload["job"]["result_ref"]
    strategy_ref = strategy_payload["job"]["result_ref"]

    assert observation_payload["data"]["artifact_path"] == observation_ref["path"]
    assert strategy_payload["data"]["artifact_path"] == strategy_ref["path"]
    assert observation_ref["path"] == "reports/benchmarks/observation-ab.json"
    assert strategy_ref["path"] == "reports/benchmarks/strategy-ab.json"
    assert (tmp_path / observation_ref["path"]).exists()
    assert (tmp_path / strategy_ref["path"]).exists()


def test_strategy_service_persists_benchmark_report_and_returns_artifact_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    reports_root = tmp_path / "reports"

    monkeypatch.setattr(
        strategy_service_module,
        "run_strategy_benchmark",
        lambda **kwargs: {"experiment": "strategy-ab", "best_variant": "variant-a"},
    )

    payload = run_strategy_benchmark_payload(
        strategy_card_paths=[Path("strategy.json")],
        profile_name="base",
        project_name="demo",
        task_set_path=Path("task_set.json"),
        experiment="strategy-ab",
        baseline_name="baseline",
        reports_root=reports_root,
        config_root=tmp_path / "configs",
        runs_root=tmp_path / "runs",
        candidates_root=tmp_path / "candidates",
    )

    assert payload["artifact_path"] == "reports/benchmarks/strategy-ab.json"
    artifact_path = tmp_path / payload["artifact_path"]
    assert json.loads(artifact_path.read_text(encoding="utf-8"))["best_variant"] == "variant-a"


def test_harness_outer_loop_persists_iteration_history_and_next_round_bundle(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    reports_root = tmp_path / "reports"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    harness_spec_path = reports_root / "integration" / "harness-demo" / "harness_spec.json"
    task_set_path = tmp_path / "task_set.json"
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True, exist_ok=True)
    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {"evaluation": {"evaluators": ["basic"]}}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )
    write_json(
        harness_spec_path,
        {
            "spec_id": "harness-demo",
            "target_project_path": str(project_root),
            "execution_model": {
                "kind": "json_stdout_cli",
                "entry_command": ["python", "scripts/run.py"],
            },
            "capability_modules": ["command_proxy"],
            "manual_checks": ["入口命令是否正确"],
        },
    )
    write_json(
        task_set_path,
        {
            "tasks": [
                {
                    "task_id": "task-a",
                    "workdir": "${workspace_dir}",
                    "phases": [
                        {
                            "phase": "run",
                            "command": ["python", "-c", "print('ok')"],
                        }
                    ],
                }
            ]
        },
    )

    def fake_run_benchmark(**kwargs):
        spec_payload = json.loads(Path(str(kwargs["spec_path"])).read_text(encoding="utf-8"))
        variant_scores = {
            "reference": 0.5,
            "cand-1": 0.8,
            "cand-2": 1.2,
        }
        variants = []
        for variant in spec_payload["variants"]:
            name = str(variant["name"])
            run_id = f"run-{name}"
            run_dir = runs_root / run_id
            task_dir = run_dir / "tasks" / "task-a"
            task_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
            write_json(
                run_dir / "score_report.json",
                {
                    "composite": variant_scores[name],
                    "stability": {
                        "repeat_count": 1,
                        "composite_range": 0.0,
                        "composite_stddev": 0.0,
                    },
                },
            )
            (task_dir / "steps.jsonl").write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "task_id": "task-a",
                        "step_id": "step-1",
                        "phase": "run",
                        "status": "completed",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            write_json(
                task_dir / "task_result.json",
                {
                    "task_id": "task-a",
                    "success": True,
                    "failed_phase": None,
                    "failed_assertion": None,
                },
            )
            variants.append(
                {
                    "name": name,
                    "variant_type": variant.get("variant_type", "harness"),
                    "candidate_id": f"candidate-{name}",
                    "candidate_harness": variant["candidate_harness"],
                    "run_id": run_id,
                    "run_ids": [run_id],
                    "score": {"composite": variant_scores[name]},
                    "stability": {
                        "repeat_count": 1,
                        "composite_range": 0.0,
                        "composite_stddev": 0.0,
                    },
                    "ranking_score": variant_scores[name],
                    "best_run_id": run_id,
                }
            )
        best_variant = max(variants, key=lambda item: item["ranking_score"])
        return {
            "experiment": spec_payload["experiment"],
            "baseline": spec_payload["baseline"],
            "best_variant": best_variant["name"],
            "best_by_quality": best_variant["name"],
            "best_by_stability": best_variant["name"],
            "report_summary": {"best_variant": best_variant["name"]},
            "variants": variants,
        }

    payload = harness_outer_loop_payload(
        config_root=config_root,
        reports_root=reports_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        harness_spec_path=harness_spec_path,
        profile_name="base",
        project_name="demo",
        task_set_path=task_set_path,
        candidate_harness_patches=[
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
        ],
        run_benchmark_fn=fake_run_benchmark,
    )

    history_path = Path(payload["iteration_history_path"])
    iteration_bundle_path = Path(payload["iteration_bundle_path"])
    bundle_index_path = Path(payload["bundle_index_path"])
    next_round_bundle_path = Path(payload["next_round_input_path"])
    loop_summary_path = Path(payload["loop_summary_path"])
    loop_iteration_path = Path(payload["loop_iteration_path"])
    iteration_result = payload["iteration_result"]
    iteration_bundle = json.loads(iteration_bundle_path.read_text(encoding="utf-8"))
    bundle_index = json.loads(bundle_index_path.read_text(encoding="utf-8"))
    next_round_bundle = json.loads(next_round_bundle_path.read_text(encoding="utf-8"))
    loop_summary = json.loads(loop_summary_path.read_text(encoding="utf-8"))

    assert payload["best_candidate_id"] == "candidate-cand-2"
    assert payload["selected_candidate_id"] == "candidate-cand-2"
    assert iteration_result["selected_candidate_id"] == "candidate-cand-2"
    assert iteration_result["status"] == "completed"
    assert history_path.exists()
    assert iteration_bundle_path.exists()
    assert bundle_index_path.exists()
    assert loop_summary_path.exists()
    assert loop_iteration_path.exists()
    assert len(history_path.read_text(encoding="utf-8").splitlines()) == 1
    assert payload["loop_id"] == "harness-outer-loop-harness-demo-iteration-0001"
    assert loop_summary["best_candidate_id"] == "candidate-cand-2"
    assert loop_summary["iteration_count"] == 1
    assert iteration_bundle["kind"] == "harness_iteration_bundle"
    assert iteration_bundle["selected_candidate_harness"]["candidate_id"] == "candidate-cand-2"
    assert iteration_bundle["best_candidate_harness"]["candidate_id"] == "candidate-cand-2"
    status_by_candidate = {
        item["candidate_id"]: item["status"] for item in iteration_bundle["candidate_harnesses"]
    }
    assert status_by_candidate["candidate-reference"] == "benchmarked"
    assert status_by_candidate["candidate-cand-2"] == "selected"
    selected_entry = next(
        item
        for item in iteration_bundle["candidate_harnesses"]
        if item["candidate_id"] == "candidate-cand-2"
    )
    assert selected_entry["candidate_definition"]["title"] == "Patch 2"
    assert len(selected_entry["trace_refs"]) == 1
    assert selected_entry["trace_refs"][0].endswith("runs/run-cand-2/tasks/task-a/steps.jsonl")
    assert selected_entry["failure_samples"]
    assert iteration_bundle["summary"]["next_actions"]
    assert bundle_index["kind"] == "harness_iteration_bundle_index"
    assert bundle_index["latest_iteration_id"] == payload["iteration_id"]
    assert bundle_index["latest_bundle_path"] == str(iteration_bundle_path)
    assert next_round_bundle["kind"] == "next_round_proposer_input"
    assert next_round_bundle["bundle_path"] == str(iteration_bundle_path)
    assert next_round_bundle["bundle_kind"] == "harness_iteration_bundle"
    assert next_round_bundle["candidate_harnesses"]


def test_harness_outer_loop_shared_loop_prefers_best_proposal_over_reference(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    reports_root = tmp_path / "reports"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    harness_spec_path = reports_root / "integration" / "harness-demo" / "harness_spec.json"
    task_set_path = tmp_path / "task_set.json"
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True, exist_ok=True)
    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {"evaluation": {"evaluators": ["basic"]}}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )
    write_json(
        harness_spec_path,
        {
            "spec_id": "harness-demo",
            "target_project_path": str(project_root),
            "execution_model": {"kind": "json_stdout_cli"},
        },
    )
    write_json(task_set_path, {"tasks": []})

    def fake_run_benchmark(**kwargs):
        spec_payload = json.loads(Path(str(kwargs["spec_path"])).read_text(encoding="utf-8"))
        variant_scores = {
            "reference": 1.4,
            "cand-1": 0.8,
            "cand-2": 1.2,
        }
        variants = []
        for variant in spec_payload["variants"]:
            name = str(variant["name"])
            run_id = f"run-{name}"
            run_dir = runs_root / run_id
            task_dir = run_dir / "tasks" / "task-a"
            task_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
            write_json(
                run_dir / "score_report.json",
                {"composite": variant_scores[name]},
            )
            write_json(
                task_dir / "task_result.json",
                {"task_id": "task-a", "success": True, "failed_phase": None},
            )
            (task_dir / "steps.jsonl").write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "task_id": "task-a",
                        "step_id": "step-1",
                        "phase": "run",
                        "status": "completed",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            variants.append(
                {
                    "name": name,
                    "variant_type": variant.get("variant_type", "harness"),
                    "candidate_id": f"candidate-{name}",
                    "candidate_harness": variant["candidate_harness"],
                    "run_id": run_id,
                    "run_ids": [run_id],
                    "score": {"composite": variant_scores[name]},
                    "ranking_score": variant_scores[name],
                    "best_run_id": run_id,
                }
            )
        return {
            "experiment": spec_payload["experiment"],
            "baseline": spec_payload["baseline"],
            "best_variant": "reference",
            "best_by_quality": "reference",
            "best_by_stability": "reference",
            "report_summary": {"best_variant": "reference"},
            "variants": variants,
        }

    payload = harness_outer_loop_payload(
        config_root=config_root,
        reports_root=reports_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        harness_spec_path=harness_spec_path,
        profile_name="base",
        project_name="demo",
        task_set_path=task_set_path,
        candidate_harness_patches=[
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
        ],
        run_benchmark_fn=fake_run_benchmark,
    )

    loop_summary = json.loads(
        Path(payload["loop_summary_path"]).read_text(encoding="utf-8")
    )

    assert payload["best_candidate_id"] == "candidate-reference"
    assert payload["selected_candidate_id"] == "candidate-cand-2"
    assert loop_summary["best_candidate_id"] == "candidate-cand-2"


def test_harness_outer_loop_uses_shared_search_loop_request_builder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_root = tmp_path / "configs"
    reports_root = tmp_path / "reports"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    harness_spec_path = reports_root / "integration" / "harness-demo" / "harness_spec.json"
    task_set_path = tmp_path / "task_set.json"
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True, exist_ok=True)
    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {"evaluation": {"evaluators": ["basic"]}}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )
    write_json(
        harness_spec_path,
        {
            "spec_id": "harness-demo",
            "target_project_path": str(project_root),
            "execution_model": {"kind": "json_stdout_cli"},
        },
    )
    write_json(task_set_path, {"tasks": []})
    captured: dict[str, object] = {}

    def fake_build_search_loop_request(**kwargs):
        captured.update(kwargs)
        from meta_harness.loop.schemas import SearchLoopRequest

        return SearchLoopRequest(
            profile_name="base",
            project_name="demo",
            task_set_path=task_set_path,
            config_root=config_root,
            runs_root=runs_root,
            candidates_root=candidates_root,
            reports_root=reports_root,
            task_plugin_id="integration_harness",
            proposer_id="external_candidate_harness_patch",
            evaluation_mode="benchmark",
            loop_id="loop-captured",
        )

    monkeypatch.setattr(
        "meta_harness.services.integration_outer_loop_service.build_search_loop_request",
        fake_build_search_loop_request,
    )

    def fake_run_benchmark(**kwargs):
        spec_payload = json.loads(Path(str(kwargs["spec_path"])).read_text(encoding="utf-8"))
        variant_name = str(spec_payload["variants"][0]["name"])
        run_id = f"run-{variant_name}"
        run_dir = runs_root / run_id
        task_dir = run_dir / "tasks" / "task-a"
        task_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        write_json(run_dir / "score_report.json", {"composite": 1.0})
        write_json(task_dir / "task_result.json", {"task_id": "task-a", "success": True})
        (task_dir / "steps.jsonl").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "task_id": "task-a",
                    "step_id": "step-1",
                    "phase": "run",
                    "status": "completed",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        variants = []
        for variant in spec_payload["variants"]:
            name = str(variant["name"])
            variants.append(
                {
                    "name": name,
                    "variant_type": variant.get("variant_type", "harness"),
                    "candidate_id": f"candidate-{name}",
                    "candidate_harness": variant["candidate_harness"],
                    "run_id": f"run-{name}",
                    "run_ids": [f"run-{name}"],
                    "score": {"composite": 1.0 if name != "reference" else 0.8},
                    "ranking_score": 1.0 if name != "reference" else 0.8,
                    "best_run_id": f"run-{name}",
                }
            )
        return {
            "experiment": spec_payload["experiment"],
            "baseline": spec_payload["baseline"],
            "best_variant": variants[-1]["name"],
            "best_by_quality": variants[-1]["name"],
            "best_by_stability": variants[-1]["name"],
            "report_summary": {"best_variant": variants[-1]["name"]},
            "variants": variants,
        }

    payload = harness_outer_loop_payload(
        config_root=config_root,
        reports_root=reports_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        harness_spec_path=harness_spec_path,
        profile_name="base",
        project_name="demo",
        task_set_path=task_set_path,
        candidate_harness_patches=[
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
            }
        ],
        run_benchmark_fn=fake_run_benchmark,
    )

    assert captured["profile_name"] == "base"
    assert captured["project_name"] == "demo"
    assert captured["plugin_id"] == "integration_harness"
    assert captured["proposer_id"] == "external_candidate_harness_patch"
    assert captured["evaluation_mode"] == "benchmark"
    assert payload["loop_id"] == "loop-captured"
