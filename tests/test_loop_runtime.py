from __future__ import annotations

import json
from pathlib import Path

from meta_harness.loop.iteration_store import (
    append_iteration_history,
    loop_root_path,
    write_iteration_artifact,
    write_loop_summary,
)
from meta_harness.loop.schemas import (
    ExperienceQuery,
    LoopIterationArtifact,
    LoopSummary,
    SearchLoopRequest,
    SelectionResult,
    StopDecision,
)
from meta_harness.loop.search_loop import run_search_loop
from meta_harness.loop.selection import select_best_result
from meta_harness.loop.stopping import decide_stop


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_history_run(
    runs_root: Path,
    run_id: str,
    *,
    profile: str,
    project: str,
    created_at: str,
    score: float,
    scenario: str,
    error: str | None = None,
) -> None:
    run_dir = runs_root / run_id
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    write_json(
        run_dir / "run_metadata.json",
        {
            "run_id": run_id,
            "profile": profile,
            "project": project,
            "created_at": created_at,
        },
    )
    write_json(
        run_dir / "effective_config.json",
        {"evaluation": {"evaluators": ["basic"]}},
    )
    write_json(
        run_dir / "score_report.json",
        {
            "correctness": {},
            "cost": {},
            "maintainability": {},
            "architecture": {},
            "retrieval": {"grounded_field_rate": 0.4 if scenario == "retrieval" else 0.0},
            "human_collaboration": {},
            "composite": score,
        },
    )
    write_json(
        task_dir / "task_result.json",
        {
            "task_id": "task-a",
            "scenario": scenario,
            "success": error is None,
            "completed_phases": 1,
            "failed_phase": "retrieval" if error else None,
        },
    )
    (task_dir / "stdout.txt").write_text(f"stdout {run_id}\n", encoding="utf-8")
    (task_dir / "stderr.txt").write_text(
        (f"stderr {run_id}\n" if error else ""),
        encoding="utf-8",
    )
    if error:
        (task_dir / "steps.jsonl").write_text(
            json.dumps(
                {
                    "step_id": "step-1",
                    "phase": "retrieval",
                    "status": "failed",
                    "error": error,
                }
            )
            + "\n",
            encoding="utf-8",
        )


def test_select_best_result_supports_best_by_stability() -> None:
    result = {
        "variants": [
            {
                "name": "spiky",
                "candidate_id": "cand-spiky",
                "run_id": "run-spiky",
                "score": {"composite": 1.3},
                "stability": {"composite_range": 0.6, "composite_stddev": 0.25},
                "ranking_score": 1.2,
            },
            {
                "name": "steady",
                "candidate_id": "cand-steady",
                "run_id": "run-steady",
                "score": {"composite": 1.15},
                "stability": {"composite_range": 0.02, "composite_stddev": 0.01},
                "ranking_score": 1.15,
            },
        ]
    }

    selection = select_best_result(
        candidate_id="fallback",
        evaluation_result=result,
        selection_policy="best_by_stability",
    )

    assert selection.candidate_id == "cand-steady"
    assert selection.run_id == "run-steady"


def test_select_best_result_supports_baseline_guardrail() -> None:
    result = {
        "variants": [
            {
                "name": "baseline",
                "candidate_id": "cand-baseline",
                "run_id": "run-baseline",
                "is_reference": True,
                "score": {"composite": 1.0},
                "stability": {"composite_range": 0.0, "composite_stddev": 0.0},
                "ranking_score": 1.0,
            },
            {
                "name": "regressed",
                "candidate_id": "cand-regressed",
                "run_id": "run-regressed",
                "score": {"composite": 0.8},
                "stability": {"composite_range": 0.0, "composite_stddev": 0.0},
                "ranking_score": 0.8,
            },
        ]
    }

    selection = select_best_result(
        candidate_id="fallback",
        evaluation_result=result,
        selection_policy="baseline_guardrail",
    )

    assert selection.candidate_id == "cand-baseline"
    assert selection.variant_name == "baseline"


