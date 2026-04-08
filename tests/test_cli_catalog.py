from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from meta_harness.cli import app
import meta_harness.catalog as catalog_module


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def make_run(
    runs_root: Path,
    run_id: str,
    *,
    profile: str = "base",
    project: str = "demo",
    candidate_id: str | None = None,
    composite: float | None = None,
    success: bool | None = None,
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
            "candidate_id": candidate_id,
            "created_at": "2026-04-06T10:00:00Z",
        },
    )
    write_json(
        run_dir / "effective_config.json", {"evaluation": {"evaluators": ["basic"]}}
    )
    if composite is not None:
        write_json(
            run_dir / "score_report.json",
            {
                "correctness": {"task_count": 1, "completed_steps": 2},
                "cost": {"trace_event_count": 2},
                "maintainability": {},
                "architecture": {},
                "human_collaboration": {"manual_interventions": 0},
                "composite": composite,
            },
        )
    if success is not None:
        write_json(
            task_dir / "task_result.json",
            {
                "task_id": "task-a",
                "success": success,
                "completed_phases": 2 if success else 1,
                "failed_phase": None if success else "build",
            },
        )


def make_candidate(
    candidates_root: Path,
    candidate_id: str,
    *,
    profile: str = "base",
    project: str = "demo",
    notes: str = "",
    proposal: dict | None = None,
) -> None:
    candidate_dir = candidates_root / candidate_id
    candidate_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        candidate_dir / "candidate.json",
        {
            "candidate_id": candidate_id,
            "profile": profile,
            "project": project,
            "notes": notes,
            "parent_candidate_id": None,
            "code_patch_artifact": None,
        },
    )
    write_json(candidate_dir / "effective_config.json", {"budget": {"max_turns": 12}})
    if proposal is not None:
        write_json(candidate_dir / "proposal.json", proposal)


def test_run_catalog_enriches_benchmark_experiment_and_latest_valid_views(
    tmp_path: Path,
) -> None:
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"

    make_candidate(
        candidates_root,
        "cand-old",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_stability_penalty_calibration",
            "variant": "penalty_default",
            "variant_type": "parameter",
        },
    )
    make_candidate(
        candidates_root,
        "cand-new",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_stability_penalty_calibration",
            "variant": "penalty_balanced",
            "variant_type": "parameter",
        },
    )
    make_run(runs_root, "run-old", candidate_id="cand-old", composite=2.0, success=True)
    make_run(runs_root, "run-new", candidate_id="cand-new", composite=2.5, success=True)
    write_json(
        runs_root / "run-old" / "run_metadata.json",
        {
            "run_id": "run-old",
            "profile": "base",
            "project": "demo",
            "candidate_id": "cand-old",
            "created_at": "2026-04-06T09:00:00Z",
        },
    )
    write_json(
        runs_root / "run-new" / "run_metadata.json",
        {
            "run_id": "run-new",
            "profile": "base",
            "project": "demo",
            "candidate_id": "cand-new",
            "created_at": "2026-04-06T10:00:00Z",
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "index",
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    by_id = {item["run_id"]: item for item in payload["runs"]}
    assert (
        by_id["run-old"]["experiment"] == "benchmark_stability_penalty_calibration"
    )
    assert by_id["run-old"]["benchmark_family"] == "stability_penalty_calibration"
    assert by_id["run-old"]["variant"] == "penalty_default"
    assert payload["latest_valid_by_experiment"] == {
        "benchmark_stability_penalty_calibration": "run-new"
    }


def test_candidate_catalog_enriches_benchmark_family_and_latest_champion_views(
    tmp_path: Path,
) -> None:
    candidates_root = tmp_path / "candidates"
    make_candidate(
        candidates_root,
        "cand-a",
        notes="benchmark variant",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
            "variant_type": "parameter",
        },
    )
    make_candidate(
        candidates_root,
        "cand-b",
        notes="benchmark variant",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_stability_penalty_calibration",
            "variant": "penalty_balanced",
            "variant_type": "parameter",
        },
    )
    write_json(candidates_root / "champions.json", {"base:demo": "cand-b"})

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["candidate", "index", "--candidates-root", str(candidates_root)],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    by_id = {item["candidate_id"]: item for item in payload["candidates"]}
    assert by_id["cand-a"]["experiment"] == "benchmark_combo_validation"
    assert by_id["cand-a"]["benchmark_family"] == "combo_validation"
    assert by_id["cand-a"]["variant"] == "retrieval_wide_only"
    assert payload["latest_champion_by_project"] == {"base:demo": "cand-b"}


