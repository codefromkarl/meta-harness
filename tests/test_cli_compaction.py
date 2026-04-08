from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from meta_harness.cli import app
import meta_harness.cli as cli_module
import meta_harness.compaction as compaction


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
    created_at: str = "2026-04-06T10:00:00Z",
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
            "created_at": created_at,
        },
    )
    write_json(
        run_dir / "effective_config.json", {"evaluation": {"evaluators": ["basic"]}}
    )
    write_json(
        run_dir / "artifacts" / "workspace.json",
        {
            "source_repo": "/tmp/source",
            "workspace_dir": str(run_dir / "workspace"),
            "patch_applied": False,
            "patch_already_present": False,
            "code_patch_artifact": None,
        },
    )
    (run_dir / "workspace").mkdir(parents=True, exist_ok=True)
    (run_dir / "workspace" / "marker.txt").write_text(run_id, encoding="utf-8")
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
    created_at: str = "2026-04-06T10:00:00Z",
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
            "notes": "",
            "parent_candidate_id": None,
            "code_patch_artifact": None,
            "created_at": created_at,
        },
    )
    write_json(candidate_dir / "effective_config.json", {"budget": {"max_turns": 12}})
    if proposal is not None:
        write_json(candidate_dir / "proposal.json", proposal)


def test_run_compact_removes_workspace_for_non_retained_valid_runs(
    tmp_path: Path,
) -> None:
    runs_root = tmp_path / "runs"

    make_run(
        runs_root,
        "run-old",
        composite=1.0,
        success=True,
        created_at="2026-04-06T09:00:00Z",
    )
    make_run(
        runs_root,
        "run-best",
        composite=3.0,
        success=True,
        created_at="2026-04-06T10:00:00Z",
    )
    make_run(
        runs_root,
        "run-latest",
        composite=2.0,
        success=True,
        created_at="2026-04-06T11:00:00Z",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "compact",
            "--runs-root",
            str(runs_root),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload == {
        "dry_run": False,
        "compacted_runs": [{"run_id": "run-old", "removed": ["workspace"]}],
    }
    assert not (runs_root / "run-old" / "workspace").exists()
    assert (runs_root / "run-best" / "workspace").exists()
    assert (runs_root / "run-latest" / "workspace").exists()


def test_run_compact_supports_dry_run_and_status_filter(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"

    make_candidate(
        candidates_root,
        "cand-old",
        created_at="2026-04-06T09:00:00Z",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
        },
    )
    make_candidate(
        candidates_root,
        "cand-new",
        created_at="2026-04-06T10:00:00Z",
        proposal={
            "strategy": "benchmark_variant",
            "experiment": "benchmark_combo_validation",
            "variant": "retrieval_wide_only",
        },
    )
    make_run(
        runs_root,
        "run-old",
        candidate_id="cand-old",
        composite=2.0,
        success=True,
        created_at="2026-04-06T09:30:00Z",
    )
    make_run(
        runs_root,
        "run-new",
        candidate_id="cand-new",
        composite=2.5,
        success=True,
        created_at="2026-04-06T10:30:00Z",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "compact",
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
            "--dry-run",
            "--status",
            "superseded",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload == {
        "dry_run": True,
        "compacted_runs": [{"run_id": "run-old", "removed": ["workspace"]}],
    }
    assert (runs_root / "run-old" / "workspace").exists()
    assert (runs_root / "run-new" / "workspace").exists()


def test_compact_runs_tolerates_workspace_disappearing_mid_cleanup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runs_root = tmp_path / "runs"
    make_run(
        runs_root,
        "run-old",
        composite=1.0,
        success=True,
        created_at="2026-04-06T09:00:00Z",
    )
    make_run(
        runs_root,
        "run-latest",
        composite=2.0,
        success=True,
        created_at="2026-04-06T10:00:00Z",
    )

    original_rmtree = compaction.shutil.rmtree

    def flaky_rmtree(path: Path, *args, **kwargs) -> None:
        target = Path(path)
        if target.name == "workspace":
            original_rmtree(path, *args, **kwargs)
            raise FileNotFoundError(str(path))
        original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(compaction.shutil, "rmtree", flaky_rmtree)

    payload = compaction.compact_runs(runs_root)

    assert payload == {
        "dry_run": False,
        "compacted_runs": [{"run_id": "run-old", "removed": ["workspace"]}],
    }
    assert not (runs_root / "run-old" / "workspace").exists()


def test_run_compact_uses_platform_include_artifacts_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    calls: list[dict[str, object]] = []

    write_json(
        config_root / "platform.json",
        {"archive": {"compaction": {"include_artifacts": True}}},
    )

    def fake_compact_runs(
        runs_root_arg: Path,
        *,
        candidates_root: Path | None = None,
        dry_run: bool = False,
        experiment: str | None = None,
        benchmark_family: str | None = None,
        status: str | None = None,
        include_artifacts: bool = False,
        compactable_statuses: list[str] | None = None,
        cleanup_auxiliary_dirs: bool = True,
    ) -> dict[str, object]:
        calls.append(
            {
                "runs_root": runs_root_arg,
                "candidates_root": candidates_root,
                "dry_run": dry_run,
                "experiment": experiment,
                "benchmark_family": benchmark_family,
                "status": status,
                "include_artifacts": include_artifacts,
                "compactable_statuses": compactable_statuses,
                "cleanup_auxiliary_dirs": cleanup_auxiliary_dirs,
            }
        )
        return {"dry_run": False, "compacted_runs": []}

    monkeypatch.setattr(cli_module, "compact_runs", fake_compact_runs)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "compact",
            "--config-root",
            str(config_root),
            "--runs-root",
            str(runs_root),
        ],
    )

    assert result.exit_code == 0
    assert calls == [
        {
            "runs_root": runs_root,
            "candidates_root": None,
            "dry_run": False,
            "experiment": None,
            "benchmark_family": None,
            "status": None,
            "include_artifacts": True,
            "compactable_statuses": None,
            "cleanup_auxiliary_dirs": True,
        }
    ]


