from __future__ import annotations

import json
from pathlib import Path
import subprocess

import meta_harness.runtime as runtime_module
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


def test_materialize_workspace_rejects_source_repo_that_contains_run_dir(
    tmp_path: Path,
) -> None:
    source_root = tmp_path
    run_dir = source_root / "runs" / "run-recursive"
    (run_dir / "tasks").mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    try:
        materialize_workspace(
            run_dir=run_dir,
            effective_config={
                "runtime": {"workspace": {"source_repo": str(source_root)}}
            },
        )
    except ValueError as exc:
        assert "must not contain the destination" in str(exc)
    else:
        raise AssertionError("expected recursive source_repo guardrail to reject ancestor source")


def test_materialize_workspace_ignores_runtime_artifact_directories_by_default(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "src.txt").write_text("ok", encoding="utf-8")
    (repo_root / "runs").mkdir()
    (repo_root / "candidates").mkdir()
    (repo_root / "archive").mkdir()
    (repo_root / "reports").mkdir()
    (repo_root / "runs" / "nested.txt").write_text("skip", encoding="utf-8")
    (repo_root / "reports" / "report.txt").write_text("skip", encoding="utf-8")

    run_dir = tmp_path / "runtime" / "run-artifact-ignore"
    (run_dir / "tasks").mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    execution_context = materialize_workspace(
        run_dir=run_dir,
        effective_config={
            "runtime": {"workspace": {"source_repo": str(repo_root)}}
        },
    )

    workspace_dir = run_dir / "workspace"
    assert execution_context is not None
    assert (workspace_dir / "src.txt").read_text(encoding="utf-8") == "ok"
    assert not (workspace_dir / "runs").exists()
    assert not (workspace_dir / "candidates").exists()
    assert not (workspace_dir / "archive").exists()
    assert not (workspace_dir / "reports").exists()


def test_execute_task_set_prefers_task_binding_command_over_phase_command(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-binding-task"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True)
    (run_dir / "tasks").mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)
    write_json(run_dir / "effective_config.json", {"runtime": {}})

    task_set = tmp_path / "task_set_binding_task.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "task-binding",
                    "workdir": "${workspace_dir}",
                    "expectations": {
                        "method_id": "web_scrape/fast_path",
                        "binding_id": "openclaw/codex/web_scrape",
                    },
                    "binding": {
                        "binding_id": "openclaw/codex/web_scrape",
                        "adapter_kind": "command",
                        "command": ["python", "-c", "print('binding-task-success')"],
                    },
                    "phases": [
                        {
                            "phase": "fetch",
                            "command": ["python", "-c", "raise SystemExit(9)"],
                        }
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
    task_result = json.loads(
        (run_dir / "tasks" / "task-binding" / "task_result.json").read_text(encoding="utf-8")
    )
    assert task_result["success"] is True
    assert task_result["method_id"] == "web_scrape/fast_path"
    assert task_result["binding_id"] == "openclaw/codex/web_scrape"
    assert (
        run_dir / "tasks" / "task-binding" / "fetch.stdout.txt"
    ).read_text(encoding="utf-8").strip() == "binding-task-success"


def test_execute_task_set_command_binding_can_parse_json_stdout_for_primitive_bridge(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-command-json-bridge"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True)
    (run_dir / "tasks").mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)
    write_json(run_dir / "effective_config.json", {"runtime": {}})

    task_set = tmp_path / "task_set_command_json_bridge.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "task-json-bridge",
                    "workdir": "${workspace_dir}",
                    "expectations": {
                        "primitive_id": "web_scrape",
                        "required_fields": ["title"],
                    },
                    "binding": {
                        "binding_id": "bridge/demo_web_scrape",
                        "adapter_kind": "command",
                        "parse_json_output": True,
                        "bridge_contract": "primitive_output",
                        "bridge_config_root": str(Path(__file__).resolve().parents[1] / "configs"),
                        "command": [
                            "python",
                            "-c",
                            (
                                "import json; "
                                "print(json.dumps({'reply': {'page_html': '<html>ok</html>', 'extracted': {'title': 'Example'}}}))"
                            ),
                        ],
                    },
                    "phases": [
                        {
                            "phase": "fetch",
                            "command": ["python", "-c", "raise SystemExit(9)"],
                        }
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

    task_dir = run_dir / "tasks" / "task-json-bridge"
    assert result == {"succeeded": 1, "total": 1}
    assert json.loads((task_dir / "fetch.binding_payload.json").read_text(encoding="utf-8")) == {
        "reply": {
            "page_html": "<html>ok</html>",
            "extracted": {"title": "Example"},
        }
    }
    assert (task_dir / "page.html").read_text(encoding="utf-8") == "<html>ok</html>"
    assert json.loads((task_dir / "extracted.json").read_text(encoding="utf-8")) == {
        "title": "Example"
    }


def test_execute_task_set_rejects_unactivated_generated_binding(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run-generated-binding-gate"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True)
    (run_dir / "tasks").mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)
    write_json(run_dir / "effective_config.json", {"runtime": {}})

    task_set = tmp_path / "task_set_generated_binding_gate.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "task-gate",
                    "workdir": "${workspace_dir}",
                    "binding": {
                        "binding_id": "generated/demo_web_scrape",
                        "adapter_kind": "command",
                        "command": ["python", "-c", "print('should-not-run')"],
                    },
                    "phases": [
                        {
                            "phase": "fetch",
                            "command": ["python", "-c", "print('fallback')"],
                        }
                    ],
                }
            ]
        },
    )

    try:
        execute_task_set(
            run_dir,
            task_set,
            execution_context={
                "run_dir": str(run_dir),
                "workspace_dir": str(workspace_dir),
                "source_repo": str(workspace_dir),
            },
        )
    except ValueError as exc:
        assert "activated review" in str(exc)
    else:
        raise AssertionError("expected generated binding gate to reject unactivated binding")