def test_select_best_result_supports_multi_objective_rank() -> None:
    result = {
        "variants": [
            {
                "name": "quality_only",
                "candidate_id": "cand-quality",
                "run_id": "run-quality",
                "score": {"composite": 1.3},
                "stability": {"composite_range": 0.7, "composite_stddev": 0.4},
                "cost": {"total_cost": 9.0},
                "ranking_score": 1.0,
            },
            {
                "name": "balanced",
                "candidate_id": "cand-balanced",
                "run_id": "run-balanced",
                "score": {"composite": 1.18},
                "stability": {"composite_range": 0.02, "composite_stddev": 0.01},
                "cost": {"total_cost": 1.0},
                "ranking_score": 1.1,
            },
        ]
    }

    selection = select_best_result(
        candidate_id="fallback",
        evaluation_result=result,
        selection_policy="multi_objective_rank",
    )

    assert selection.candidate_id == "cand-balanced"
    assert selection.variant_name == "balanced"


def test_decide_stop_supports_instability_and_regression() -> None:
    unstable = decide_stop(
        iteration_index=2,
        max_iterations=8,
        best_score=1.2,
        score_history=[1.2, 1.18],
        recent_scores=[1.2, 0.62],
        current_score=0.62,
        stability_window=2,
        instability_threshold=0.4,
    )
    regressed = decide_stop(
        iteration_index=3,
        max_iterations=8,
        best_score=1.2,
        score_history=[1.2, 1.15, 0.55],
        recent_scores=[1.15, 0.55],
        current_score=0.55,
        regression_tolerance=0.35,
    )

    assert unstable.should_stop is True
    assert unstable.reason == "instability threshold reached"
    assert regressed.should_stop is True
    assert regressed.reason == "regression tolerance reached"


def test_iteration_store_writes_loop_contract_files(tmp_path: Path) -> None:
    loop_dir = loop_root_path(tmp_path / "reports", "loop-1")
    request = SearchLoopRequest(
        config_root=tmp_path / "configs",
        runs_root=tmp_path / "runs",
        candidates_root=tmp_path / "candidates",
        profile_name="base",
        project_name="demo",
        task_set_path=tmp_path / "task_set.json",
    )
    artifact = LoopIterationArtifact(
        iteration_id="loop-1-0001",
        iteration_index=1,
        objective={"focus": "all"},
        experience={"matching_runs": []},
        proposal={"strategy": "heuristic"},
        candidate_id="cand-1",
        candidate_path="/tmp/candidates/cand-1",
        run_id="run-1",
        run_path="/tmp/runs/run-1",
        selection=SelectionResult(candidate_id="cand-1", run_id="run-1", score=1.0),
        stop_decision=StopDecision(
            should_stop=False,
            reason="continue searching",
            iteration_index=1,
            max_iterations=3,
        ),
        evaluation={
            "variants": [],
            "validation": {
                "status": "passed",
                "validation_artifact": {"kind": "lightweight", "status": "passed"},
            },
        },
        summary={"score": 1.0},
    )

    paths = write_iteration_artifact(loop_dir, artifact)
    history_path = append_iteration_history(loop_dir, artifact)
    summary = LoopSummary(
        loop_id="loop-1",
        profile_name="base",
        project_name="demo",
        request=request,
        best_candidate_id="cand-1",
        best_run_id="run-1",
        best_score=1.0,
        iteration_count=1,
        stop_reason="continue searching",
        iterations=[artifact],
        loop_dir=str(loop_dir),
    )
    loop_summary_path = write_loop_summary(loop_dir, summary)

    assert (loop_dir / "iteration_history.jsonl") == history_path
    assert loop_summary_path == loop_dir / "loop.json"
    assert paths["iteration_json"].exists()
    assert paths["proposal_input_json"].exists()
    assert paths["proposal_output_json"].exists()
    assert paths["selected_candidate_json"].exists()
    assert paths["benchmark_summary_json"].exists()
    assert paths["validation_summary_json"].exists()
    assert paths["next_round_context_json"].exists()
    assert paths["experience_summary_json"].exists()
    validation_payload = json.loads(
        paths["validation_summary_json"].read_text(encoding="utf-8")
    )
    assert validation_payload["status"] == "passed"
    next_round_context = json.loads(
        paths["next_round_context_json"].read_text(encoding="utf-8")
    )
    assert next_round_context["validation_summary_path"] == str(
        paths["validation_summary_json"]
    )
    loop_payload = json.loads(loop_summary_path.read_text(encoding="utf-8"))
    assert loop_payload["loop_id"] == "loop-1"
    assert loop_payload["iteration_count"] == 1