def test_run_compact_cli_flag_overrides_platform_include_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    calls: list[dict[str, object]] = []

    write_json(
        config_root / "platform.json",
        {"archive": {"compaction": {"include_artifacts": True}}},
    )

    def fake_compact_runs(
        runs_root_arg: Path,
        *,
        candidates_root: Path | None = None,
        dry_run: bool = False,
        experiment: str | None = None,
        benchmark_family: str | None = None,
        status: str | None = None,
        include_artifacts: bool = False,
        compactable_statuses: list[str] | None = None,
        cleanup_auxiliary_dirs: bool = True,
    ) -> dict[str, object]:
        calls.append(
            {
                "runs_root": runs_root_arg,
                "candidates_root": candidates_root,
                "dry_run": dry_run,
                "experiment": experiment,
                "benchmark_family": benchmark_family,
                "status": status,
                "include_artifacts": include_artifacts,
                "compactable_statuses": compactable_statuses,
                "cleanup_auxiliary_dirs": cleanup_auxiliary_dirs,
            }
        )
        return {"dry_run": False, "compacted_runs": []}

    monkeypatch.setattr(cli_module, "compact_runs", fake_compact_runs)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "compact",
            "--config-root",
            str(config_root),
            "--runs-root",
            str(runs_root),
            "--no-include-artifacts",
        ],
    )

    assert result.exit_code == 0
    assert calls == [
        {
            "runs_root": runs_root,
            "candidates_root": None,
            "dry_run": False,
            "experiment": None,
            "benchmark_family": None,
            "status": None,
            "include_artifacts": False,
            "compactable_statuses": None,
            "cleanup_auxiliary_dirs": True,
        }
    ]


def test_run_compact_uses_platform_cleanup_auxiliary_dirs_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    calls: list[dict[str, object]] = []

    write_json(
        config_root / "platform.json",
        {
            "archive": {
                "compaction": {
                    "cleanup_auxiliary_dirs": False,
                }
            }
        },
    )

    def fake_compact_runs(
        runs_root_arg: Path,
        *,
        candidates_root: Path | None = None,
        dry_run: bool = False,
        experiment: str | None = None,
        benchmark_family: str | None = None,
        status: str | None = None,
        include_artifacts: bool = False,
        compactable_statuses: list[str] | None = None,
        cleanup_auxiliary_dirs: bool = True,
    ) -> dict[str, object]:
        calls.append(
            {
                "runs_root": runs_root_arg,
                "candidates_root": candidates_root,
                "dry_run": dry_run,
                "experiment": experiment,
                "benchmark_family": benchmark_family,
                "status": status,
                "include_artifacts": include_artifacts,
                "compactable_statuses": compactable_statuses,
                "cleanup_auxiliary_dirs": cleanup_auxiliary_dirs,
            }
        )
        return {"dry_run": False, "compacted_runs": []}

    monkeypatch.setattr(cli_module, "compact_runs", fake_compact_runs)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "compact",
            "--config-root",
            str(config_root),
            "--runs-root",
            str(runs_root),
        ],
    )

    assert result.exit_code == 0
    assert calls == [
        {
            "runs_root": runs_root,
            "candidates_root": None,
            "dry_run": False,
            "experiment": None,
            "benchmark_family": None,
            "status": None,
            "include_artifacts": False,
            "compactable_statuses": None,
            "cleanup_auxiliary_dirs": False,
        }
    ]