def test_catalog_marks_superseded_candidates_and_links_runs(
    tmp_path: Path,
) -> None:
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"

    make_candidate(
        candidates_root,
        "cand-old",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
            "variant_type": "parameter",
        },
    )
    make_candidate(
        candidates_root,
        "cand-new",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
            "variant_type": "parameter",
        },
    )
    write_json(
        candidates_root / "cand-old" / "candidate.json",
        {
            "candidate_id": "cand-old",
            "profile": "base",
            "project": "demo",
            "notes": "older benchmark variant",
            "parent_candidate_id": None,
            "code_patch_artifact": None,
            "created_at": "2026-04-06T09:00:00Z",
        },
    )
    write_json(
        candidates_root / "cand-new" / "candidate.json",
        {
            "candidate_id": "cand-new",
            "profile": "base",
            "project": "demo",
            "notes": "newer benchmark variant",
            "parent_candidate_id": None,
            "code_patch_artifact": None,
            "created_at": "2026-04-06T10:00:00Z",
        },
    )

    make_run(runs_root, "run-old", candidate_id="cand-old", composite=2.0, success=True)
    make_run(runs_root, "run-new", candidate_id="cand-new", composite=2.5, success=True)
    write_json(
        runs_root / "run-old" / "run_metadata.json",
        {
            "run_id": "run-old",
            "profile": "base",
            "project": "demo",
            "candidate_id": "cand-old",
            "created_at": "2026-04-06T09:30:00Z",
        },
    )
    write_json(
        runs_root / "run-new" / "run_metadata.json",
        {
            "run_id": "run-new",
            "profile": "base",
            "project": "demo",
            "candidate_id": "cand-new",
            "created_at": "2026-04-06T10:30:00Z",
        },
    )

    runner = CliRunner()
    run_result = runner.invoke(
        app,
        [
            "run",
            "index",
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
        ],
    )
    candidate_result = runner.invoke(
        app,
        [
            "candidate",
            "index",
            "--candidates-root",
            str(candidates_root),
            "--runs-root",
            str(runs_root),
        ],
    )

    assert run_result.exit_code == 0
    assert candidate_result.exit_code == 0
    run_payload = json.loads(run_result.stdout)
    candidate_payload = json.loads(candidate_result.stdout)
    run_by_id = {item["run_id"]: item for item in run_payload["runs"]}
    candidate_by_id = {
        item["candidate_id"]: item for item in candidate_payload["candidates"]
    }

    assert run_by_id["run-old"]["status"] == "superseded"
    assert run_by_id["run-old"]["superseded_by_run_id"] == "run-new"
    assert run_payload["current_recommended_run_by_experiment"] == {
        "benchmark_combo_validation": "run-new"
    }
    assert candidate_by_id["cand-old"]["status"] == "superseded"
    assert candidate_by_id["cand-old"]["superseded_by_candidate_id"] == "cand-new"
    assert candidate_by_id["cand-old"]["run_ids"] == ["run-old"]
    assert candidate_by_id["cand-new"]["run_ids"] == ["run-new"]
    assert candidate_payload["current_recommended_candidate_by_experiment"] == {
        "benchmark_combo_validation": "cand-new"
    }