def test_execute_task_set_exposes_phase_command_json_to_binding_templates(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-phase-command-context"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True)
    (run_dir / "tasks").mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)
    write_json(run_dir / "effective_config.json", {"runtime": {}})

    task_set = tmp_path / "task_set_phase_command_context.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "task-phase-context",
                    "workdir": "${workspace_dir}",
                    "binding": {
                        "binding_id": "harness/demo",
                        "adapter_kind": "command",
                        "command": [
                            "python",
                            "-c",
                            "import sys; print(sys.argv[1])",
                            "${phase_command_json}",
                        ],
                    },
                    "phases": [
                        {
                            "phase": "exec",
                            "command": ["echo", "hello"],
                        }
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
    stdout = (run_dir / "tasks" / "task-phase-context" / "exec.stdout.txt").read_text(encoding="utf-8").strip()
    assert json.loads(stdout) == ["echo", "hello"]


def test_execute_managed_run_uses_runtime_binding_command_for_transfer_candidate(
    tmp_path: Path,
) -> None:
    runs_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)

    task_set = tmp_path / "task_set_runtime_binding.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "managed-binding",
                    "workdir": "${workspace_dir}",
                    "phases": [
                        {
                            "phase": "fetch",
                            "command": ["python", "-c", "raise SystemExit(7)"],
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
            "runtime": {
                "workspace": {"source_repo": str(repo_root)},
                "binding": {
                    "binding_id": "openclaw/claude/web_scrape",
                    "adapter_kind": "command",
                    "command": ["python", "-c", "print('runtime-binding-success')"],
                },
            },
            "evaluation": {"evaluators": ["basic"]},
        },
        task_set_path=task_set,
    )

    run_dir = runs_root / result["run_id"]
    task_result = json.loads(
        (run_dir / "tasks" / "managed-binding" / "task_result.json").read_text(encoding="utf-8")
    )
    assert result["task_summary"] == {"succeeded": 1, "total": 1}
    assert task_result["binding_id"] == "openclaw/claude/web_scrape"
    assert task_result["candidate_harness_id"] is None
    assert task_result["proposal_id"] is None
    assert task_result["iteration_id"] is None
    assert task_result["wrapper_path"] is None
    assert task_result["source_artifacts"] == []
    assert (
        run_dir / "tasks" / "managed-binding" / "fetch.stdout.txt"
    ).read_text(encoding="utf-8").strip() == "runtime-binding-success"