def test_run_compact_uses_platform_compactable_statuses_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    calls: list[dict[str, object]] = []

    write_json(
        config_root / "platform.json",
        {
            "archive": {
                "compaction": {
                    "compactable_statuses": ["superseded", "failed"],
                }
            }
        },
    )

    def fake_compact_runs(
        runs_root_arg: Path,
        *,
        candidates_root: Path | None = None,
        dry_run: bool = False,
        experiment: str | None = None,
        benchmark_family: str | None = None,
        status: str | None = None,
        include_artifacts: bool = False,
        compactable_statuses: list[str] | None = None,
        cleanup_auxiliary_dirs: bool = True,
    ) -> dict[str, object]:
        calls.append(
            {
                "runs_root": runs_root_arg,
                "candidates_root": candidates_root,
                "dry_run": dry_run,
                "experiment": experiment,
                "benchmark_family": benchmark_family,
                "status": status,
                "include_artifacts": include_artifacts,
                "compactable_statuses": compactable_statuses,
                "cleanup_auxiliary_dirs": cleanup_auxiliary_dirs,
            }
        )
        return {"dry_run": False, "compacted_runs": []}

    monkeypatch.setattr(cli_module, "compact_runs", fake_compact_runs)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "compact",
            "--config-root",
            str(config_root),
            "--runs-root",
            str(runs_root),
        ],
    )

    assert result.exit_code == 0
    assert calls == [
        {
            "runs_root": runs_root,
            "candidates_root": None,
            "dry_run": False,
            "experiment": None,
            "benchmark_family": None,
            "status": None,
            "include_artifacts": False,
            "compactable_statuses": ["superseded", "failed"],
            "cleanup_auxiliary_dirs": True,
        }
    ]


def test_run_compact_project_overlay_overrides_platform_compaction_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    calls: list[dict[str, object]] = []

    write_json(
        config_root / "platform.json",
        {
            "archive": {
                "compaction": {
                    "include_artifacts": False,
                    "cleanup_auxiliary_dirs": True,
                    "compactable_statuses": ["superseded"],
                }
            }
        },
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
                "archive": {
                    "compaction": {
                        "include_artifacts": True,
                        "cleanup_auxiliary_dirs": False,
                        "compactable_statuses": ["failed", "partial"],
                    }
                }
            },
        },
    )

    def fake_compact_runs(
        runs_root_arg: Path,
        *,
        candidates_root: Path | None = None,
        dry_run: bool = False,
        experiment: str | None = None,
        benchmark_family: str | None = None,
        status: str | None = None,
        include_artifacts: bool = False,
        compactable_statuses: list[str] | None = None,
        cleanup_auxiliary_dirs: bool = True,
    ) -> dict[str, object]:
        calls.append(
            {
                "runs_root": runs_root_arg,
                "candidates_root": candidates_root,
                "dry_run": dry_run,
                "experiment": experiment,
                "benchmark_family": benchmark_family,
                "status": status,
                "include_artifacts": include_artifacts,
                "compactable_statuses": compactable_statuses,
                "cleanup_auxiliary_dirs": cleanup_auxiliary_dirs,
            }
        )
        return {"dry_run": False, "compacted_runs": []}

    monkeypatch.setattr(cli_module, "compact_runs", fake_compact_runs)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "compact",
            "--config-root",
            str(config_root),
            "--project",
            "demo",
            "--runs-root",
            str(runs_root),
        ],
    )

    assert result.exit_code == 0
    assert calls == [
        {
            "runs_root": runs_root,
            "candidates_root": None,
            "dry_run": False,
            "experiment": None,
            "benchmark_family": None,
            "status": None,
            "include_artifacts": True,
            "compactable_statuses": ["failed", "partial"],
            "cleanup_auxiliary_dirs": False,
        }
    ]