def test_run_current_and_archive_list_views(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    make_candidate(
        candidates_root,
        "cand-old",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
        },
    )
    make_candidate(
        candidates_root,
        "cand-new",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
        },
    )
    write_json(
        candidates_root / "cand-old" / "candidate.json",
        {
            "candidate_id": "cand-old",
            "profile": "base",
            "project": "demo",
            "notes": "older",
            "parent_candidate_id": None,
            "code_patch_artifact": None,
            "created_at": "2026-04-06T09:00:00Z",
        },
    )
    write_json(
        candidates_root / "cand-new" / "candidate.json",
        {
            "candidate_id": "cand-new",
            "profile": "base",
            "project": "demo",
            "notes": "newer",
            "parent_candidate_id": None,
            "code_patch_artifact": None,
            "created_at": "2026-04-06T10:00:00Z",
        },
    )
    make_run(runs_root, "run-old", candidate_id="cand-old", composite=2.0, success=True)
    make_run(runs_root, "run-new", candidate_id="cand-new", composite=2.5, success=True)
    make_run(runs_root, "run-failed", candidate_id=None, composite=None, success=False)
    write_json(
        runs_root / "run-old" / "run_metadata.json",
        {
            "run_id": "run-old",
            "profile": "base",
            "project": "demo",
            "candidate_id": "cand-old",
            "created_at": "2026-04-06T09:30:00Z",
        },
    )
    write_json(
        runs_root / "run-new" / "run_metadata.json",
        {
            "run_id": "run-new",
            "profile": "base",
            "project": "demo",
            "candidate_id": "cand-new",
            "created_at": "2026-04-06T10:30:00Z",
        },
    )

    runner = CliRunner()
    current_result = runner.invoke(
        app,
        [
            "run",
            "current",
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
        ],
    )
    archive_result = runner.invoke(
        app,
        [
            "run",
            "archive-list",
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
        ],
    )

    assert current_result.exit_code == 0
    assert archive_result.exit_code == 0
    current_payload = json.loads(current_result.stdout)
    archive_payload = json.loads(archive_result.stdout)
    assert current_payload == {
        "current_recommended_run_by_experiment": {
            "benchmark_combo_validation": "run-new"
        }
    }
    assert archive_payload["superseded_runs"] == ["run-old"]
    assert archive_payload["failed_runs"] == ["run-failed"]


def test_candidate_current_and_archive_list_views(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    make_candidate(
        candidates_root,
        "cand-old",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
        },
    )
    make_candidate(
        candidates_root,
        "cand-new",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
        },
    )
    write_json(
        candidates_root / "cand-old" / "candidate.json",
        {
            "candidate_id": "cand-old",
            "profile": "base",
            "project": "demo",
            "notes": "older",
            "parent_candidate_id": None,
            "code_patch_artifact": None,
            "created_at": "2026-04-06T09:00:00Z",
        },
    )
    write_json(
        candidates_root / "cand-new" / "candidate.json",
        {
            "candidate_id": "cand-new",
            "profile": "base",
            "project": "demo",
            "notes": "newer",
            "parent_candidate_id": None,
            "code_patch_artifact": None,
            "created_at": "2026-04-06T10:00:00Z",
        },
    )
    make_run(runs_root, "run-new", candidate_id="cand-new", composite=2.5, success=True)

    runner = CliRunner()
    current_result = runner.invoke(
        app,
        [
            "candidate",
            "current",
            "--candidates-root",
            str(candidates_root),
            "--runs-root",
            str(runs_root),
        ],
    )
    archive_result = runner.invoke(
        app,
        [
            "candidate",
            "archive-list",
            "--candidates-root",
            str(candidates_root),
            "--runs-root",
            str(runs_root),
        ],
    )

    assert current_result.exit_code == 0
    assert archive_result.exit_code == 0
    current_payload = json.loads(current_result.stdout)
    archive_payload = json.loads(archive_result.stdout)
    assert current_payload == {
        "current_recommended_candidate_by_experiment": {
            "benchmark_combo_validation": "cand-new"
        }
    }
    assert archive_payload["superseded_candidates"] == ["cand-old"]