def test_run_search_loop_honors_instability_stopping_policy(tmp_path: Path) -> None:
    class _Plugin:
        plugin_id = "test"

        def assemble_objective(self, **_: object) -> dict[str, object]:
            return {"goal": "stop on instability"}

        def assemble_experience(self, **_: object) -> dict[str, object]:
            return {}

        def build_evaluation_plan(self, **_: object) -> dict[str, object]:
            return {
                "kind": "benchmark",
                "benchmark_spec_path": str(tmp_path / "benchmark.json"),
                "selection_policy": "best_by_score",
                "instability_threshold": 0.4,
                "stability_window": 2,
            }

        def summarize_iteration(self, **_: object) -> dict[str, object]:
            return {"summary": "ok"}

    class _Proposer:
        proposer_id = "dummy"

        def propose(self, **_: object) -> dict[str, object]:
            return {
                "proposer_kind": "dummy",
                "proposal": {"strategy": "dummy"},
                "config_patch": {},
                "notes": "dummy",
            }

    scores = iter([1.2, 0.6, 0.59])

    def _benchmark(**_: object) -> dict[str, object]:
        score = next(scores)
        return {
            "variants": [
                {
                    "name": f"candidate-{score}",
                    "candidate_id": f"cand-{score}",
                    "run_id": f"run-{score}",
                    "score": {"composite": score},
                    "stability": {"composite_range": 0.0, "composite_stddev": 0.0},
                    "ranking_score": score,
                }
            ]
        }

    request = SearchLoopRequest(
        config_root=tmp_path / "configs",
        runs_root=tmp_path / "runs",
        candidates_root=tmp_path / "candidates",
        profile_name="base",
        project_name="demo",
        task_set_path=tmp_path / "task_set.json",
        reports_root=tmp_path / "reports",
        max_iterations=4,
    )
    (tmp_path / "configs" / "profiles").mkdir(parents=True, exist_ok=True)
    (tmp_path / "configs" / "projects").mkdir(parents=True, exist_ok=True)
    (tmp_path / "candidates").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "task_set.json").write_text('{"tasks":[]}', encoding="utf-8")
    (tmp_path / "configs" / "platform.json").write_text("{}", encoding="utf-8")
    (tmp_path / "benchmark.json").write_text("{}", encoding="utf-8")
    (tmp_path / "configs" / "profiles" / "base.json").write_text(
        '{"description":"base","defaults":{}}',
        encoding="utf-8",
    )
    (tmp_path / "configs" / "projects" / "demo.json").write_text(
        '{"workflow":"base","overrides":{}}',
        encoding="utf-8",
    )

    summary = run_search_loop(
        request,
        task_plugin=_Plugin(),
        proposer=_Proposer(),
        benchmark_fn=_benchmark,
    )

    assert summary.iteration_count == 2
    assert summary.stop_reason == "instability threshold reached"


def test_run_search_loop_honors_experience_query_filters(tmp_path: Path) -> None:
    class _Plugin:
        plugin_id = "test"

        def assemble_objective(self, **_: object) -> dict[str, object]:
            return {"goal": "focus retrieval"}

        def assemble_experience(self, **_: object) -> dict[str, object]:
            return {}

        def build_evaluation_plan(self, **_: object) -> dict[str, object]:
            return {
                "kind": "benchmark",
                "benchmark_spec_path": str(tmp_path / "benchmark.json"),
            }

        def summarize_iteration(self, **_: object) -> dict[str, object]:
            return {"summary": "ok"}

    class _Proposer:
        proposer_id = "capture"

        def __init__(self) -> None:
            self.captured: dict[str, object] | None = None

        def propose(self, **kwargs: object) -> dict[str, object]:
            self.captured = kwargs.get("experience")
            return {
                "proposer_kind": "capture",
                "proposal": {"strategy": "capture"},
                "config_patch": {},
                "notes": "capture",
            }

    def _benchmark(**_: object) -> dict[str, object]:
        return {
            "variants": [
                {
                    "name": "candidate",
                    "candidate_id": "cand-1",
                    "run_id": "run-new",
                    "score": {"composite": 1.0},
                    "stability": {"composite_range": 0.0, "composite_stddev": 0.0},
                    "ranking_score": 1.0,
                }
            ]
        }

    (tmp_path / "configs" / "profiles").mkdir(parents=True, exist_ok=True)
    (tmp_path / "configs" / "projects").mkdir(parents=True, exist_ok=True)
    (tmp_path / "candidates").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "task_set.json").write_text('{"tasks":[]}', encoding="utf-8")
    (tmp_path / "benchmark.json").write_text("{}", encoding="utf-8")
    (tmp_path / "configs" / "platform.json").write_text("{}", encoding="utf-8")
    (tmp_path / "configs" / "profiles" / "base.json").write_text(
        '{"description":"base","defaults":{}}',
        encoding="utf-8",
    )
    (tmp_path / "configs" / "projects" / "demo.json").write_text(
        '{"workflow":"base","overrides":{}}',
        encoding="utf-8",
    )
    write_history_run(
        tmp_path / "runs",
        "run-retrieval",
        profile="base",
        project="demo",
        created_at="2026-04-08T09:00:00Z",
        score=0.4,
        scenario="retrieval",
        error="retrieval timeout while fetching context",
    )
    write_history_run(
        tmp_path / "runs",
        "run-architecture",
        profile="base",
        project="demo",
        created_at="2026-04-08T10:00:00Z",
        score=1.0,
        scenario="architecture",
    )

    proposer = _Proposer()
    request = SearchLoopRequest(
        config_root=tmp_path / "configs",
        runs_root=tmp_path / "runs",
        candidates_root=tmp_path / "candidates",
        profile_name="base",
        project_name="demo",
        task_set_path=tmp_path / "task_set.json",
        reports_root=tmp_path / "reports",
        max_iterations=1,
        experience_query=ExperienceQuery(
            focus="retrieval",
            dedupe_failure_families=True,
        ),
    )

    run_search_loop(
        request,
        task_plugin=_Plugin(),
        proposer=proposer,
        benchmark_fn=_benchmark,
    )

    assert proposer.captured is not None
    assert [record["run_id"] for record in proposer.captured["matching_runs"]] == [
        "run-retrieval"
    ]
    assert len(proposer.captured["failure_records"]) == 1


