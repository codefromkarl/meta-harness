from __future__ import annotations

import json
from pathlib import Path

from meta_harness.loop.experience import assemble_experience_context, list_experience_runs


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_run(
    runs_root: Path,
    run_id: str,
    *,
    profile: str,
    project: str,
    created_at: str,
    score: float = 0.0,
    error: str | None = None,
    scenario: str = "history-check",
    phase: str = "compile",
    retrieval_score: float | None = None,
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
        {"budget": {"max_turns": 12}, "evaluation": {"evaluators": ["basic"]}},
    )
    write_json(
        run_dir / "score_report.json",
        {
            "correctness": {},
            "cost": {},
            "maintainability": {},
            "architecture": {},
            "retrieval": (
                {"grounded_field_rate": retrieval_score}
                if retrieval_score is not None
                else {}
            ),
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
            "failed_phase": phase if error else None,
        },
    )
    (task_dir / "stdout.txt").write_text(f"stdout for {run_id}\n", encoding="utf-8")
    (task_dir / "stderr.txt").write_text(
        (f"stderr for {run_id}\n" if error else ""),
        encoding="utf-8",
    )
    if error:
        (task_dir / "steps.jsonl").write_text(
            json.dumps(
                {
                    "step_id": "step-1",
                    "phase": phase,
                    "status": "failed",
                    "error": error,
                }
            )
            + "\n",
            encoding="utf-8",
        )