def test_run_archive_and_prune_commands_move_and_delete_safe_targets(
    tmp_path: Path,
) -> None:
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    archive_root = tmp_path / "archive"

    make_candidate(
        candidates_root,
        "cand-old",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
        },
    )
    make_candidate(
        candidates_root,
        "cand-new",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
        },
    )
    write_json(
        candidates_root / "cand-old" / "candidate.json",
        {
            "candidate_id": "cand-old",
            "profile": "base",
            "project": "demo",
            "notes": "older",
            "parent_candidate_id": None,
            "code_patch_artifact": None,
            "created_at": "2026-04-06T09:00:00Z",
        },
    )
    write_json(
        candidates_root / "cand-new" / "candidate.json",
        {
            "candidate_id": "cand-new",
            "profile": "base",
            "project": "demo",
            "notes": "newer",
            "parent_candidate_id": None,
            "code_patch_artifact": None,
            "created_at": "2026-04-06T10:00:00Z",
        },
    )
    make_run(runs_root, "run-old", candidate_id="cand-old", composite=2.0, success=True)
    make_run(runs_root, "run-new", candidate_id="cand-new", composite=2.5, success=True)
    make_run(runs_root, "run-failed", candidate_id=None, composite=None, success=False)
    write_json(
        runs_root / "run-old" / "run_metadata.json",
        {
            "run_id": "run-old",
            "profile": "base",
            "project": "demo",
            "candidate_id": "cand-old",
            "created_at": "2026-04-06T09:30:00Z",
        },
    )
    write_json(
        runs_root / "run-new" / "run_metadata.json",
        {
            "run_id": "run-new",
            "profile": "base",
            "project": "demo",
            "candidate_id": "cand-new",
            "created_at": "2026-04-06T10:30:00Z",
        },
    )

    runner = CliRunner()
    archive_result = runner.invoke(
        app,
        [
            "run",
            "archive",
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
            "--archive-root",
            str(archive_root),
        ],
    )
    prune_result = runner.invoke(
        app,
        [
            "run",
            "prune",
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
        ],
    )

    assert archive_result.exit_code == 0
    assert prune_result.exit_code == 0
    archive_payload = json.loads(archive_result.stdout)
    prune_payload = json.loads(prune_result.stdout)
    assert archive_payload["archived_runs"] == ["run-old", "run-failed"]
    assert prune_payload["deleted_runs"] == []
    assert not (runs_root / "run-old").exists()
    assert not (runs_root / "run-failed").exists()
    assert (runs_root / "run-new").exists()
    assert (archive_root / "runs" / "run-old").exists()
    assert (archive_root / "runs" / "run-failed").exists()


def test_candidate_archive_and_prune_commands_move_and_delete_safe_targets(
    tmp_path: Path,
) -> None:
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    archive_root = tmp_path / "archive"

    make_candidate(
        candidates_root,
        "cand-old",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
        },
    )
    make_candidate(
        candidates_root,
        "cand-new",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
        },
    )
    write_json(
        candidates_root / "cand-old" / "candidate.json",
        {
            "candidate_id": "cand-old",
            "profile": "base",
            "project": "demo",
            "notes": "older",
            "parent_candidate_id": None,
            "code_patch_artifact": None,
            "created_at": "2026-04-06T09:00:00Z",
        },
    )
    write_json(
        candidates_root / "cand-new" / "candidate.json",
        {
            "candidate_id": "cand-new",
            "profile": "base",
            "project": "demo",
            "notes": "newer",
            "parent_candidate_id": None,
            "code_patch_artifact": None,
            "created_at": "2026-04-06T10:00:00Z",
        },
    )
    make_run(runs_root, "run-new", candidate_id="cand-new", composite=2.5, success=True)

    runner = CliRunner()
    archive_result = runner.invoke(
        app,
        [
            "candidate",
            "archive",
            "--candidates-root",
            str(candidates_root),
            "--runs-root",
            str(runs_root),
            "--archive-root",
            str(archive_root),
        ],
    )
    prune_result = runner.invoke(
        app,
        [
            "candidate",
            "prune",
            "--candidates-root",
            str(candidates_root),
            "--runs-root",
            str(runs_root),
        ],
    )

    assert archive_result.exit_code == 0
    assert prune_result.exit_code == 0
    archive_payload = json.loads(archive_result.stdout)
    prune_payload = json.loads(prune_result.stdout)
    assert archive_payload["archived_candidates"] == ["cand-old"]
    assert prune_payload["deleted_candidates"] == []
    assert not (candidates_root / "cand-old").exists()
    assert (candidates_root / "cand-new").exists()
    assert (archive_root / "candidates" / "cand-old").exists()


