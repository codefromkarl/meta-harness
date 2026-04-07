from __future__ import annotations

import json
from pathlib import Path

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
    submit_run_export_trace_job,
    submit_run_score_job,
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
from meta_harness.services.profile_service import list_profile_names
from meta_harness.services.run_query_service import (
    list_run_summaries,
    load_run_summary,
    search_failure_records,
)
from meta_harness.services.run_service import initialize_run_record
from meta_harness.services.scoring_service import score_run_record
from meta_harness.services.strategy_service import (
    create_candidate_from_strategy_card_payload,
    inspect_strategy_card_payload,
)
from meta_harness.services.workflow_service import (
    benchmark_suite_workflow_payload,
    benchmark_workflow_payload,
    compile_workflow_payload,
    inspect_workflow_payload,
    run_workflow_payload,
)


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

    promoted = promote_candidate_record(candidates_root, candidate_id)
    assert promoted["candidate_id"] == candidate_id
    assert promoted["champions"]["base:demo"] == candidate_id


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
            "experiment": "contextatlas_combo_validation",
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

    assert run_payload["runs"][0]["experiment"] == "contextatlas_combo_validation"
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
    )

    candidate_dir = candidates_root / str(payload["candidate_id"])
    proposal = json.loads((candidate_dir / "proposal.json").read_text(encoding="utf-8"))
    assert proposal["strategy"] == "increase_budget_on_repeated_failures"


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
        auto_compact_runs=False,
    )

    assert payload["best_variant"] == "larger_top_k"


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

    inspect_payload = inspect_workflow_payload(workflow_path=workflow_path)
    compile_payload = compile_workflow_payload(
        workflow_path=workflow_path,
        output_path=output_path,
    )

    assert inspect_payload["workflow_id"] == "news_aggregation"
    assert inspect_payload["evaluator_packs"] == ["web_scrape/core"]
    assert compile_payload["output_path"] == str(output_path)
    assert compile_payload["task_set"]["tasks"][0]["task_id"] == "fetch_homepages"


def test_workflow_service_run_and_benchmark_bind_evaluator_packs(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
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
    assert captured_benchmark["effective_config_override"]["evaluation"]["command_evaluators"] == [
        {
            "name": "web_scrape/core",
            "command": ["python", "scripts/eval_web_scrape.py"],
        }
    ]


def test_workflow_service_benchmark_suite_binds_evaluator_packs(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
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
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=tmp_path / "candidates",
        run_benchmark_suite_fn=fake_run_benchmark_suite,
        compact_runs_fn=lambda *args, **kwargs: {"compacted_runs": []},
    )

    assert payload["suite"] == "workflow-suite"
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

    assert benchmark_ref["path"] == "reports/benchmarks/workflow-ab.json"
    assert suite_ref["path"] == "reports/benchmark-suites/workflow-suite.json"
    assert (tmp_path / benchmark_ref["path"]).exists()
    assert (tmp_path / suite_ref["path"]).exists()