def test_list_experience_runs_filters_by_history_sources(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    write_run(
        runs_root,
        "run-maint",
        profile="maintenance",
        project="demo",
        created_at="2026-04-08T10:00:00Z",
    )
    write_run(
        runs_root,
        "run-repair",
        profile="repair",
        project="demo_patch",
        created_at="2026-04-08T11:00:00Z",
    )

    runs = list_experience_runs(
        runs_root=runs_root,
        profile_name="repair",
        project_name="demo_patch",
        history_sources=[{"profile": "maintenance", "project": "demo"}],
    )

    assert [record["run_id"] for record in runs] == ["run-maint"]


def test_assemble_experience_context_can_enrich_matching_runs_with_run_context(
    tmp_path: Path,
) -> None:
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    write_run(
        runs_root,
        "run-maint",
        profile="maintenance",
        project="demo",
        created_at="2026-04-08T10:00:00Z",
        score=2.5,
        error="Trait bound `Foo: Clone` is not satisfied",
    )

    payload = assemble_experience_context(
        runs_root=runs_root,
        candidates_root=candidates_root,
        profile_name="repair",
        project_name="demo_patch",
        history_sources=[{"profile": "maintenance", "project": "demo"}],
        run_context_builder=lambda run_dir, record: {
            "run_id": record["run_id"],
            "task_count": len(list((run_dir / "tasks").iterdir())),
        },
    )

    assert payload["source_run_ids"] == ["run-maint"]
    assert payload["matching_runs"][0]["run_context"] == {
        "run_id": "run-maint",
        "task_count": 1,
    }
    assert payload["failure_records"][0]["run_id"] == "run-maint"


def test_assemble_experience_context_adds_representative_failures_and_score_delta(
    tmp_path: Path,
) -> None:
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    write_run(
        runs_root,
        "run-older",
        profile="repair",
        project="demo_patch",
        created_at="2026-04-08T09:00:00Z",
        score=0.6,
        error="compile failed",
    )
    write_run(
        runs_root,
        "run-latest",
        profile="repair",
        project="demo_patch",
        created_at="2026-04-08T10:00:00Z",
        score=1.1,
    )

    payload = assemble_experience_context(
        runs_root=runs_root,
        candidates_root=candidates_root,
        profile_name="repair",
        project_name="demo_patch",
    )

    assert payload["best_run"]["run_id"] == "run-latest"
    assert payload["score_delta"] == 0.5
    assert payload["representative_failures"][0]["run_id"] == "run-older"
    assert payload["representative_successes"][0]["run_id"] == "run-latest"


def test_list_experience_runs_supports_best_k_selection(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    write_run(
        runs_root,
        "run-a",
        profile="repair",
        project="demo_patch",
        created_at="2026-04-08T09:00:00Z",
        score=0.2,
    )
    write_run(
        runs_root,
        "run-b",
        profile="repair",
        project="demo_patch",
        created_at="2026-04-08T10:00:00Z",
        score=0.9,
    )
    write_run(
        runs_root,
        "run-c",
        profile="repair",
        project="demo_patch",
        created_at="2026-04-08T11:00:00Z",
        score=0.6,
    )

    runs = list_experience_runs(
        runs_root=runs_root,
        profile_name="repair",
        project_name="demo_patch",
        best_k=2,
    )

    assert [record["run_id"] for record in runs] == ["run-b", "run-c"]


def test_assemble_experience_context_supports_focus_filter_and_failure_family_dedupe(
    tmp_path: Path,
) -> None:
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    write_run(
        runs_root,
        "run-retrieval-1",
        profile="repair",
        project="demo_patch",
        created_at="2026-04-08T09:00:00Z",
        score=0.7,
        error="retrieval timeout while fetching context",
        scenario="retrieval",
        phase="retrieval",
        retrieval_score=0.3,
    )
    write_run(
        runs_root,
        "run-retrieval-2",
        profile="repair",
        project="demo_patch",
        created_at="2026-04-08T10:00:00Z",
        score=0.8,
        error="retrieval timeout while fetching context again",
        scenario="retrieval",
        phase="retrieval",
        retrieval_score=0.4,
    )
    write_run(
        runs_root,
        "run-architecture",
        profile="repair",
        project="demo_patch",
        created_at="2026-04-08T11:00:00Z",
        score=1.1,
        scenario="architecture",
    )

    payload = assemble_experience_context(
        runs_root=runs_root,
        candidates_root=candidates_root,
        profile_name="repair",
        project_name="demo_patch",
        objective={"focus": "retrieval"},
        focus="retrieval",
        dedupe_failure_families=True,
    )

    assert [record["run_id"] for record in payload["matching_runs"]] == [
        "run-retrieval-1",
        "run-retrieval-2",
    ]
    assert payload["focus_summary"]["focus"] == "retrieval"
    assert payload["focus_summary"]["matching_run_count"] == 2
    assert len(payload["failure_records"]) == 1
    assert payload["failure_records"][0]["family"] == "retrieval timeout"


def test_assemble_experience_context_adds_artifact_refs_and_capability_gaps(
    tmp_path: Path,
) -> None:
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    write_run(
        runs_root,
        "run-low",
        profile="repair",
        project="demo_patch",
        created_at="2026-04-08T09:00:00Z",
        score=0.4,
        error="retrieval grounding failed",
        scenario="retrieval",
        phase="retrieval",
        retrieval_score=0.2,
    )
    write_run(
        runs_root,
        "run-high",
        profile="repair",
        project="demo_patch",
        created_at="2026-04-08T10:00:00Z",
        score=1.2,
        scenario="retrieval",
        retrieval_score=0.85,
    )

    payload = assemble_experience_context(
        runs_root=runs_root,
        candidates_root=candidates_root,
        profile_name="repair",
        project_name="demo_patch",
        objective={"focus": "retrieval"},
        focus="retrieval",
    )

    assert payload["representative_artifacts"]["trace_refs"] == [
        "runs/run-low/tasks/task-a/steps.jsonl"
    ]
    assert payload["representative_artifacts"]["stdout_refs"] == [
        "runs/run-low/tasks/task-a/stdout.txt",
        "runs/run-high/tasks/task-a/stdout.txt",
    ]
    assert payload["representative_artifacts"]["stderr_refs"] == [
        "runs/run-low/tasks/task-a/stderr.txt"
    ]
    assert payload["capability_gaps"][0]["focus"] == "retrieval"
    assert payload["capability_gaps"][0]["gap"] == 0.65