def test_run_archive_supports_dry_run_and_filters(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    archive_root = tmp_path / "archive"

    make_candidate(
        candidates_root,
        "cand-old",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
        },
    )
    make_candidate(
        candidates_root,
        "cand-new",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
        },
    )
    write_json(
        candidates_root / "cand-old" / "candidate.json",
        {
            "candidate_id": "cand-old",
            "profile": "base",
            "project": "demo",
            "notes": "older",
            "parent_candidate_id": None,
            "code_patch_artifact": None,
            "created_at": "2026-04-06T09:00:00Z",
        },
    )
    write_json(
        candidates_root / "cand-new" / "candidate.json",
        {
            "candidate_id": "cand-new",
            "profile": "base",
            "project": "demo",
            "notes": "newer",
            "parent_candidate_id": None,
            "code_patch_artifact": None,
            "created_at": "2026-04-06T10:00:00Z",
        },
    )
    make_run(runs_root, "run-old", candidate_id="cand-old", composite=2.0, success=True)
    make_run(runs_root, "run-new", candidate_id="cand-new", composite=2.5, success=True)
    make_run(runs_root, "run-failed", candidate_id=None, composite=None, success=False)
    write_json(
        runs_root / "run-old" / "run_metadata.json",
        {
            "run_id": "run-old",
            "profile": "base",
            "project": "demo",
            "candidate_id": "cand-old",
            "created_at": "2026-04-06T09:30:00Z",
        },
    )
    write_json(
        runs_root / "run-new" / "run_metadata.json",
        {
            "run_id": "run-new",
            "profile": "base",
            "project": "demo",
            "candidate_id": "cand-new",
            "created_at": "2026-04-06T10:30:00Z",
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "archive",
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
            "--archive-root",
            str(archive_root),
            "--dry-run",
            "--experiment",
            "benchmark_combo_validation",
            "--status",
            "superseded",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["archived_runs"] == ["run-old"]
    assert (runs_root / "run-old").exists()
    assert not (archive_root / "runs" / "run-old").exists()


def test_candidate_prune_supports_dry_run_and_family_filter(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"

    make_candidate(
        candidates_root,
        "cand-old",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
        },
    )
    make_candidate(
        candidates_root,
        "cand-new",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
        },
    )
    write_json(
        candidates_root / "cand-old" / "candidate.json",
        {
            "candidate_id": "cand-old",
            "profile": "base",
            "project": "demo",
            "notes": "older",
            "parent_candidate_id": None,
            "code_patch_artifact": None,
            "created_at": "2026-04-06T09:00:00Z",
        },
    )
    write_json(
        candidates_root / "cand-new" / "candidate.json",
        {
            "candidate_id": "cand-new",
            "profile": "base",
            "project": "demo",
            "notes": "newer",
            "parent_candidate_id": None,
            "code_patch_artifact": None,
            "created_at": "2026-04-06T10:00:00Z",
        },
    )
    make_run(runs_root, "run-new", candidate_id="cand-new", composite=2.5, success=True)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "candidate",
            "prune",
            "--candidates-root",
            str(candidates_root),
            "--runs-root",
            str(runs_root),
            "--dry-run",
            "--benchmark-family",
            "combo_validation",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["deleted_candidates"] == ["cand-old"]
    assert (candidates_root / "cand-old").exists()


def test_run_archive_writes_manifest_and_cleanup_log(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    archive_root = tmp_path / "archive"

    make_candidate(
        candidates_root,
        "cand-old",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
        },
    )
    make_candidate(
        candidates_root,
        "cand-new",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
        },
    )
    write_json(
        candidates_root / "cand-old" / "candidate.json",
        {
            "candidate_id": "cand-old",
            "profile": "base",
            "project": "demo",
            "notes": "older",
            "parent_candidate_id": None,
            "code_patch_artifact": None,
            "created_at": "2026-04-06T09:00:00Z",
        },
    )
    write_json(
        candidates_root / "cand-new" / "candidate.json",
        {
            "candidate_id": "cand-new",
            "profile": "base",
            "project": "demo",
            "notes": "newer",
            "parent_candidate_id": None,
            "code_patch_artifact": None,
            "created_at": "2026-04-06T10:00:00Z",
        },
    )
    make_run(runs_root, "run-old", candidate_id="cand-old", composite=2.0, success=True)
    make_run(runs_root, "run-new", candidate_id="cand-new", composite=2.5, success=True)
    make_run(runs_root, "run-failed", candidate_id=None, composite=None, success=False)
    write_json(
        runs_root / "run-old" / "run_metadata.json",
        {
            "run_id": "run-old",
            "profile": "base",
            "project": "demo",
            "candidate_id": "cand-old",
            "created_at": "2026-04-06T09:30:00Z",
        },
    )
    write_json(
        runs_root / "run-new" / "run_metadata.json",
        {
            "run_id": "run-new",
            "profile": "base",
            "project": "demo",
            "candidate_id": "cand-new",
            "created_at": "2026-04-06T10:30:00Z",
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "archive",
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
            "--archive-root",
            str(archive_root),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    manifest_path = archive_root / "cleanup_logs" / payload["manifest_id"]
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    log_path = archive_root / "cleanup_logs" / "cleanup_log.jsonl"
    log_lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert manifest_payload["operation"] == "run.archive"
    assert manifest_payload["target_type"] == "run"
    assert manifest_payload["targets"] == ["run-old", "run-failed"]
    assert manifest_payload["source_root"] == str(runs_root)
    assert manifest_payload["archive_root"] == str(archive_root)
    assert manifest_payload["filters"] == {
        "experiment": None,
        "benchmark_family": None,
        "status": None,
    }
    assert "timestamp" in manifest_payload
    assert manifest_payload["target_records"] == [
        {
            "target_id": "run-old",
            "target_type": "run",
            "status": "superseded",
            "experiment": "benchmark_combo_validation",
            "benchmark_family": "combo_validation",
            "variant": "retrieval_wide_only",
            "source_path": str(runs_root / "run-old"),
            "archive_path": str(archive_root / "runs" / "run-old"),
        },
        {
            "target_id": "run-failed",
            "target_type": "run",
            "status": "failed",
            "experiment": None,
            "benchmark_family": None,
            "variant": None,
            "source_path": str(runs_root / "run-failed"),
            "archive_path": str(archive_root / "runs" / "run-failed"),
        },
    ]
    assert len(log_lines) == 1


def test_candidate_prune_writes_manifest_and_cleanup_log(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    archive_root = tmp_path / "archive"

    make_candidate(
        candidates_root,
        "cand-old",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
        },
    )
    make_candidate(
        candidates_root,
        "cand-new",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
        },
    )
    write_json(
        candidates_root / "cand-old" / "candidate.json",
        {
            "candidate_id": "cand-old",
            "profile": "base",
            "project": "demo",
            "notes": "older",
            "parent_candidate_id": None,
            "code_patch_artifact": None,
            "created_at": "2026-04-06T09:00:00Z",
        },
    )
    write_json(
        candidates_root / "cand-new" / "candidate.json",
        {
            "candidate_id": "cand-new",
            "profile": "base",
            "project": "demo",
            "notes": "newer",
            "parent_candidate_id": None,
            "code_patch_artifact": None,
            "created_at": "2026-04-06T10:00:00Z",
        },
    )
    make_run(runs_root, "run-new", candidate_id="cand-new", composite=2.5, success=True)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "candidate",
            "prune",
            "--candidates-root",
            str(candidates_root),
            "--runs-root",
            str(runs_root),
            "--archive-root",
            str(archive_root),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    manifest_path = archive_root / "cleanup_logs" / payload["manifest_id"]
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    log_path = archive_root / "cleanup_logs" / "cleanup_log.jsonl"
    log_lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert manifest_payload["operation"] == "candidate.prune"
    assert manifest_payload["target_type"] == "candidate"
    assert manifest_payload["targets"] == ["cand-old"]
    assert manifest_payload["source_root"] == str(candidates_root)
    assert manifest_payload["archive_root"] == str(archive_root)
    assert manifest_payload["filters"] == {
        "experiment": None,
        "benchmark_family": None,
        "status": None,
    }
    assert "timestamp" in manifest_payload
    assert manifest_payload["target_records"] == [
        {
            "target_id": "cand-old",
            "target_type": "candidate",
            "status": "superseded",
            "experiment": "benchmark_combo_validation",
            "benchmark_family": "combo_validation",
            "variant": "retrieval_wide_only",
            "source_path": str(candidates_root / "cand-old"),
            "archive_path": None,
        }
    ]
    assert len(log_lines) == 1


def test_cleanup_logs_retention_keeps_only_latest_manifests(
    tmp_path: Path,
    monkeypatch,
) -> None:
    archive_root = tmp_path / "archive"
    source_root = tmp_path / "runs"
    source_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(catalog_module, "_DEFAULT_CLEANUP_LOG_RETENTION", 3)

    manifest_ids = []
    for index in range(5):
        manifest_ids.append(
            catalog_module._write_cleanup_log(
                archive_root,
                operation="run.prune",
                targets=[f"run-{index}"],
                target_records=[
                    {
                        "target_id": f"run-{index}",
                        "target_type": "run",
                        "status": "failed",
                        "experiment": None,
                        "benchmark_family": None,
                        "variant": None,
                        "source_path": str(source_root / f"run-{index}"),
                        "archive_path": None,
                    }
                ],
                dry_run=False,
                target_type="run",
                source_root=source_root,
                filters={
                    "experiment": None,
                    "benchmark_family": None,
                    "status": None,
                },
            )
        )

    logs_root = archive_root / "cleanup_logs"
    remaining_manifests = sorted(
        path.name
        for path in logs_root.glob("*.json")
        if path.name != "cleanup_log.jsonl"
    )
    log_lines = (logs_root / "cleanup_log.jsonl").read_text(encoding="utf-8").strip().splitlines()
    logged_manifest_ids = [json.loads(line)["manifest_id"] for line in log_lines]

    assert len(log_lines) == 3
    assert logged_manifest_ids == manifest_ids[-3:]
    assert remaining_manifests == sorted(manifest_ids[-3:])
    for manifest_id in manifest_ids[:2]:
        assert not (logs_root / manifest_id).exists()


def test_write_cleanup_log_respects_explicit_retention_override(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    source_root = tmp_path / "runs"
    source_root.mkdir(parents=True, exist_ok=True)

    manifest_ids = []
    for index in range(4):
        manifest_ids.append(
            catalog_module._write_cleanup_log(
                archive_root,
                operation="run.prune",
                targets=[f"run-{index}"],
                target_records=[
                    {
                        "target_id": f"run-{index}",
                        "target_type": "run",
                        "status": "failed",
                        "experiment": None,
                        "benchmark_family": None,
                        "variant": None,
                        "source_path": str(source_root / f"run-{index}"),
                        "archive_path": None,
                    }
                ],
                dry_run=False,
                target_type="run",
                source_root=source_root,
                filters={
                    "experiment": None,
                    "benchmark_family": None,
                    "status": None,
                },
                retention=2,
            )
        )

    logs_root = archive_root / "cleanup_logs"
    log_lines = (logs_root / "cleanup_log.jsonl").read_text(encoding="utf-8").strip().splitlines()
    logged_manifest_ids = [json.loads(line)["manifest_id"] for line in log_lines]
    remaining_manifests = sorted(path.name for path in logs_root.glob("*.json"))

    assert logged_manifest_ids == manifest_ids[-2:]
    assert remaining_manifests == sorted(manifest_ids[-2:])


def test_run_archive_uses_platform_cleanup_log_retention_from_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    archive_root = tmp_path / "archive"

    write_json(
        config_root / "platform.json",
        {"archive": {"cleanup_logs": {"retention": 7}}},
    )
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )
    make_candidate(
        candidates_root,
        "cand-old",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
        },
    )
    make_candidate(
        candidates_root,
        "cand-new",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
        },
    )
    write_json(
        candidates_root / "cand-old" / "candidate.json",
        {
            "candidate_id": "cand-old",
            "profile": "base",
            "project": "demo",
            "notes": "older",
            "parent_candidate_id": None,
            "code_patch_artifact": None,
            "created_at": "2026-04-06T09:00:00Z",
        },
    )
    write_json(
        candidates_root / "cand-new" / "candidate.json",
        {
            "candidate_id": "cand-new",
            "profile": "base",
            "project": "demo",
            "notes": "newer",
            "parent_candidate_id": None,
            "code_patch_artifact": None,
            "created_at": "2026-04-06T10:00:00Z",
        },
    )
    make_run(runs_root, "run-old", candidate_id="cand-old", composite=2.0, success=True)
    make_run(runs_root, "run-new", candidate_id="cand-new", composite=2.5, success=True)
    write_json(
        runs_root / "run-old" / "run_metadata.json",
        {
            "run_id": "run-old",
            "profile": "base",
            "project": "demo",
            "candidate_id": "cand-old",
            "created_at": "2026-04-06T09:30:00Z",
        },
    )
    write_json(
        runs_root / "run-new" / "run_metadata.json",
        {
            "run_id": "run-new",
            "profile": "base",
            "project": "demo",
            "candidate_id": "cand-new",
            "created_at": "2026-04-06T10:30:00Z",
        },
    )

    calls: list[dict[str, object]] = []
    original_archive_runs = catalog_module.archive_runs

    def tracking_archive_runs(*args, **kwargs):
        calls.append(kwargs)
        return original_archive_runs(*args, **kwargs)

    monkeypatch.setattr("meta_harness.cli.archive_runs", tracking_archive_runs)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "archive",
            "--config-root",
            str(config_root),
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
            "--archive-root",
            str(archive_root),
        ],
    )

    assert result.exit_code == 0
    assert calls[0]["cleanup_log_retention"] == 7