def test_execute_managed_run_records_candidate_harness_provenance(
    tmp_path: Path,
) -> None:
    runs_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
    (repo_root / "repo_marker.txt").write_text("from-source-repo", encoding="utf-8")
    wrapper_path = tmp_path / "artifacts" / "harness-wrapper.py"
    wrapper_path.parent.mkdir(parents=True, exist_ok=True)
    wrapper_path.write_text("print('wrapper-ready')\n", encoding="utf-8")

    task_set = tmp_path / "task_set_harness_provenance.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "managed-harness",
                    "workdir": "${workspace_dir}",
                    "phases": [
                        {
                            "phase": "fetch",
                            "command": ["python", "-c", "raise SystemExit(7)"],
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
            "runtime": {
                "workspace": {"source_repo": str(repo_root)},
                "binding": {
                    "binding_id": "harness/demo",
                    "adapter_kind": "command",
                    "command": ["python", "-c", "print('harness-binding-success')"],
                    "proposal_id": "proposal-42",
                    "iteration_id": "iter-7",
                    "wrapper_path": str(wrapper_path),
                    "source_artifacts": [
                        str(wrapper_path),
                        str(repo_root / "support.json"),
                    ],
                    "provenance": {"source": "test-suite"},
                },
            },
            "evaluation": {"evaluators": ["basic"]},
        },
        task_set_path=task_set,
    )

    run_dir = runs_root / result["run_id"]
    task_result = json.loads(
        (run_dir / "tasks" / "managed-harness" / "task_result.json").read_text(encoding="utf-8")
    )
    trace_payload = json.loads(
        (run_dir / "tasks" / "managed-harness" / "steps.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )

    assert result["task_summary"] == {"succeeded": 1, "total": 1}
    assert task_result["candidate_harness_id"] == "harness/demo"
    assert task_result["proposal_id"] == "proposal-42"
    assert task_result["iteration_id"] == "iter-7"
    assert task_result["wrapper_path"] == str(wrapper_path)
    assert task_result["source_artifacts"] == [
        str(wrapper_path),
        str(repo_root / "support.json"),
    ]
    assert task_result["provenance"]["source"] == "test-suite"
    assert trace_payload["candidate_harness_id"] == "harness/demo"
    assert trace_payload["proposal_id"] == "proposal-42"
    assert trace_payload["iteration_id"] == "iter-7"
    assert trace_payload["wrapper_path"] == str(wrapper_path)
    assert trace_payload["source_artifacts"] == [
        str(wrapper_path),
        str(repo_root / "support.json"),
    ]
    assert trace_payload["provenance"]["source"] == "test-suite"


def test_execute_task_set_uses_json_agent_cli_binding_and_records_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "runs" / "run-openclaw-agent"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True)
    (run_dir / "tasks").mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)
    write_json(
        run_dir / "effective_config.json",
        {
            "runtime": {
                "binding": {
                    "binding_id": "openclaw/ops/analysis",
                    "adapter_kind": "json_agent_cli",
                    "cli_command": ["openclaw", "agent"],
                    "agent": "ops",
                    "local": True,
                    "timeout": 45,
                    "json": True,
                }
            }
        },
    )

    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append([str(item) for item in command])
        payload = {
            "reply": "analysis-ready",
            "runId": "oc-run-123",
            "sessionId": "session-9",
            "usage": {"totalTokens": 321},
        }
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr(runtime_module.subprocess, "run", fake_run)

    task_set = tmp_path / "task_set_json_agent_cli.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "task-openclaw",
                    "workdir": "${workspace_dir}",
                    "phases": [
                        {
                            "phase": "analyze",
                            "message": "Summarize the dataset drift",
                            "command": ["python", "-c", "raise SystemExit(4)"],
                        }
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
    assert calls == [
        [
            "openclaw",
            "agent",
            "--agent",
            "ops",
            "--message",
            "Summarize the dataset drift",
            "--local",
            "--timeout",
            "45",
            "--json",
        ]
    ]
    task_result = json.loads(
        (run_dir / "tasks" / "task-openclaw" / "task_result.json").read_text(encoding="utf-8")
    )
    assert task_result["binding_id"] == "openclaw/ops/analysis"
    assert task_result["binding_payload"]["reply"] == "analysis-ready"
    assert task_result["binding_payload"]["usage"]["totalTokens"] == 321
    assert task_result["binding_artifacts"] == ["analyze.binding_payload.json"]
    assert (
        run_dir / "tasks" / "task-openclaw" / "analyze.binding_payload.json"
    ).read_text(encoding="utf-8")
    trace_lines = (
        run_dir / "tasks" / "task-openclaw" / "steps.jsonl"
    ).read_text(encoding="utf-8").splitlines()
    assert len(trace_lines) == 2
    trace_payload = json.loads(trace_lines[0])
    assert trace_payload["model"] == "ops"
    assert trace_payload["token_usage"] == {"total": 321}
    assert trace_payload["artifact_refs"] == ["analyze.binding_payload.json"]
    assistant_payload = json.loads(trace_lines[1])
    assert assistant_payload["phase"] == "assistant_reply"
    assert assistant_payload["status"] == "completed"
    assert assistant_payload["artifact_refs"] == ["analyze.binding_payload.json"]
    assert assistant_payload["token_usage"] == {"total": 321}


def test_execute_task_set_runs_binding_postprocess_command_after_openclaw_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "runs" / "run-openclaw-postprocess"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True)
    (run_dir / "tasks").mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)
    write_json(
        run_dir / "effective_config.json",
        {
            "runtime": {
                "binding": {
                    "binding_id": "openclaw/ops/analysis",
                    "adapter_kind": "json_agent_cli",
                    "cli_command": ["openclaw", "agent"],
                    "agent": "ops",
                    "local": True,
                    "timeout": 45,
                    "json": True,
                }
            }
        },
    )

    original_run = runtime_module.subprocess.run

    def fake_run(command, **kwargs):
        if command[:2] == ["openclaw", "agent"]:
            payload = {
                "reply": json.dumps(
                    {
                        "page_html": "<html><body><h1>Example Tool</h1></body></html>",
                        "extracted": {"title": "Example Tool"},
                    }
                ),
                "usage": {"totalTokens": 123},
            }
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(payload),
                stderr="",
            )
        return original_run(command, **kwargs)

    monkeypatch.setattr(runtime_module.subprocess, "run", fake_run)

    normalizer = tmp_path / "normalize.py"
    normalizer.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "import sys",
                "from pathlib import Path",
                "payload = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))",
                "reply = json.loads(payload['reply'])",
                "task_dir = Path(sys.argv[2])",
                "(task_dir / 'page.html').write_text(reply['page_html'], encoding='utf-8')",
                "(task_dir / 'extracted.json').write_text(json.dumps(reply['extracted']), encoding='utf-8')",
            ]
        ),
        encoding="utf-8",
    )

    task_set = tmp_path / "task_set_openclaw_postprocess.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "task-openclaw",
                    "workdir": "${workspace_dir}",
                    "expectations": {"primitive_id": "web_scrape"},
                    "phases": [
                        {
                            "phase": "analyze",
                            "message": "Extract the title as JSON",
                            "postprocess_command": [
                                "python",
                                str(normalizer),
                                "${run_dir}/tasks/${task.task_id}/analyze.binding_payload.json",
                                "${run_dir}/tasks/${task.task_id}",
                            ],
                            "command": ["python", "-c", "raise SystemExit(4)"],
                        }
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
    task_dir = run_dir / "tasks" / "task-openclaw"
    assert (task_dir / "analyze.binding_payload.json").exists()
    assert (task_dir / "page.html").read_text(encoding="utf-8").strip() == (
        "<html><body><h1>Example Tool</h1></body></html>"
    )
    assert json.loads((task_dir / "extracted.json").read_text(encoding="utf-8")) == {
        "title": "Example Tool"
    }


def test_execute_task_set_primitive_bridge_uses_primitive_contract_for_web_scrape(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "runs" / "run-openclaw-bridge-web"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True)
    (run_dir / "tasks").mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)
    write_json(
        run_dir / "effective_config.json",
        {
            "runtime": {
                "binding": {
                    "binding_id": "openclaw/ops/web_scrape",
                    "adapter_kind": "json_agent_cli",
                    "bridge_contract": "primitive_output",
                    "cli_command": ["openclaw", "agent"],
                    "agent": "ops",
                    "local": True,
                    "timeout": 45,
                    "json": True,
                }
            }
        },
    )

    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append([str(item) for item in command])
        payload = {
            "reply": {
                "page_html": "<html><body><h1>Example Tool</h1><p>Free</p></body></html>",
                "extracted": {
                    "tool_name": "Example Tool",
                    "pricing_model": "Free",
                    "api_access": "Yes",
                },
            },
            "usage": {"totalTokens": 222},
        }
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr(runtime_module.subprocess, "run", fake_run)

    task_set = tmp_path / "task_set_primitive_bridge_web.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "task-openclaw-bridge-web",
                    "scenario": "web_scrape",
                    "workdir": "${workspace_dir}",
                    "expectations": {
                        "primitive_id": "web_scrape",
                        "required_fields": [
                            "tool_name",
                            "pricing_model",
                            "api_access",
                        ],
                    },
                    "phases": [
                        {
                            "phase": "fetch",
                            "message": "Read the bundled HTML file and extract structured product facts.",
                            "command": ["python", "-c", "raise SystemExit(4)"],
                        }
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
    assert len(calls) == 1
    message_index = calls[0].index("--message") + 1
    prompt = calls[0][message_index]
    assert "Read the bundled HTML file and extract structured product facts." in prompt
    assert '"page_html"' in prompt
    assert '"extracted"' in prompt
    assert "tool_name" in prompt
    task_dir = run_dir / "tasks" / "task-openclaw-bridge-web"
    assert (task_dir / "page.html").read_text(encoding="utf-8") == (
        "<html><body><h1>Example Tool</h1><p>Free</p></body></html>"
    )
    assert json.loads((task_dir / "extracted.json").read_text(encoding="utf-8")) == {
        "tool_name": "Example Tool",
        "pricing_model": "Free",
        "api_access": "Yes",
    }
    task_result = json.loads((task_dir / "task_result.json").read_text(encoding="utf-8"))
    assert task_result["binding_artifacts"] == [
        "fetch.binding_payload.json",
        "page.html",
        "extracted.json",
        "benchmark_probe.stdout.txt",
    ]


def test_execute_task_set_primitive_bridge_uses_primitive_contract_for_data_analysis(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "runs" / "run-openclaw-bridge-analysis"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True)
    (run_dir / "tasks").mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)
    write_json(
        run_dir / "effective_config.json",
        {
            "runtime": {
                "binding": {
                    "binding_id": "openclaw/ops/data_analysis",
                    "adapter_kind": "json_agent_cli",
                    "bridge_contract": "primitive_output",
                    "cli_command": ["openclaw", "agent"],
                    "agent": "ops",
                    "local": True,
                    "timeout": 45,
                    "json": True,
                }
            }
        },
    )

    def fake_run(command, **kwargs):
        payload = {
            "reply": {
                "analysis_summary": {
                    "recommended_tool": "Tool A",
                    "cheapest_tool": "Tool B",
                    "best_collaboration_tool": "Tool C",
                    "rationale": "Tool A balances cost and collaboration.",
                },
                "analysis_report": "# Report\n\nTool A balances cost and collaboration.",
            },
            "usage": {"totalTokens": 111},
        }
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr(runtime_module.subprocess, "run", fake_run)

    task_set = tmp_path / "task_set_primitive_bridge_analysis.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "task-openclaw-bridge-analysis",
                    "scenario": "data_analysis",
                    "workdir": "${workspace_dir}",
                    "expectations": {
                        "primitive_id": "data_analysis",
                        "required_fields": [
                            "recommended_tool",
                            "cheapest_tool",
                            "best_collaboration_tool",
                            "rationale",
                        ],
                    },
                    "phases": [
                        {
                            "phase": "analyze",
                            "message": "Compare the collected extracts and recommend the best tool.",
                            "command": ["python", "-c", "raise SystemExit(4)"],
                        }
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
    task_dir = run_dir / "tasks" / "task-openclaw-bridge-analysis"
    assert json.loads(
        (task_dir / "analysis_summary.json").read_text(encoding="utf-8")
    ) == {
        "recommended_tool": "Tool A",
        "cheapest_tool": "Tool B",
        "best_collaboration_tool": "Tool C",
        "rationale": "Tool A balances cost and collaboration.",
    }
    assert (task_dir / "analysis_report.md").read_text(encoding="utf-8") == (
        "# Report\n\nTool A balances cost and collaboration."
    )
    task_result = json.loads((task_dir / "task_result.json").read_text(encoding="utf-8"))
    assert task_result["binding_artifacts"] == [
        "analyze.binding_payload.json",
        "analysis_summary.json",
        "analysis_report.md",
        "benchmark_probe.stdout.txt",
    ]


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

def test_execute_task_set_supports_phase_assertions_for_stdout_and_artifacts(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-assertions-green"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True)
    (run_dir / "tasks").mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)
    write_json(run_dir / "effective_config.json", {})

    task_set = tmp_path / "task_set_assertions_green.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "assertions-green",
                    "workdir": "${workspace_dir}",
                    "phases": [
                        {
                            "phase": "build",
                            "command": [
                                "python",
                                "-c",
                                (
                                    "from pathlib import Path; "
                                    "Path('dist').mkdir(exist_ok=True); "
                                    "Path('dist/index.js').write_text('ok', encoding='utf-8'); "
                                    "print('build succeeded')"
                                ),
                            ],
                            "assertions": [
                                {"kind": "stdout_contains", "value": "build succeeded"},
                                {"kind": "artifact_exists", "path": "dist/index.js"},
                            ],
                        }
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

    task_result = json.loads(
        (
            run_dir / "tasks" / "assertions-green" / "task_result.json"
        ).read_text(encoding="utf-8")
    )

    assert result == {"succeeded": 1, "total": 1}
    assert task_result["success"] is True
    assert task_result["failed_phase"] is None
    assert task_result["failed_assertion"] is None


def test_execute_task_set_persists_dataset_case_metadata_to_task_result(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-dataset-case"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True)
    (run_dir / "tasks").mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)
    write_json(run_dir / "effective_config.json", {})

    task_set = tmp_path / "task_set_dataset_case.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "dataset-case-task",
                    "workdir": "${workspace_dir}",
                    "dataset_case": {
                        "query": "trace search service dependencies",
                        "expected_paths": [
                            "src/search/SearchService.ts",
                            "src/memory/MemoryRouter.ts",
                        ],
                        "expected_rank_max": 3,
                    },
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

    result = execute_task_set(
        run_dir,
        task_set,
        execution_context={
            "run_dir": str(run_dir),
            "workspace_dir": str(workspace_dir),
            "source_repo": str(workspace_dir),
        },
    )

    task_result = json.loads(
        (
            run_dir / "tasks" / "dataset-case-task" / "task_result.json"
        ).read_text(encoding="utf-8")
    )

    assert result == {"succeeded": 1, "total": 1}
    assert task_result["dataset_case"] == {
        "query": "trace search service dependencies",
        "expected_paths": [
            "src/search/SearchService.ts",
            "src/memory/MemoryRouter.ts",
        ],
        "expected_rank_max": 3,
    }


def test_execute_task_set_resolves_task_dataset_case_templates_in_commands(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-task-template"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True)
    (run_dir / "tasks").mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)
    write_json(run_dir / "effective_config.json", {})

    task_set = tmp_path / "task_set_task_template.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "task-template",
                    "workdir": "${workspace_dir}",
                    "dataset_case": {
                        "query": "trace search service dependencies",
                    },
                    "phases": [
                        {
                            "phase": "render_query",
                            "command": [
                                "python",
                                "-c",
                                "print('query=${task.dataset_case.query}')",
                            ],
                        }
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
        run_dir / "tasks" / "task-template" / "render_query.stdout.txt"
    ).read_text(encoding="utf-8").strip() == "query=trace search service dependencies"


def test_execute_task_set_fails_when_phase_assertion_detects_unexpected_stderr(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-assertions-red"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True)
    (run_dir / "tasks").mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)
    write_json(run_dir / "effective_config.json", {})

    task_set = tmp_path / "task_set_assertions_red.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "assertions-red",
                    "workdir": "${workspace_dir}",
                    "phases": [
                        {
                            "phase": "test",
                            "command": [
                                "python",
                                "-c",
                                (
                                    "import sys; "
                                    "print('all good'); "
                                    "print('deprecated warning', file=sys.stderr)"
                                ),
                            ],
                            "assertions": [
                                {"kind": "stderr_not_contains", "value": "warning"}
                            ],
                        }
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

    task_result = json.loads(
        (
            run_dir / "tasks" / "assertions-red" / "task_result.json"
        ).read_text(encoding="utf-8")
    )
    step_payload = json.loads(
        (
            run_dir / "tasks" / "assertions-red" / "steps.jsonl"
        ).read_text(encoding="utf-8").strip()
    )

    assert result == {"succeeded": 0, "total": 1}
    assert task_result["success"] is False
    assert task_result["failed_phase"] == "test"
    assert task_result["failed_assertion"]["kind"] == "stderr_not_contains"
    assert step_payload["status"] == "failed"
    assert "stderr_not_contains" in step_payload["error"]


def _read_json(run_dir: Path) -> dict:
    return json.loads((run_dir / "effective_config.json").read_text(encoding="utf-8"))
