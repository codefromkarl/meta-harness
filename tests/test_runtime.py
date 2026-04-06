from __future__ import annotations

import json
from pathlib import Path

from meta_harness.runtime import execute_managed_run, execute_task_set, materialize_workspace


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_execute_task_set_resolves_workspace_template_arguments_as_absolute_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    run_dir = Path("runs") / "run-abs"
    repo_root = Path("repo")
    repo_root.mkdir(parents=True)
    (repo_root / "package.json").write_text('{"name":"demo","version":"1.0.0"}', encoding="utf-8")
    (run_dir / "tasks").mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)
    write_json(
        run_dir / "effective_config.json",
        {"runtime": {"workspace": {"source_repo": str(repo_root)}}},
    )

    task_set = tmp_path / "task_set_abs.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "task-abs",
                    "workdir": "${workspace_dir}",
                    "phases": [
                        {
                            "phase": "inspect_arg",
                            "command": [
                                "python",
                                "-c",
                                (
                                    "import sys; "
                                    "from pathlib import Path; "
                                    "assert Path(sys.argv[1]).resolve() == Path.cwd().resolve(); "
                                    "print(Path(sys.argv[1]).resolve())"
                                ),
                                "${workspace_dir}",
                            ],
                        }
                    ],
                }
            ]
        },
    )

    execution_context = materialize_workspace(run_dir=run_dir, effective_config=_read_json(run_dir))
    result = execute_task_set(run_dir, task_set, execution_context=execution_context)

    assert result == {"succeeded": 1, "total": 1}
    task_result = json.loads(
        (run_dir / "tasks" / "task-abs" / "task_result.json").read_text(encoding="utf-8")
    )
    assert task_result["success"] is True


def test_execute_task_set_updates_contextatlas_project_id_from_register_project_output(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-project-id"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True)
    (run_dir / "tasks").mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)
    write_json(
        run_dir / "effective_config.json",
        {"contextatlas": {"project_id": "static-project-id"}},
    )

    task_set = tmp_path / "task_set_project_id.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "task-project-id",
                    "workdir": "${workspace_dir}",
                    "phases": [
                        {
                            "phase": "register_project",
                            "command": [
                                "python",
                                "-c",
                                (
                                    "import sys; "
                                    "print('{\"projectId\":\"dynamic-project-id\"}', file=sys.stderr)"
                                ),
                            ],
                        },
                        {
                            "phase": "inspect_template",
                            "command": [
                                "python",
                                "-c",
                                "print('project=${contextatlas.project_id}')",
                            ],
                        },
                    ],
                }
            ]
        },
    )

    result = execute_task_set(
        run_dir,
        task_set,
        execution_context={
            "run_dir": str(run_dir),
            "workspace_dir": str(workspace_dir),
            "source_repo": str(workspace_dir),
        },
    )

    assert result == {"succeeded": 1, "total": 1}
    assert (
        run_dir / "tasks" / "task-project-id" / "inspect_template.stdout.txt"
    ).read_text(encoding="utf-8").strip() == "project=dynamic-project-id"


def test_execute_task_set_propagates_dynamic_project_id_across_tasks(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-project-id-shared"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True)
    (run_dir / "tasks").mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)
    write_json(run_dir / "effective_config.json", {"contextatlas": {}})

    task_set = tmp_path / "task_set_project_id_shared.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "bootstrap",
                    "workdir": "${workspace_dir}",
                    "phases": [
                        {
                            "phase": "register_project",
                            "command": [
                                "python",
                                "-c",
                                (
                                    "import sys; "
                                    "print('{\"projectId\":\"shared-project-id\"}', file=sys.stderr)"
                                ),
                            ],
                        }
                    ],
                },
                {
                    "task_id": "follow-up",
                    "workdir": "${workspace_dir}",
                    "phases": [
                        {
                            "phase": "inspect_template",
                            "command": [
                                "python",
                                "-c",
                                "print('project=${contextatlas.project_id}')",
                            ],
                        }
                    ],
                },
            ]
        },
    )

    result = execute_task_set(
        run_dir,
        task_set,
        execution_context={
            "run_dir": str(run_dir),
            "workspace_dir": str(workspace_dir),
            "source_repo": str(workspace_dir),
        },
    )

    assert result == {"succeeded": 2, "total": 2}
    assert (
        run_dir / "tasks" / "follow-up" / "inspect_template.stdout.txt"
    ).read_text(encoding="utf-8").strip() == "project=shared-project-id"


def test_execute_managed_run_initializes_workspace_executes_and_scores(
    tmp_path: Path,
) -> None:
    runs_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
    (repo_root / "package.json").write_text('{"name":"demo","version":"1.0.0"}', encoding="utf-8")
    (repo_root / "repo_marker.txt").write_text("from-source-repo", encoding="utf-8")

    task_set = tmp_path / "task_set_managed.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "managed-task",
                    "workdir": "${workspace_dir}",
                    "phases": [
                        {
                            "phase": "prepare",
                            "command": [
                                "python",
                                "-c",
                                (
                                    "from pathlib import Path; "
                                    "print(Path('repo_marker.txt').read_text(encoding='utf-8').strip())"
                                ),
                            ],
                        }
                    ],
                }
            ]
        },
    )

    result = execute_managed_run(
        runs_root=runs_root,
        profile_name="base",
        project_name="demo",
        effective_config={
            "runtime": {"workspace": {"source_repo": str(repo_root)}},
            "evaluation": {"evaluators": ["basic"]},
        },
        task_set_path=task_set,
        candidate_id="candidate-123",
    )

    run_dir = runs_root / result["run_id"]
    run_metadata = json.loads((run_dir / "run_metadata.json").read_text(encoding="utf-8"))
    workspace_artifact = json.loads(
        (run_dir / "artifacts" / "workspace.json").read_text(encoding="utf-8")
    )
    task_result = json.loads(
        (run_dir / "tasks" / "managed-task" / "task_result.json").read_text(encoding="utf-8")
    )

    assert result["task_summary"] == {"succeeded": 1, "total": 1}
    assert result["score"]["correctness"]["task_count"] == 1
    assert result["score"]["composite"] == 1.0
    assert run_metadata["candidate_id"] == "candidate-123"
    assert workspace_artifact["workspace_dir"] == str(run_dir / "workspace")
    assert task_result["success"] is True


def test_execute_managed_run_can_skip_scoring(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
    (repo_root / "repo_marker.txt").write_text("from-source-repo", encoding="utf-8")

    task_set = tmp_path / "task_set_managed_no_score.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "managed-task",
                    "workdir": "${workspace_dir}",
                    "phases": [
                        {
                            "phase": "prepare",
                            "command": ["python", "-c", "print('ok')"],
                        }
                    ],
                }
            ]
        },
    )

    result = execute_managed_run(
        runs_root=runs_root,
        profile_name="base",
        project_name="demo",
        effective_config={
            "runtime": {"workspace": {"source_repo": str(repo_root)}},
            "evaluation": {"evaluators": ["basic"]},
        },
        task_set_path=task_set,
        score_enabled=False,
    )

    run_dir = runs_root / result["run_id"]
    assert result["task_summary"] == {"succeeded": 1, "total": 1}
    assert result["score"] is None
    assert not (run_dir / "score_report.json").exists()
    assert (
        run_dir / "tasks" / "managed-task" / "prepare.stdout.txt"
    ).read_text(encoding="utf-8").strip() == "ok"


def _read_json(run_dir: Path) -> dict:
    return json.loads((run_dir / "effective_config.json").read_text(encoding="utf-8"))