def test_run_search_loop_writes_next_round_experience_summary_and_plugin_overrides(
    tmp_path: Path,
) -> None:
    class _Plugin:
        plugin_id = "test"

        def assemble_objective(self, **_: object) -> dict[str, object]:
            return {"goal": "focus retrieval"}

        def build_experience_query(self, **_: object) -> dict[str, object]:
            return {
                "focus": "retrieval",
                "dedupe_failure_families": True,
            }

        def assemble_experience(self, **_: object) -> dict[str, object]:
            return {}

        def build_evaluation_plan(self, **_: object) -> dict[str, object]:
            return {
                "kind": "benchmark",
                "benchmark_spec_path": str(tmp_path / "benchmark.json"),
            }

        def build_proposal_constraints(self, **_: object) -> dict[str, object]:
            return {"preferred_family": "retrieval"}

        def build_stopping_policy(self, **_: object) -> dict[str, object]:
            return {"no_improvement_limit": 0}

        def summarize_iteration(self, **_: object) -> dict[str, object]:
            return {"summary": "ok"}

    class _Proposer:
        proposer_id = "capture"

        def __init__(self) -> None:
            self.constraints: dict[str, object] | None = None

        def propose(self, **kwargs: object) -> dict[str, object]:
            self.constraints = kwargs.get("constraints")
            return {
                "proposer_kind": "capture",
                "proposal": {"strategy": "capture"},
                "config_patch": {},
                "notes": "capture",
            }

    def _benchmark(**_: object) -> dict[str, object]:
        return {
            "variants": [
                {
                    "name": "candidate",
                    "candidate_id": "cand-1",
                    "run_id": "run-new",
                    "score": {"composite": 1.0},
                    "stability": {"composite_range": 0.0, "composite_stddev": 0.0},
                    "ranking_score": 1.0,
                }
            ]
        }

    (tmp_path / "configs" / "profiles").mkdir(parents=True, exist_ok=True)
    (tmp_path / "configs" / "projects").mkdir(parents=True, exist_ok=True)
    (tmp_path / "candidates").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "task_set.json").write_text('{"tasks":[]}', encoding="utf-8")
    (tmp_path / "benchmark.json").write_text("{}", encoding="utf-8")
    (tmp_path / "configs" / "platform.json").write_text("{}", encoding="utf-8")
    (tmp_path / "configs" / "profiles" / "base.json").write_text(
        '{"description":"base","defaults":{}}',
        encoding="utf-8",
    )
    (tmp_path / "configs" / "projects" / "demo.json").write_text(
        '{"workflow":"base","overrides":{}}',
        encoding="utf-8",
    )
    write_history_run(
        tmp_path / "runs",
        "run-retrieval",
        profile="base",
        project="demo",
        created_at="2026-04-08T09:00:00Z",
        score=0.4,
        scenario="retrieval",
        error="retrieval timeout while fetching context",
    )

    proposer = _Proposer()
    request = SearchLoopRequest(
        config_root=tmp_path / "configs",
        runs_root=tmp_path / "runs",
        candidates_root=tmp_path / "candidates",
        profile_name="base",
        project_name="demo",
        task_set_path=tmp_path / "task_set.json",
        reports_root=tmp_path / "reports",
        max_iterations=3,
    )

    summary = run_search_loop(
        request,
        task_plugin=_Plugin(),
        proposer=proposer,
        benchmark_fn=_benchmark,
    )

    assert summary.stop_reason == "no improvement limit reached"
    assert proposer.constraints is not None
    assert proposer.constraints["plugin_constraints"]["preferred_family"] == "retrieval"
    loop_dir = Path(summary.loop_dir)
    next_round_context = json.loads(
        (loop_dir / "iterations" / f"{summary.loop_id}-0001" / "next_round_context.json").read_text(
            encoding="utf-8"
        )
    )
    experience_summary_path = Path(next_round_context["experience_summary_path"])
    validation_summary_path = Path(next_round_context["validation_summary_path"])
    experience_summary = json.loads(experience_summary_path.read_text(encoding="utf-8"))
    validation_summary = json.loads(validation_summary_path.read_text(encoding="utf-8"))
    assert experience_summary["focus"] == "retrieval"
    assert experience_summary["representative_failures"][0]["family"] == "retrieval timeout"
    assert validation_summary == {}