def test_run_archive_project_overlay_overrides_cleanup_log_retention(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    archive_root = tmp_path / "archive"

    write_json(
        config_root / "platform.json",
        {"archive": {"cleanup_logs": {"retention": 7}}},
    )
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {
            "workflow": "base",
            "overrides": {
                "archive": {"cleanup_logs": {"retention": 3}},
            },
        },
    )
    make_candidate(
        candidates_root,
        "cand-old",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
        },
    )
    make_candidate(
        candidates_root,
        "cand-new",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
        },
    )
    write_json(
        candidates_root / "cand-old" / "candidate.json",
        {
            "candidate_id": "cand-old",
            "profile": "base",
            "project": "demo",
            "notes": "older",
            "parent_candidate_id": None,
            "code_patch_artifact": None,
            "created_at": "2026-04-06T09:00:00Z",
        },
    )
    write_json(
        candidates_root / "cand-new" / "candidate.json",
        {
            "candidate_id": "cand-new",
            "profile": "base",
            "project": "demo",
            "notes": "newer",
            "parent_candidate_id": None,
            "code_patch_artifact": None,
            "created_at": "2026-04-06T10:00:00Z",
        },
    )
    make_run(runs_root, "run-old", candidate_id="cand-old", composite=2.0, success=True)
    make_run(runs_root, "run-new", candidate_id="cand-new", composite=2.5, success=True)
    write_json(
        runs_root / "run-old" / "run_metadata.json",
        {
            "run_id": "run-old",
            "profile": "base",
            "project": "demo",
            "candidate_id": "cand-old",
            "created_at": "2026-04-06T09:30:00Z",
        },
    )
    write_json(
        runs_root / "run-new" / "run_metadata.json",
        {
            "run_id": "run-new",
            "profile": "base",
            "project": "demo",
            "candidate_id": "cand-new",
            "created_at": "2026-04-06T10:30:00Z",
        },
    )

    calls: list[dict[str, object]] = []
    original_archive_runs = catalog_module.archive_runs

    def tracking_archive_runs(*args, **kwargs):
        calls.append(kwargs)
        return original_archive_runs(*args, **kwargs)

    monkeypatch.setattr("meta_harness.cli.archive_runs", tracking_archive_runs)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "archive",
            "--config-root",
            str(config_root),
            "--project",
            "demo",
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
            "--archive-root",
            str(archive_root),
        ],
    )

    assert result.exit_code == 0
    assert calls[0]["cleanup_log_retention"] == 3