def test_run_search_loop_writes_proposer_context_bundle_and_passes_paths(
    tmp_path: Path,
) -> None:
    class _Plugin:
        plugin_id = "test"

        def assemble_objective(self, **_: object) -> dict[str, object]:
            return {"goal": "improve retrieval diagnostics", "focus": "retrieval"}

        def assemble_experience(self, **_: object) -> dict[str, object]:
            return {}

        def build_evaluation_plan(self, **_: object) -> dict[str, object]:
            return {
                "kind": "benchmark",
                "benchmark_spec_path": str(tmp_path / "benchmark.json"),
            }

        def summarize_iteration(self, **_: object) -> dict[str, object]:
            return {"summary": "ok"}

    class _Proposer:
        proposer_id = "capture"

        def __init__(self) -> None:
            self.constraints: dict[str, object] | None = None

        def propose(self, **kwargs: object) -> dict[str, object]:
            self.constraints = kwargs.get("constraints")
            return {
                "proposer_kind": "capture",
                "proposal": {"strategy": "capture"},
                "config_patch": {},
                "notes": "capture",
            }

    def _benchmark(**_: object) -> dict[str, object]:
        return {
            "variants": [
                {
                    "name": "candidate",
                    "candidate_id": "cand-ctx",
                    "run_id": "run-ctx",
                    "score": {"composite": 1.0},
                    "stability": {"composite_range": 0.0, "composite_stddev": 0.0},
                    "ranking_score": 1.0,
                }
            ]
        }

    (tmp_path / "configs" / "profiles").mkdir(parents=True, exist_ok=True)
    (tmp_path / "configs" / "projects").mkdir(parents=True, exist_ok=True)
    (tmp_path / "candidates").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "task_set.json").write_text('{"tasks":[]}', encoding="utf-8")
    (tmp_path / "benchmark.json").write_text("{}", encoding="utf-8")
    (tmp_path / "configs" / "platform.json").write_text("{}", encoding="utf-8")
    (tmp_path / "configs" / "profiles" / "base.json").write_text(
        '{"description":"base","defaults":{}}',
        encoding="utf-8",
    )
    (tmp_path / "configs" / "projects" / "demo.json").write_text(
        '{"workflow":"base","overrides":{}}',
        encoding="utf-8",
    )
    write_history_run(
        tmp_path / "runs",
        "run-retrieval",
        profile="base",
        project="demo",
        created_at="2026-04-08T09:00:00Z",
        score=0.4,
        scenario="retrieval",
        error="retrieval timeout while fetching context",
    )

    proposer = _Proposer()
    request = SearchLoopRequest(
        config_root=tmp_path / "configs",
        runs_root=tmp_path / "runs",
        candidates_root=tmp_path / "candidates",
        profile_name="base",
        project_name="demo",
        task_set_path=tmp_path / "task_set.json",
        reports_root=tmp_path / "reports",
        max_iterations=1,
    )

    summary = run_search_loop(
        request,
        task_plugin=_Plugin(),
        proposer=proposer,
        benchmark_fn=_benchmark,
    )

    loop_dir = Path(summary.loop_dir)
    bundle_dir = loop_dir / "iterations" / f"{summary.loop_id}-0001" / "proposer_context"
    manifest_path = bundle_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["objective_path"] == str((bundle_dir / "objective.json").resolve())
    assert manifest["experience_path"] == str((bundle_dir / "experience.json").resolve())
    assert manifest["selected_runs"][0]["run_id"] == "run-retrieval"
    assert (
        bundle_dir / "selected_runs" / "run-retrieval" / "run_metadata.json"
    ).exists()
    assert (
        bundle_dir
        / "selected_runs"
        / "run-retrieval"
        / "tasks"
        / "task-a"
        / "steps.jsonl"
    ).exists()
    assert proposer.constraints is not None
    proposer_context = proposer.constraints["proposer_context"]
    assert proposer_context["bundle_dir"] == str(bundle_dir.resolve())
    assert proposer_context["manifest_path"] == str(manifest_path.resolve())


def test_execute_evaluation_plan_runs_lightweight_validation_before_benchmark(
    tmp_path: Path,
) -> None:
    from meta_harness.loop.search_loop import execute_evaluation_plan

    request = SearchLoopRequest(
        config_root=tmp_path / "configs",
        runs_root=tmp_path / "runs",
        candidates_root=tmp_path / "candidates",
        profile_name="base",
        project_name="demo",
        task_set_path=tmp_path / "task_set.json",
        reports_root=tmp_path / "reports",
        max_iterations=1,
    )
    (tmp_path / "configs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "candidates").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "task_set.json").write_text('{"tasks":[]}', encoding="utf-8")

    calls: list[str] = []

    def _validation(**_: object) -> dict[str, object]:
        calls.append("validation")
        return {
            "status": "passed",
            "validation_artifact": {
                "kind": "lightweight",
                "status": "passed",
            },
        }

    def _benchmark(**_: object) -> dict[str, object]:
        calls.append("benchmark")
        return {
            "variants": [
                {
                    "name": "candidate",
                    "candidate_id": "cand-validated",
                    "run_id": "run-validated",
                    "score": {"composite": 1.0},
                    "stability": {"composite_range": 0.0, "composite_stddev": 0.0},
                    "ranking_score": 1.0,
                }
            ]
        }

    result = execute_evaluation_plan(
        request=request,
        evaluation_plan={
            "kind": "benchmark",
            "benchmark_spec_path": str(tmp_path / "benchmark.json"),
            "validation_command": ["python", "-c", "print('ok')"],
        },
        benchmark_fn=_benchmark,
        shadow_run_fn=lambda **_: "run-shadow",
        candidate_id="cand-validated",
        effective_config={},
        validation_fn=_validation,
    )

    assert calls == ["validation", "benchmark"]
    assert result["executor"]["status"] == "completed"
    assert result["validation"]["status"] == "passed"
    assert result["validation"]["validation_artifact"]["kind"] == "lightweight"


def test_execute_evaluation_plan_skips_benchmark_when_lightweight_validation_fails(
    tmp_path: Path,
) -> None:
    from meta_harness.loop.search_loop import execute_evaluation_plan

    request = SearchLoopRequest(
        config_root=tmp_path / "configs",
        runs_root=tmp_path / "runs",
        candidates_root=tmp_path / "candidates",
        profile_name="base",
        project_name="demo",
        task_set_path=tmp_path / "task_set.json",
        reports_root=tmp_path / "reports",
        max_iterations=1,
    )
    (tmp_path / "configs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "candidates").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "task_set.json").write_text('{"tasks":[]}', encoding="utf-8")

    calls: list[str] = []

    def _validation(**_: object) -> dict[str, object]:
        calls.append("validation")
        return {
            "status": "failed",
            "reason": "smoke import failed",
            "validation_artifact": {
                "kind": "lightweight",
                "status": "failed",
                "reason": "smoke import failed",
            },
        }

    def _benchmark(**_: object) -> dict[str, object]:
        calls.append("benchmark")
        return {
            "variants": []
        }

    result = execute_evaluation_plan(
        request=request,
        evaluation_plan={
            "kind": "benchmark",
            "benchmark_spec_path": str(tmp_path / "benchmark.json"),
            "validation_command": ["python", "-c", "print('ok')"],
        },
        benchmark_fn=_benchmark,
        shadow_run_fn=lambda **_: "run-shadow",
        candidate_id="cand-invalid",
        effective_config={},
        validation_fn=_validation,
    )

    assert calls == ["validation"]
    assert result["executor"]["status"] == "validation_failed"
    assert result["validation"]["reason"] == "smoke import failed"
    assert result["benchmark_skipped"] is True


def test_execute_evaluation_plan_resolves_relative_validation_workdir_from_workspace(
    tmp_path: Path,
) -> None:
    from meta_harness.loop.search_loop import execute_evaluation_plan

    repo_root = tmp_path / "repo"
    validation_dir = repo_root / "checks"
    validation_dir.mkdir(parents=True, exist_ok=True)

    request = SearchLoopRequest(
        config_root=tmp_path / "configs",
        runs_root=tmp_path / "runs",
        candidates_root=tmp_path / "candidates",
        profile_name="base",
        project_name="demo",
        task_set_path=tmp_path / "task_set.json",
        reports_root=tmp_path / "reports",
        max_iterations=1,
    )
    (tmp_path / "configs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "candidates").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "task_set.json").write_text('{"tasks":[]}', encoding="utf-8")

    def _benchmark(**_: object) -> dict[str, object]:
        return {
            "variants": [
                {
                    "name": "candidate",
                    "candidate_id": "cand-validated",
                    "run_id": "run-validated",
                    "score": {"composite": 1.0},
                    "stability": {"composite_range": 0.0, "composite_stddev": 0.0},
                    "ranking_score": 1.0,
                }
            ]
        }

    result = execute_evaluation_plan(
        request=request,
        evaluation_plan={
            "kind": "benchmark",
            "benchmark_spec_path": str(tmp_path / "benchmark.json"),
            "validation_command": ["python", "-c", "print('ok')"],
            "validation_workdir": "checks",
        },
        benchmark_fn=_benchmark,
        shadow_run_fn=lambda **_: "run-shadow",
        candidate_id="cand-validated",
        effective_config={"runtime": {"workspace": {"source_repo": str(repo_root)}}},
    )

    assert result["validation"]["status"] == "passed"
    assert result["validation"]["validation_artifact"]["workdir"] == str(validation_dir)


def test_run_search_loop_ranks_multiple_proposers_and_records_rejected_proposals(
    tmp_path: Path,
) -> None:
    class _Plugin:
        plugin_id = "test"

        def assemble_objective(self, **_: object) -> dict[str, object]:
            return {"goal": "rank proposals"}

        def assemble_experience(self, **_: object) -> dict[str, object]:
            return {}

        def build_evaluation_plan(self, **_: object) -> dict[str, object]:
            return {
                "kind": "benchmark",
                "benchmark_spec_path": str(tmp_path / "benchmark.json"),
            }

        def summarize_iteration(self, **_: object) -> dict[str, object]:
            return {"summary": "ok"}

    class _HighRankProposer:
        proposer_id = "high"

        def propose(self, **_: object) -> dict[str, object]:
            return {
                "proposer_kind": "high",
                "proposal": {"strategy": "high"},
                "config_patch": {"retrieval": {"top_k": 20}},
                "notes": "high rank",
                "proposal_score": 1.0,
                "stability_score": 0.9,
                "cost_score": 0.8,
            }

    class _LowRankProposer:
        proposer_id = "low"

        def propose(self, **_: object) -> dict[str, object]:
            return {
                "proposer_kind": "low",
                "proposal": {"strategy": "low"},
                "config_patch": {"retrieval": {"top_k": 6}},
                "notes": "low rank",
                "proposal_score": 0.4,
                "stability_score": 0.2,
                "cost_score": 0.1,
            }

    def _benchmark(**_: object) -> dict[str, object]:
        return {
            "variants": [
                {
                    "name": "candidate",
                    "candidate_id": "cand-high",
                    "run_id": "run-high",
                    "score": {"composite": 1.0},
                    "stability": {"composite_range": 0.0, "composite_stddev": 0.0},
                    "ranking_score": 1.0,
                }
            ]
        }

    (tmp_path / "configs" / "profiles").mkdir(parents=True, exist_ok=True)
    (tmp_path / "configs" / "projects").mkdir(parents=True, exist_ok=True)
    (tmp_path / "candidates").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "proposals").mkdir(parents=True, exist_ok=True)
    (tmp_path / "task_set.json").write_text('{"tasks":[]}', encoding="utf-8")
    (tmp_path / "benchmark.json").write_text("{}", encoding="utf-8")
    (tmp_path / "configs" / "platform.json").write_text("{}", encoding="utf-8")
    (tmp_path / "configs" / "profiles" / "base.json").write_text(
        '{"description":"base","defaults":{}}',
        encoding="utf-8",
    )
    (tmp_path / "configs" / "projects" / "demo.json").write_text(
        '{"workflow":"base","overrides":{}}',
        encoding="utf-8",
    )

    summary = run_search_loop(
        SearchLoopRequest(
            config_root=tmp_path / "configs",
            runs_root=tmp_path / "runs",
            candidates_root=tmp_path / "candidates",
            profile_name="base",
            project_name="demo",
            task_set_path=tmp_path / "task_set.json",
            reports_root=tmp_path / "reports",
            max_iterations=1,
        ),
        task_plugin=_Plugin(),
        proposer=[_LowRankProposer(), _HighRankProposer()],
        benchmark_fn=_benchmark,
        proposals_root=tmp_path / "proposals",
    )

    assert summary.best_candidate_id is not None
    iteration_dir = Path(summary.loop_dir) / "iterations" / f"{summary.loop_id}-0001"
    proposal_output = json.loads((iteration_dir / "proposal_output.json").read_text(encoding="utf-8"))
    assert proposal_output["proposal"]["strategy"] == "high"
    assert proposal_output["proposal_evaluation"]["selected_proposal"]["proposer_kind"] == "high"
    assert proposal_output["proposal_evaluation"]["rejected_proposals"][0]["proposer_kind"] == "low"


def test_run_search_loop_uses_shared_evaluation_executor_for_shadow_run(
    tmp_path: Path,
) -> None:
    class _Plugin:
        plugin_id = "test"

        def assemble_objective(self, **_: object) -> dict[str, object]:
            return {"goal": "shadow evaluation"}

        def assemble_experience(self, **_: object) -> dict[str, object]:
            return {}

        def build_evaluation_plan(self, **_: object) -> dict[str, object]:
            return {
                "kind": "shadow-run",
            }

        def summarize_iteration(self, **_: object) -> dict[str, object]:
            return {"summary": "ok"}

    class _Proposer:
        proposer_id = "dummy"

        def propose(self, **_: object) -> dict[str, object]:
            return {
                "proposer_kind": "dummy",
                "proposal": {"strategy": "dummy"},
                "config_patch": {},
                "notes": "dummy",
            }

    def _shadow_run(**_: object) -> str:
        run_id = "shadow-run-1"
        run_dir = tmp_path / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            run_dir / "run_metadata.json",
            {"run_id": run_id, "profile": "base", "project": "demo"},
        )
        write_json(run_dir / "effective_config.json", {"evaluation": {"evaluators": ["basic"]}})
        write_json(run_dir / "score_report.json", {"composite": 0.9})
        return run_id

    (tmp_path / "configs" / "profiles").mkdir(parents=True, exist_ok=True)
    (tmp_path / "configs" / "projects").mkdir(parents=True, exist_ok=True)
    (tmp_path / "candidates").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "task_set.json").write_text('{"tasks":[]}', encoding="utf-8")
    (tmp_path / "configs" / "platform.json").write_text("{}", encoding="utf-8")
    (tmp_path / "configs" / "profiles" / "base.json").write_text(
        '{"description":"base","defaults":{}}',
        encoding="utf-8",
    )
    (tmp_path / "configs" / "projects" / "demo.json").write_text(
        '{"workflow":"base","overrides":{}}',
        encoding="utf-8",
    )

    summary = run_search_loop(
        SearchLoopRequest(
            config_root=tmp_path / "configs",
            runs_root=tmp_path / "runs",
            candidates_root=tmp_path / "candidates",
            profile_name="base",
            project_name="demo",
            task_set_path=tmp_path / "task_set.json",
            reports_root=tmp_path / "reports",
            max_iterations=1,
        ),
        task_plugin=_Plugin(),
        proposer=_Proposer(),
        shadow_run_fn=_shadow_run,
    )

    assert summary.iterations[0].evaluation["mode"] == "shadow-run"
    assert summary.iterations[0].evaluation["executor"]["kind"] == "shadow-run"