def test_run_catalog_builds_classified_index(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    make_run(runs_root, "run-valid", composite=2.5, success=True)
    make_run(runs_root, "run-failed", composite=None, success=False)
    make_run(runs_root, "run-partial", composite=1.0, success=False)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["run", "index", "--runs-root", str(runs_root)],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["summary"] == {
        "total_runs": 3,
        "valid_runs": 1,
        "failed_runs": 1,
        "partial_runs": 1,
    }
    by_id = {item["run_id"]: item for item in payload["runs"]}
    assert by_id["run-valid"]["status"] == "valid"
    assert by_id["run-valid"]["tags"] == ["scored", "successful"]
    assert by_id["run-failed"]["status"] == "failed"
    assert by_id["run-partial"]["status"] == "partial"
    index_payload = json.loads((runs_root / "_index.json").read_text(encoding="utf-8"))
    assert index_payload["summary"]["valid_runs"] == 1


def test_candidate_catalog_builds_classified_index(tmp_path: Path) -> None:
    candidates_root = tmp_path / "candidates"
    make_candidate(
        candidates_root,
        "cand-a",
        notes="benchmark variant",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "demo",
            "variant": "wide",
        },
    )
    make_candidate(candidates_root, "cand-b", notes="manual exploration")
    write_json(candidates_root / "champions.json", {"base:demo": "cand-a"})

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["candidate", "index", "--candidates-root", str(candidates_root)],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["summary"] == {
        "total_candidates": 2,
        "champion_candidates": 1,
        "benchmark_candidates": 1,
    }
    by_id = {item["candidate_id"]: item for item in payload["candidates"]}
    assert by_id["cand-a"]["status"] == "champion"
    assert by_id["cand-a"]["tags"] == ["benchmark", "champion"]
    assert by_id["cand-b"]["status"] == "exploratory"
    index_payload = json.loads(
        (candidates_root / "_index.json").read_text(encoding="utf-8")
    )
    assert index_payload["summary"]["champion_candidates"] == 1
