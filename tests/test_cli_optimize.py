from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest
from typer.testing import CliRunner

from meta_harness.cli import app
from meta_harness.optimizer import propose_candidate_from_architecture_recommendation
from meta_harness.services.optimize_loop_service import optimize_loop_payload


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def make_failed_run(
    runs_root: Path,
    run_id: str,
    error: str,
    *,
    profile: str = "java_to_rust",
    project: str = "voidsector",
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
        },
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


def make_scored_run(
    runs_root: Path,
    run_id: str,
    *,
    profile: str,
    project: str,
    config: dict,
    composite: float,
    created_at: str = "2026-04-06T10:00:00Z",
) -> None:
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "tasks").mkdir(parents=True, exist_ok=True)
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
    payload = dict(config)
    payload["evaluation"] = {"evaluators": ["basic"]}
    write_json(run_dir / "effective_config.json", payload)
    write_json(
        run_dir / "score_report.json",
        {
            "correctness": {},
            "cost": {},
            "maintainability": {},
            "architecture": {},
            "retrieval": {},
            "human_collaboration": {},
            "composite": composite,
        },
    )


def test_optimize_propose_creates_candidate_from_failed_runs(tmp_path: Path) -> None:
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

    make_failed_run(runs_root, "run-a", "Trait bound `Foo: Clone` is not satisfied")
    make_failed_run(runs_root, "run-b", "Trait bound `Bar: Debug` is not satisfied")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "optimize",
            "propose",
            "--profile",
            "java_to_rust",
            "--project",
            "voidsector",
            "--config-root",
            str(config_root),
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
        ],
    )

    assert result.exit_code == 0
    candidate_id = result.stdout.strip()
    proposal = json.loads(
        (candidates_root / candidate_id / "proposal.json").read_text(encoding="utf-8")
    )
    effective_config = json.loads(
        (candidates_root / candidate_id / "effective_config.json").read_text(
            encoding="utf-8"
        )
    )
    proposal_records = [path for path in (tmp_path / "proposals").iterdir() if path.is_dir()]

    assert proposal["strategy"] == "increase_budget_on_repeated_failures"
    assert proposal["proposal_id"]
    assert proposal["source_runs"] == ["run-a", "run-b"]
    assert effective_config["budget"]["max_turns"] == 18
    assert len(proposal_records) == 1


def test_optimize_propose_can_create_proposal_without_materializing_candidate(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    proposals_root = tmp_path / "proposals"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "java_to_rust.json",
        {"description": "workflow", "defaults": {"retrieval": {"top_k": 8}}},
    )
    write_json(
        config_root / "projects" / "voidsector.json",
        {"workflow": "java_to_rust", "overrides": {"budget": {"max_turns": 16}}},
    )
    make_failed_run(runs_root, "run-a", "Trait bound `Foo: Clone` is not satisfied")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "optimize",
            "propose",
            "--profile",
            "java_to_rust",
            "--project",
            "voidsector",
            "--config-root",
            str(config_root),
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
            "--proposals-root",
            str(proposals_root),
            "--proposal-only",
        ],
    )

    assert result.exit_code == 0
    proposal_id = result.stdout.strip()
    proposal_record = json.loads(
        (proposals_root / proposal_id / "proposal.json").read_text(encoding="utf-8")
    )
    proposal_evaluation = json.loads(
        (proposals_root / proposal_id / "proposal_evaluation.json").read_text(encoding="utf-8")
    )
    assert proposal_record["status"] == "proposed"
    assert proposal_record["candidate_id"] is None
    assert proposal_evaluation["selected"] is True
    assert proposal_evaluation["selection_reason"] == "proposal_only"
    assert not candidates_root.exists()


def test_optimize_materialize_proposal_creates_candidate_from_proposal_artifact(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    proposals_root = tmp_path / "proposals"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "java_to_rust.json",
        {"description": "workflow", "defaults": {"retrieval": {"top_k": 8}}},
    )
    write_json(
        config_root / "projects" / "voidsector.json",
        {"workflow": "java_to_rust", "overrides": {"budget": {"max_turns": 16}}},
    )
    make_failed_run(runs_root, "run-a", "Trait bound `Foo: Clone` is not satisfied")

    runner = CliRunner()
    propose = runner.invoke(
        app,
        [
            "optimize",
            "propose",
            "--profile",
            "java_to_rust",
            "--project",
            "voidsector",
            "--config-root",
            str(config_root),
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
            "--proposals-root",
            str(proposals_root),
            "--proposal-only",
        ],
    )
    proposal_id = propose.stdout.strip()
    materialize = runner.invoke(
        app,
        [
            "optimize",
            "materialize-proposal",
            "--proposal-id",
            proposal_id,
            "--proposals-root",
            str(proposals_root),
            "--candidates-root",
            str(candidates_root),
            "--config-root",
            str(config_root),
        ],
    )

    assert propose.exit_code == 0
    assert materialize.exit_code == 0
    candidate_id = materialize.stdout.strip()
    proposal_record = json.loads(
        (proposals_root / proposal_id / "proposal.json").read_text(encoding="utf-8")
    )
    proposal_evaluation = json.loads(
        (proposals_root / proposal_id / "proposal_evaluation.json").read_text(encoding="utf-8")
    )
    candidate_proposal = json.loads(
        (candidates_root / candidate_id / "proposal.json").read_text(encoding="utf-8")
    )
    assert proposal_record["status"] == "materialized"
    assert proposal_record["candidate_id"] == candidate_id
    assert proposal_evaluation["selected"] is True
    assert proposal_evaluation["materialized_candidate_id"] == candidate_id
    assert candidate_proposal["proposal_id"] == proposal_id


def test_optimize_cli_can_list_and_show_proposals(tmp_path: Path) -> None:
    proposals_root = tmp_path / "proposals"
    proposal_dir = proposals_root / "proposal-1"
    proposal_dir.mkdir(parents=True, exist_ok=True)
    (proposal_dir / "proposal.json").write_text(
        json.dumps(
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
            indent=2,
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    listed = runner.invoke(
        app,
        [
            "optimize",
            "list-proposals",
            "--proposals-root",
            str(proposals_root),
            "--project",
            "voidsector",
        ],
    )
    shown = runner.invoke(
        app,
        [
            "optimize",
            "show-proposal",
            "--proposal-id",
            "proposal-1",
            "--proposals-root",
            str(proposals_root),
        ],
    )

    assert listed.exit_code == 0
    assert shown.exit_code == 0
    listed_payload = json.loads(listed.stdout)
    shown_payload = json.loads(shown.stdout)
    assert listed_payload[0]["proposal_id"] == "proposal-1"
    assert shown_payload["proposal_id"] == "proposal-1"
    assert shown_payload["strategy"] == "increase_budget_on_repeated_failures"


def test_optimize_propose_reuses_equivalent_candidate_on_repeat_invocation(
    tmp_path: Path,
) -> None:
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

    make_failed_run(runs_root, "run-a", "Trait bound `Foo: Clone` is not satisfied")
    make_failed_run(runs_root, "run-b", "Trait bound `Bar: Debug` is not satisfied")

    runner = CliRunner()
    first = runner.invoke(
        app,
        [
            "optimize",
            "propose",
            "--profile",
            "java_to_rust",
            "--project",
            "voidsector",
            "--config-root",
            str(config_root),
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
        ],
    )
    second = runner.invoke(
        app,
        [
            "optimize",
            "propose",
            "--profile",
            "java_to_rust",
            "--project",
            "voidsector",
            "--config-root",
            str(config_root),
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
        ],
    )

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert second.stdout.strip() == first.stdout.strip()
    candidate_dirs = [path for path in candidates_root.iterdir() if path.is_dir()]
    assert len(candidate_dirs) == 1


def test_optimize_propose_uses_command_generator_for_code_patch_candidates(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"

    script_path = tmp_path / "proposal_generator.py"
    script_path.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "import sys",
                "payload = json.load(sys.stdin)",
                "assert payload['profile'] == 'base'",
                "assert payload['project'] == 'demo'",
                "print(json.dumps({",
                "  'notes': 'command generated patch',",
                "  'proposal': {",
                "    'strategy': 'command_generated_patch',",
                "    'source_runs': [record['run_id'] for record in payload['matching_runs']]",
                "  },",
                "  'code_patch': '--- a/hello.txt\\n+++ b/hello.txt\\n@@ -1 +1 @@\\n-old\\n+new\\n'",
                "}))",
            ]
        ),
        encoding="utf-8",
    )

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {
            "workflow": "base",
            "overrides": {
                "optimization": {
                    "proposal_command": ["python", str(script_path)],
                }
            },
        },
    )

    make_failed_run(
        runs_root,
        "run-a",
        "Profile show command returned empty output",
        profile="base",
        project="demo",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "optimize",
            "propose",
            "--profile",
            "base",
            "--project",
            "demo",
            "--config-root",
            str(config_root),
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
        ],
    )

    assert result.exit_code == 0
    candidate_id = result.stdout.strip()
    candidate_dir = candidates_root / candidate_id

    proposal = json.loads((candidate_dir / "proposal.json").read_text(encoding="utf-8"))
    metadata = json.loads(
        (candidate_dir / "candidate.json").read_text(encoding="utf-8")
    )

    assert proposal["strategy"] == "command_generated_patch"
    assert proposal["source_runs"] == ["run-a"]
    assert metadata["code_patch_artifact"] == "code.patch"
    assert (
        (candidate_dir / "code.patch")
        .read_text(encoding="utf-8")
        .startswith("--- a/hello.txt")
    )


def test_optimize_propose_can_read_history_from_configured_source_pairs(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"

    script_path = tmp_path / "proposal_generator.py"
    script_path.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "import sys",
                "payload = json.load(sys.stdin)",
                "print(json.dumps({",
                "  'notes': 'history source proposal',",
                "  'proposal': {",
                "    'strategy': 'history_source_command',",
                "    'source_runs': [record['run_id'] for record in payload['matching_runs']]",
                "  }",
                "}))",
            ]
        ),
        encoding="utf-8",
    )

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "repair.json",
        {"description": "workflow", "defaults": {}},
    )
    write_json(
        config_root / "projects" / "demo_patch.json",
        {
            "workflow": "repair",
            "overrides": {
                "optimization": {
                    "proposal_command": ["python", str(script_path)],
                    "history_sources": [{"profile": "maintenance", "project": "demo"}],
                }
            },
        },
    )

    make_failed_run(
        runs_root,
        "run-maint-a",
        "Profile show command returned empty output",
        profile="maintenance",
        project="demo",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "optimize",
            "propose",
            "--profile",
            "repair",
            "--project",
            "demo_patch",
            "--config-root",
            str(config_root),
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
        ],
    )

    assert result.exit_code == 0
    candidate_id = result.stdout.strip()
    proposal = json.loads(
        (candidates_root / candidate_id / "proposal.json").read_text(encoding="utf-8")
    )

    assert proposal["strategy"] == "history_source_command"
    assert proposal["source_runs"] == ["run-maint-a"]


def test_optimize_propose_resolves_env_backed_proposal_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"

    script_path = tmp_path / "proposal_generator.py"
    script_path.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "import os",
                "print(json.dumps({'notes': 'env resolved proposal', 'proposal': {'strategy': 'env_command', 'marker': os.environ.get('PROPOSAL_MARKER')}}))",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("META_HARNESS_PROPOSAL_SCRIPT", str(script_path))
    monkeypatch.setenv("PROPOSAL_MARKER", "ready")

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {
            "workflow": "base",
            "overrides": {
                "optimization": {
                    "proposal_command": ["python", "${env.META_HARNESS_PROPOSAL_SCRIPT}"],
                }
            },
        },
    )

    make_failed_run(
        runs_root,
        "run-a",
        "Profile show command returned empty output",
        profile="base",
        project="demo",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "optimize",
            "propose",
            "--profile",
            "base",
            "--project",
            "demo",
            "--config-root",
            str(config_root),
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
        ],
    )

    assert result.exit_code == 0
    candidate_id = result.stdout.strip()
    proposal = json.loads(
        (candidates_root / candidate_id / "proposal.json").read_text(encoding="utf-8")
    )
    assert proposal["strategy"] == "env_command"
    assert proposal["marker"] == "ready"


def test_optimize_propose_can_use_llm_harness_config(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"

    script_path = tmp_path / "llm_harness_generator.py"
    script_path.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "import sys",
                "payload = json.load(sys.stdin)",
                "assert payload['model'] == 'gpt-test'",
                "assert 'run-a' in payload['user_prompt']",
                "print(json.dumps({",
                "  'notes': 'llm harness proposal',",
                "  'proposal': {",
                "    'strategy': 'llm_harness_patch',",
                "    'model': payload['model']",
                "  },",
                "  'config_patch': {",
                "    'retrieval': {'top_k': 10}",
                "  }",
                "}))",
            ]
        ),
        encoding="utf-8",
    )

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {
            "workflow": "base",
            "overrides": {
                "optimization": {
                    "llm_harness": {
                        "command": ["python", str(script_path)],
                        "model": "gpt-test",
                    }
                }
            },
        },
    )

    make_failed_run(
        runs_root,
        "run-a",
        "Profile show command returned empty output",
        profile="base",
        project="demo",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "optimize",
            "propose",
            "--profile",
            "base",
            "--project",
            "demo",
            "--config-root",
            str(config_root),
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
        ],
    )

    assert result.exit_code == 0
    candidate_id = result.stdout.strip()
    proposal = json.loads(
        (candidates_root / candidate_id / "proposal.json").read_text(encoding="utf-8")
    )
    effective_config = json.loads(
        (candidates_root / candidate_id / "effective_config.json").read_text(
            encoding="utf-8"
        )
    )
    assert proposal["strategy"] == "llm_harness_patch"
    assert proposal["model"] == "gpt-test"
    assert effective_config["retrieval"]["top_k"] == 10


def test_optimize_loop_service_forwards_request_to_runner(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {"evaluation": {"evaluators": ["basic"]}}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )
    calls: list[dict[str, object]] = []

    def fake_runner(request, **kwargs):
        calls.append(
            {
                "request": request,
                "kwargs": kwargs,
            }
        )
        return {
            "loop_id": "loop-123",
            "best_candidate_id": "candidate-1",
        }

    payload = optimize_loop_payload(
        profile_name="base",
        project_name="demo",
        task_set_path=tmp_path / "task_set.json",
        config_root=config_root,
        runs_root=tmp_path / "runs",
        candidates_root=tmp_path / "candidates",
        reports_root=tmp_path / "reports",
        loop_id="loop-override",
        plugin_id="web_scrape",
        proposer_id="heuristic",
        max_iterations=5,
        focus="all",
        run_search_loop_fn=fake_runner,
    )

    assert calls
    call = calls[0]
    request = call["request"]
    kwargs = call["kwargs"]
    assert request.profile_name == "base"
    assert request.project_name == "demo"
    assert str(request.task_set_path).endswith("task_set.json")
    assert request.task_plugin_id == "web_scrape"
    assert request.proposer_id == "heuristic"
    assert request.max_iterations == 5
    assert kwargs["task_plugin"].plugin_id == "web_scrape"
    assert kwargs["proposer"].proposer_id == "heuristic_failure_family"
    assert payload["loop_id"] == "loop-123"
    assert payload["best_candidate_id"] == "candidate-1"
    assert payload["loop_request"]["loop_id"] == "loop-override"


def test_optimize_loop_service_resolves_llm_harness_proposer_from_config(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
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
                "optimization": {
                    "llm_harness": {
                        "command": ["python", "scripts/generate.py"],
                        "model": "gpt-test",
                        "system_prompt": "You are an optimizer.",
                    }
                }
            },
        },
    )
    calls: list[dict[str, object]] = []

    def fake_runner(request, **kwargs):
        calls.append({"request": request, "kwargs": kwargs})
        return {
            "loop_id": "loop-llm",
            "best_candidate_id": "candidate-llm",
        }

    payload = optimize_loop_payload(
        profile_name="base",
        project_name="demo",
        task_set_path=tmp_path / "task_set.json",
        config_root=config_root,
        runs_root=tmp_path / "runs",
        candidates_root=tmp_path / "candidates",
        reports_root=tmp_path / "reports",
        proposer_id="llm_harness",
        run_search_loop_fn=fake_runner,
    )

    assert calls
    proposer = calls[0]["kwargs"]["proposer"]
    assert proposer.proposer_id == "llm_harness"
    assert proposer.command == ["python", "scripts/generate.py"]
    assert proposer.model_name == "gpt-test"
    assert payload["loop_id"] == "loop-llm"


def test_optimize_loop_service_uses_shared_request_builder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_root = tmp_path / "configs"
    write_json(config_root / "platform.json", {})
    write_json(config_root / "profiles" / "base.json", {"description": "workflow", "defaults": {}})
    write_json(config_root / "projects" / "demo.json", {"workflow": "base", "overrides": {}})
    captured: dict[str, object] = {}

    def fake_build_search_loop_request(**kwargs):
        captured.update(kwargs)
        from meta_harness.loop.schemas import SearchLoopRequest

        return SearchLoopRequest(
            profile_name="base",
            project_name="demo",
            task_set_path=tmp_path / "task_set.json",
            config_root=tmp_path / "configs",
            runs_root=tmp_path / "runs",
            candidates_root=tmp_path / "candidates",
            reports_root=tmp_path / "reports",
            task_plugin_id="web_scrape",
            proposer_id="heuristic",
        )

    monkeypatch.setattr(
        "meta_harness.services.optimize_loop_service.build_search_loop_request",
        fake_build_search_loop_request,
    )

    optimize_loop_payload(
        profile_name="base",
        project_name="demo",
        task_set_path=tmp_path / "task_set.json",
        config_root=config_root,
        runs_root=tmp_path / "runs",
        candidates_root=tmp_path / "candidates",
        reports_root=tmp_path / "reports",
        proposals_root=tmp_path / "proposals",
        plugin_id="web_scrape",
        proposer_id="heuristic",
        run_search_loop_fn=lambda request, **kwargs: {"loop_id": "loop-x", "loop_request": request.model_dump()},
    )

    assert captured["profile_name"] == "base"
    assert captured["project_name"] == "demo"
    assert captured["plugin_id"] == "web_scrape"
    assert captured["proposer_id"] == "heuristic"


def test_optimize_loop_cli_invokes_service_and_echoes_loop_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: dict[str, object] = {}

    def fake_optimize_loop_payload(**kwargs):
        called.update(kwargs)
        return {"loop_id": "loop-456", "best_candidate_id": "candidate-2"}

    monkeypatch.setattr(
        "meta_harness.cli_optimize_loop.optimize_loop_payload",
        fake_optimize_loop_payload,
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "optimize",
            "loop",
            "--profile",
            "base",
            "--project",
            "demo",
            "--task-set",
            str(tmp_path / "task_set.json"),
            "--config-root",
            str(tmp_path / "configs"),
            "--runs-root",
            str(tmp_path / "runs"),
            "--candidates-root",
            str(tmp_path / "candidates"),
            "--proposals-root",
            str(tmp_path / "proposals"),
            "--reports-root",
            str(tmp_path / "reports"),
            "--loop-id",
            "loop-override",
            "--plugin-id",
            "web_scrape",
            "--proposer-id",
            "heuristic",
            "--max-iterations",
            "4",
        ],
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "loop-456"
    assert called["profile_name"] == "base"
    assert called["project_name"] == "demo"
    assert called["loop_id"] == "loop-override"
    assert called["max_iterations"] == 4
    assert called["proposals_root"] == tmp_path / "proposals"


def test_optimize_propose_passes_only_shared_run_context_for_generic_workflows(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"

    script_path = tmp_path / "proposal_generator.py"
    script_path.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "import sys",
                "payload = json.load(sys.stdin)",
                "run = payload['matching_runs'][0]",
                "assert run['run_context']['tasks'][0]['task_id'] == 'task-a'",
                "assert run['run_context']['tasks'][0]['success'] is True",
                "assert set(run['run_context']) == {'tasks'}",
                "print(json.dumps({",
                "  'notes': 'generic run context proposal',",
                "  'proposal': {",
                "    'strategy': 'generic_run_context_command',",
                "    'source_runs': [run['run_id']]",
                "  }",
                "}))",
            ]
        ),
        encoding="utf-8",
    )

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "repair.json",
        {"description": "workflow", "defaults": {}},
    )
    write_json(
        config_root / "projects" / "demo_patch.json",
        {
            "workflow": "repair",
            "overrides": {
                "optimization": {
                    "proposal_command": ["python", str(script_path)],
                }
            },
        },
    )

    run_dir = runs_root / "run-generic-ctx"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    write_json(
        run_dir / "run_metadata.json",
        {
            "run_id": "run-generic-ctx",
            "profile": "repair",
            "project": "demo_patch",
            "created_at": "2026-04-05T10:00:00Z",
        },
    )
    write_json(
        run_dir / "effective_config.json",
        {"budget": {"max_turns": 14}, "evaluation": {"evaluators": ["basic"]}},
    )
    write_json(
        task_dir / "task_result.json",
        {
            "task_id": "task-a",
            "success": True,
            "completed_phases": 3,
            "failed_phase": None,
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "optimize",
            "propose",
            "--profile",
            "repair",
            "--project",
            "demo_patch",
            "--config-root",
            str(config_root),
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
        ],
    )

    assert result.exit_code == 0
    candidate_id = result.stdout.strip()
    proposal = json.loads(
        (candidates_root / candidate_id / "proposal.json").read_text(encoding="utf-8")
    )
    assert proposal["strategy"] == "generic_run_context_command"


def test_optimize_propose_passes_benchmark_v2_context_to_proposal_command(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"

    script_path = tmp_path / "proposal_generator.py"
    script_path.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "import sys",
                "payload = json.load(sys.stdin)",
                "run = payload['matching_runs'][0]",
                "assert run['run_context']['tasks'][0]['scenario'] == 'memory_staleness_resistance'",
                "assert run['run_context']['benchmark']['mechanism']['fingerprints']['memory.routing_mode'] == 'freshness-biased'",
                "assert run['run_context']['benchmark']['mechanism']['validation']['expected_signals_satisfied'] is True",
                "assert run['run_context']['benchmark']['capability_gains']['memory_staleness_resistance']['success_rate'] == 1.0",
                "assert run['run_context']['benchmark']['ranking_score'] == 2.4",
                "print(json.dumps({",
                "  'notes': 'benchmark v2 proposal',",
                "  'proposal': {",
                "    'strategy': 'benchmark_v2_context_command',",
                "    'source_runs': [run['run_id']]",
                "  }",
                "}))",
            ]
        ),
        encoding="utf-8",
    )

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {
            "workflow": "base",
            "overrides": {
                "optimization": {
                    "proposal_command": ["python", str(script_path)],
                }
            },
        },
    )

    run_dir = runs_root / "run-benchmark-v2"
    task_dir = run_dir / "tasks" / "memory-task"
    task_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    write_json(
        run_dir / "run_metadata.json",
        {
            "run_id": "run-benchmark-v2",
            "profile": "base",
            "project": "demo",
            "created_at": "2026-04-06T10:00:00Z",
        },
    )
    write_json(
        run_dir / "effective_config.json",
        {
            "evaluation": {"evaluators": ["basic"]},
            "proposal": {"variant_name": "freshness_method"},
        },
    )
    write_json(
        task_dir / "task_result.json",
        {
            "task_id": "memory-task",
            "scenario": "memory_staleness_resistance",
            "difficulty": "hard",
            "weight": 1.5,
            "success": True,
            "completed_phases": 1,
            "failed_phase": None,
        },
    )
    (task_dir / "benchmark_probe.stdout.txt").write_text(
        json.dumps(
            {
                "fingerprints": {"memory.routing_mode": "freshness-biased"},
                "probes": {
                    "memory.stale_filtered_count": 2,
                    "memory.routing_confidence": 0.91,
                },
                "validation": {
                    "expected_signals_satisfied": True,
                    "missing_signals": [],
                    "mismatch_signals": [],
                },
            }
        ),
        encoding="utf-8",
    )
    write_json(
        run_dir / "score_report.json",
        {
            "correctness": {},
            "cost": {},
            "maintainability": {},
            "architecture": {},
            "retrieval": {},
            "human_collaboration": {},
            "composite": 2.4,
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "optimize",
            "propose",
            "--profile",
            "base",
            "--project",
            "demo",
            "--config-root",
            str(config_root),
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
        ],
    )

    assert result.exit_code == 0
    candidate_id = result.stdout.strip()
    proposal = json.loads(
        (candidates_root / candidate_id / "proposal.json").read_text(encoding="utf-8")
    )
    assert proposal["strategy"] == "benchmark_v2_context_command"


def test_optimize_propose_persists_architecture_level_proposal_metadata(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"

    script_path = tmp_path / "proposal_generator.py"
    script_path.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "print(json.dumps({",
                "  'notes': 'architecture proposal',",
                "  'proposal': {",
                "    'strategy': 'promote_method_family',",
                "    'variant_type': 'method_family',",
                "    'hypothesis': 'freshness routing reduces stale memory interference',",
                "    'implementation_id': 'memory-routing/freshness-v3',",
                "    'expected_signals': {",
                "      'fingerprints': {'memory.routing_mode': 'freshness-biased'},",
                "      'probes': {'memory.routing_confidence': {'min': 0.8}}",
                "    },",
                "    'tags': ['memory', 'architecture']",
                "  },",
                "  'config_patch': {",
                "    'memory': {'routing_mode': 'freshness-biased'}",
                "  }",
                "}))",
            ]
        ),
        encoding="utf-8",
    )

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {
            "workflow": "base",
            "overrides": {
                "optimization": {
                    "proposal_command": ["python", str(script_path)],
                }
            },
        },
    )
    make_failed_run(
        runs_root,
        "run-a",
        "Memory routing returned stale context",
        profile="base",
        project="demo",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "optimize",
            "propose",
            "--profile",
            "base",
            "--project",
            "demo",
            "--config-root",
            str(config_root),
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
        ],
    )

    assert result.exit_code == 0
    candidate_id = result.stdout.strip()
    proposal = json.loads(
        (candidates_root / candidate_id / "proposal.json").read_text(encoding="utf-8")
    )
    effective_config = json.loads(
        (candidates_root / candidate_id / "effective_config.json").read_text(
            encoding="utf-8"
        )
    )

    assert {key: value for key, value in proposal.items() if key != "proposal_id"} == {
        "strategy": "promote_method_family",
        "variant_type": "method_family",
        "hypothesis": "freshness routing reduces stale memory interference",
        "implementation_id": "memory-routing/freshness-v3",
        "expected_signals": {
            "fingerprints": {"memory.routing_mode": "freshness-biased"},
            "probes": {"memory.routing_confidence": {"min": 0.8}},
        },
        "tags": ["memory", "architecture"],
    }
    assert proposal["proposal_id"]
    assert effective_config["memory"]["routing_mode"] == "freshness-biased"


def test_builtin_architecture_recommendation_proposal_templates_retrieval(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )

    candidate_id = propose_candidate_from_architecture_recommendation(
        config_root=config_root,
        candidates_root=candidates_root,
        profile_name="base",
        project_name="demo",
        source_run_ids=["run-r"],
        architecture_recommendation={
            "focus": "retrieval",
            "variant_type": "method_family",
            "proposal_strategy": "explore_retrieval_method_family",
            "hypothesis": "improve retrieval quality",
            "gap_signals": ["retrieval_hit_rate"],
            "metric_thresholds": {
                "retrieval_hit_rate": 0.7,
                "retrieval_mrr": 0.5,
                "grounded_answer_rate": 0.8,
            },
        },
    )

    proposal = json.loads(
        (candidates_root / candidate_id / "proposal.json").read_text(encoding="utf-8")
    )
    effective_config = json.loads(
        (candidates_root / candidate_id / "effective_config.json").read_text(
            encoding="utf-8"
        )
    )

    assert proposal["expected_signals"] == {
        "probes": {"retrieval.retrieval_budget": {"min": 1}}
    }
    assert proposal["tags"] == ["auto-propose", "method-family", "retrieval"]
    assert effective_config["optimization"]["focus"] == "retrieval"
    assert effective_config["retrieval"] == {
        "top_k": 12,
        "rerank_k": 24,
    }


def test_pack_driven_workflow_architecture_recommendation_uses_primitive_templates(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "workflow.json",
        {"description": "workflow", "defaults": {}},
    )
    write_json(
        config_root / "projects" / "workflow_demo.json",
        {"workflow": "workflow", "overrides": {}},
    )
    write_json(
        config_root / "primitives" / "web_scrape.json",
        {
            "primitive_id": "web_scrape",
            "kind": "browser_interaction",
            "proposal_templates": [
                {
                    "template_id": "web_scrape/fast_path",
                    "title": "Fast path",
                    "hypothesis": "Reduce wait time on stable pages",
                    "knobs": {
                        "timeout_ms": 5000,
                        "wait_strategy": "domcontentloaded",
                    },
                    "expected_signals": {
                        "fingerprints": {"scrape.mode": "fast"}
                    },
                    "tags": ["latency"],
                },
                {
                    "template_id": "web_scrape/hardening",
                    "title": "Hardening",
                    "hypothesis": "Increase resilience on unstable pages",
                    "knobs": {
                        "timeout_ms": 9000,
                        "retry_limit": 3,
                    },
                    "expected_signals": {
                        "probes": {"scrape.retry_count": {"max": 3}}
                    },
                    "tags": ["stability"],
                },
            ],
        },
    )

    candidate_id = propose_candidate_from_architecture_recommendation(
        config_root=config_root,
        candidates_root=candidates_root,
        profile_name="workflow",
        project_name="workflow_demo",
        source_run_ids=["run-workflow"],
        architecture_recommendation={
            "focus": "workflow",
            "primitive_id": "web_scrape",
            "variant_type": "method_family",
            "proposal_strategy": "explore_workflow_method_family",
            "hypothesis": "improve workflow hot path",
            "gap_signals": ["hot_path_success_rate"],
            "metric_thresholds": {
                "hot_path_success_rate": 0.9,
                "fallback_rate": 0.15,
            },
        },
    )

    proposal = json.loads(
        (candidates_root / candidate_id / "proposal.json").read_text(encoding="utf-8")
    )
    effective_config = json.loads(
        (candidates_root / candidate_id / "effective_config.json").read_text(
            encoding="utf-8"
        )
    )

    assert proposal["strategy"] == "explore_workflow_method_family"
    assert proposal["expected_signals"] == {
        "fingerprints": {"scrape.mode": "fast"}
    }
    assert "web_scrape" in proposal["tags"]
    assert proposal["selected_template_id"] == "web_scrape/fast_path"
    assert effective_config["workflow"]["primitives"]["web_scrape"] == {
        "timeout_ms": 5000,
        "wait_strategy": "domcontentloaded",
    }


def test_builtin_architecture_recommendation_binding_patch_templates(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "workflow.json",
        {
            "description": "workflow",
            "defaults": {"runtime": {"binding": {"agent": "claude"}}},
        },
    )
    write_json(
        config_root / "projects" / "workflow_demo.json",
        {"workflow": "workflow", "overrides": {}},
    )

    candidate_id = propose_candidate_from_architecture_recommendation(
        config_root=config_root,
        candidates_root=candidates_root,
        profile_name="workflow",
        project_name="workflow_demo",
        source_run_ids=["run-binding"],
        architecture_recommendation={
            "focus": "binding",
            "primitive_id": "web_scrape",
            "variant_type": "method_family",
            "proposal_strategy": "explore_binding_patch",
            "hypothesis": "improve transferred binding fidelity",
            "gap_signals": [
                "binding_execution_rate",
                "method_trace_coverage_rate",
                "binding_payload_rate",
            ],
            "metric_thresholds": {
                "binding_execution_rate": 0.9,
                "method_trace_coverage_rate": 0.85,
                "binding_payload_rate": 0.9,
                "assistant_reply_rate": 0.85,
                "artifact_coverage_rate": 0.85,
            },
        },
    )

    proposal = json.loads(
        (candidates_root / candidate_id / "proposal.json").read_text(encoding="utf-8")
    )
    effective_config = json.loads(
        (candidates_root / candidate_id / "effective_config.json").read_text(
            encoding="utf-8"
        )
    )

    assert proposal["strategy"] == "explore_binding_patch"
    assert proposal["expected_signals"] == {
        "probes": {
            "web_scrape.binding_payload_present_rate": {"min": 1},
            "web_scrape.assistant_reply_rate": {"min": 1},
        }
    }
    assert effective_config["optimization"]["focus"] == "binding"
    assert effective_config["runtime"]["binding"] == {
        "agent": "claude",
        "json": True,
        "local": True,
        "timeout": 900,
        "verbose": "on",
    }


def test_pack_driven_workflow_architecture_recommendation_selects_hardening_template_for_strong_gap(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "workflow.json",
        {"description": "workflow", "defaults": {}},
    )
    write_json(
        config_root / "projects" / "workflow_demo.json",
        {"workflow": "workflow", "overrides": {}},
    )
    write_json(
        config_root / "primitives" / "web_scrape.json",
        {
            "primitive_id": "web_scrape",
            "kind": "browser_interaction",
            "proposal_templates": [
                {
                    "template_id": "web_scrape/fast_path",
                    "title": "Fast path",
                    "hypothesis": "Reduce wait time on stable pages",
                    "knobs": {
                        "timeout_ms": 5000,
                        "wait_strategy": "domcontentloaded",
                    },
                    "expected_signals": {
                        "fingerprints": {"scrape.mode": "fast"}
                    },
                    "tags": ["latency"],
                },
                {
                    "template_id": "web_scrape/hardening",
                    "title": "Hardening",
                    "hypothesis": "Increase resilience on unstable pages",
                    "knobs": {
                        "timeout_ms": 9000,
                        "retry_limit": 3,
                    },
                    "expected_signals": {
                        "probes": {"scrape.retry_count": {"max": 3}}
                    },
                    "tags": ["stability"],
                },
            ],
        },
    )

    candidate_id = propose_candidate_from_architecture_recommendation(
        config_root=config_root,
        candidates_root=candidates_root,
        profile_name="workflow",
        project_name="workflow_demo",
        source_run_ids=["run-workflow"],
        architecture_recommendation={
            "focus": "workflow",
            "primitive_id": "web_scrape",
            "variant_type": "method_family",
            "proposal_strategy": "explore_workflow_method_family",
            "hypothesis": "improve workflow hot path",
            "gap_signals": ["hot_path_success_rate", "fallback_rate"],
            "metric_thresholds": {
                "hot_path_success_rate": 0.9,
                "fallback_rate": 0.15,
            },
        },
    )

    proposal = json.loads(
        (candidates_root / candidate_id / "proposal.json").read_text(encoding="utf-8")
    )
    effective_config = json.loads(
        (candidates_root / candidate_id / "effective_config.json").read_text(
            encoding="utf-8"
        )
    )

    assert proposal["expected_signals"] == {
        "probes": {"scrape.retry_count": {"max": 3}}
    }
    assert proposal["selected_template_id"] == "web_scrape/hardening"
    assert effective_config["workflow"]["primitives"]["web_scrape"] == {
        "timeout_ms": 9000,
        "retry_limit": 3,
    }


def test_builtin_architecture_recommendation_proposal_templates_retrieval_scale_with_gap_strength(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {
            "description": "workflow",
            "defaults": {"retrieval": {"top_k": 8, "rerank_k": 8}},
        },
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )

    candidate_id = propose_candidate_from_architecture_recommendation(
        config_root=config_root,
        candidates_root=candidates_root,
        profile_name="base",
        project_name="demo",
        source_run_ids=["run-r-strong"],
        architecture_recommendation={
            "focus": "retrieval",
            "variant_type": "method_family",
            "proposal_strategy": "explore_retrieval_method_family",
            "hypothesis": "improve retrieval quality",
            "gap_signals": [
                "retrieval_hit_rate",
                "retrieval_mrr",
                "grounded_answer_rate",
            ],
            "metric_thresholds": {
                "retrieval_hit_rate": 0.82,
                "retrieval_mrr": 0.65,
                "grounded_answer_rate": 0.9,
            },
        },
    )

    effective_config = json.loads(
        (candidates_root / candidate_id / "effective_config.json").read_text(
            encoding="utf-8"
        )
    )

    assert effective_config["retrieval"] == {
        "top_k": 16,
        "rerank_k": 32,
    }


def test_builtin_architecture_recommendation_retrieval_template_avoids_current_config_band(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {
            "description": "workflow",
            "defaults": {"retrieval": {"top_k": 12, "rerank_k": 24}},
        },
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )

    candidate_id = propose_candidate_from_architecture_recommendation(
        config_root=config_root,
        candidates_root=candidates_root,
        profile_name="base",
        project_name="demo",
        source_run_ids=["run-r-current"],
        architecture_recommendation={
            "focus": "retrieval",
            "variant_type": "method_family",
            "proposal_strategy": "explore_retrieval_method_family",
            "hypothesis": "improve retrieval quality",
            "gap_signals": ["retrieval_hit_rate"],
            "metric_thresholds": {
                "retrieval_hit_rate": 0.7,
                "retrieval_mrr": 0.5,
                "grounded_answer_rate": 0.8,
            },
        },
    )

    effective_config = json.loads(
        (candidates_root / candidate_id / "effective_config.json").read_text(
            encoding="utf-8"
        )
    )

    assert effective_config["retrieval"] == {
        "top_k": 16,
        "rerank_k": 32,
    }


def test_builtin_architecture_recommendation_retrieval_template_avoids_best_run_band(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"
    runs_root = tmp_path / "runs"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {
            "description": "workflow",
            "defaults": {"retrieval": {"top_k": 8, "rerank_k": 8}},
        },
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )
    run_dir = runs_root / "run-best"
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        run_dir / "run_metadata.json",
        {
            "run_id": "run-best",
            "profile": "base",
            "project": "demo",
            "created_at": "2026-04-06T10:00:00Z",
        },
    )
    write_json(
        run_dir / "effective_config.json",
        {
            "retrieval": {"top_k": 16, "rerank_k": 32},
            "evaluation": {"evaluators": ["basic"]},
        },
    )
    write_json(
        run_dir / "score_report.json",
        {
            "correctness": {},
            "cost": {},
            "maintainability": {},
            "architecture": {},
            "retrieval": {},
            "human_collaboration": {},
            "composite": 18.0,
        },
    )

    candidate_id = propose_candidate_from_architecture_recommendation(
        config_root=config_root,
        candidates_root=candidates_root,
        profile_name="base",
        project_name="demo",
        source_run_ids=["run-best"],
        architecture_recommendation={
            "focus": "retrieval",
            "variant_type": "method_family",
            "proposal_strategy": "explore_retrieval_method_family",
            "hypothesis": "improve retrieval quality",
            "gap_signals": [
                "retrieval_hit_rate",
                "retrieval_mrr",
                "grounded_answer_rate",
            ],
            "metric_thresholds": {
                "retrieval_hit_rate": 0.82,
                "retrieval_mrr": 0.65,
                "grounded_answer_rate": 0.9,
            },
        },
        runs_root=runs_root,
    )

    effective_config = json.loads(
        (candidates_root / candidate_id / "effective_config.json").read_text(
            encoding="utf-8"
        )
    )

    assert effective_config["retrieval"] == {
        "top_k": 20,
        "rerank_k": 40,
    }


def test_builtin_architecture_recommendation_retrieval_template_prefers_nearest_historical_config(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"
    runs_root = tmp_path / "runs"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {
            "description": "workflow",
            "defaults": {"retrieval": {"top_k": 8, "rerank_k": 8}},
        },
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )
    make_scored_run(
        runs_root,
        "run-r-near",
        profile="base",
        project="demo",
        config={"retrieval": {"top_k": 10, "rerank_k": 20}},
        composite=11.0,
    )
    make_scored_run(
        runs_root,
        "run-r-far",
        profile="base",
        project="demo",
        config={"retrieval": {"top_k": 14, "rerank_k": 28}},
        composite=14.0,
    )

    candidate_id = propose_candidate_from_architecture_recommendation(
        config_root=config_root,
        candidates_root=candidates_root,
        profile_name="base",
        project_name="demo",
        source_run_ids=["run-r-near", "run-r-far"],
        architecture_recommendation={
            "focus": "retrieval",
            "variant_type": "method_family",
            "proposal_strategy": "explore_retrieval_method_family",
            "hypothesis": "improve retrieval quality",
            "gap_signals": ["retrieval_hit_rate"],
            "metric_thresholds": {
                "retrieval_hit_rate": 0.72,
                "retrieval_mrr": 0.52,
                "grounded_answer_rate": 0.82,
            },
        },
        runs_root=runs_root,
    )

    effective_config = json.loads(
        (candidates_root / candidate_id / "effective_config.json").read_text(
            encoding="utf-8"
        )
    )

    assert effective_config["retrieval"] == {
        "top_k": 10,
        "rerank_k": 20,
    }


def test_builtin_architecture_recommendation_proposal_templates_memory(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )

    candidate_id = propose_candidate_from_architecture_recommendation(
        config_root=config_root,
        candidates_root=candidates_root,
        profile_name="base",
        project_name="demo",
        source_run_ids=["run-m"],
        architecture_recommendation={
            "focus": "memory",
            "variant_type": "method_family",
            "proposal_strategy": "explore_memory_method_family",
            "hypothesis": "improve memory routing freshness",
            "gap_signals": ["memory_stale_ratio"],
            "metric_thresholds": {
                "memory_completeness": 0.8,
                "memory_freshness": 0.85,
                "memory_stale_ratio": 0.1,
            },
        },
    )

    proposal = json.loads(
        (candidates_root / candidate_id / "proposal.json").read_text(encoding="utf-8")
    )
    effective_config = json.loads(
        (candidates_root / candidate_id / "effective_config.json").read_text(
            encoding="utf-8"
        )
    )

    assert proposal["expected_signals"] == {
        "probes": {"memory.routing_confidence": {"min": 0.5}}
    }
    assert proposal["tags"] == ["auto-propose", "method-family", "memory"]
    assert effective_config["optimization"]["focus"] == "memory"
    assert effective_config["memory"] == {
        "enabled": True,
        "routing_mode": "freshness-biased",
        "freshness_bias": 0.8,
        "stale_prune_threshold": 0.12,
    }


def test_builtin_architecture_recommendation_proposal_templates_memory_scale_with_gap_strength(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )

    candidate_id = propose_candidate_from_architecture_recommendation(
        config_root=config_root,
        candidates_root=candidates_root,
        profile_name="base",
        project_name="demo",
        source_run_ids=["run-m-strong"],
        architecture_recommendation={
            "focus": "memory",
            "variant_type": "method_family",
            "proposal_strategy": "explore_memory_method_family",
            "hypothesis": "improve memory routing freshness",
            "gap_signals": [
                "memory_completeness",
                "memory_freshness",
                "memory_stale_ratio",
            ],
            "metric_thresholds": {
                "memory_completeness": 0.85,
                "memory_freshness": 0.9,
                "memory_stale_ratio": 0.08,
            },
        },
    )

    effective_config = json.loads(
        (candidates_root / candidate_id / "effective_config.json").read_text(
            encoding="utf-8"
        )
    )

    assert effective_config["memory"] == {
        "enabled": True,
        "routing_mode": "freshness-biased",
        "freshness_bias": 0.9,
        "stale_prune_threshold": 0.08,
    }


def test_builtin_architecture_recommendation_memory_template_prefers_historical_config(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"
    runs_root = tmp_path / "runs"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )
    make_scored_run(
        runs_root,
        "run-m-near",
        profile="base",
        project="demo",
        config={
            "memory": {
                "enabled": True,
                "routing_mode": "freshness-biased",
                "freshness_bias": 0.72,
                "stale_prune_threshold": 0.14,
            }
        },
        composite=12.0,
    )

    candidate_id = propose_candidate_from_architecture_recommendation(
        config_root=config_root,
        candidates_root=candidates_root,
        profile_name="base",
        project_name="demo",
        source_run_ids=["run-m-near"],
        architecture_recommendation={
            "focus": "memory",
            "variant_type": "method_family",
            "proposal_strategy": "explore_memory_method_family",
            "hypothesis": "improve memory routing freshness",
            "gap_signals": ["memory_stale_ratio"],
            "metric_thresholds": {
                "memory_completeness": 0.8,
                "memory_freshness": 0.85,
                "memory_stale_ratio": 0.1,
            },
        },
        runs_root=runs_root,
    )

    effective_config = json.loads(
        (candidates_root / candidate_id / "effective_config.json").read_text(
            encoding="utf-8"
        )
    )

    assert effective_config["memory"] == {
        "enabled": True,
        "routing_mode": "freshness-biased",
        "freshness_bias": 0.72,
        "stale_prune_threshold": 0.14,
    }


def test_builtin_architecture_recommendation_proposal_templates_indexing(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )

    candidate_id = propose_candidate_from_architecture_recommendation(
        config_root=config_root,
        candidates_root=candidates_root,
        profile_name="base",
        project_name="demo",
        source_run_ids=["run-i"],
        architecture_recommendation={
            "focus": "indexing",
            "variant_type": "method_family",
            "proposal_strategy": "explore_indexing_method_family",
            "hypothesis": "improve indexing freshness",
            "gap_signals": ["index_freshness_ratio"],
            "metric_thresholds": {
                "vector_coverage_ratio": 0.9,
                "index_freshness_ratio": 0.85,
            },
        },
    )

    proposal = json.loads(
        (candidates_root / candidate_id / "proposal.json").read_text(encoding="utf-8")
    )
    effective_config = json.loads(
        (candidates_root / candidate_id / "effective_config.json").read_text(
            encoding="utf-8"
        )
    )

    assert proposal["expected_signals"] == {
        "probes": {"indexing.chunk_profile": {"min": 1}}
    }
    assert proposal["tags"] == ["auto-propose", "method-family", "indexing"]
    assert effective_config["optimization"]["focus"] == "indexing"
    assert effective_config["indexing"] == {
        "chunk_size": 1200,
        "chunk_overlap": 160,
    }


def test_builtin_architecture_recommendation_proposal_templates_indexing_scale_with_gap_strength(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {"indexing": {"chunk_size": 1000, "chunk_overlap": 40}}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )

    candidate_id = propose_candidate_from_architecture_recommendation(
        config_root=config_root,
        candidates_root=candidates_root,
        profile_name="base",
        project_name="demo",
        source_run_ids=["run-i-strong"],
        architecture_recommendation={
            "focus": "indexing",
            "variant_type": "method_family",
            "proposal_strategy": "explore_indexing_method_family",
            "hypothesis": "improve indexing freshness",
            "gap_signals": [
                "vector_coverage_ratio",
                "index_freshness_ratio",
            ],
            "metric_thresholds": {
                "vector_coverage_ratio": 0.95,
                "index_freshness_ratio": 0.9,
            },
        },
    )

    effective_config = json.loads(
        (candidates_root / candidate_id / "effective_config.json").read_text(
            encoding="utf-8"
        )
    )

    assert effective_config["indexing"] == {
        "chunk_size": 1400,
        "chunk_overlap": 200,
    }


def test_builtin_architecture_recommendation_indexing_template_avoids_best_run_band(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"
    runs_root = tmp_path / "runs"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {
            "description": "workflow",
            "defaults": {"indexing": {"chunk_size": 1200, "chunk_overlap": 160}},
        },
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )
    run_dir = runs_root / "run-index-best"
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        run_dir / "run_metadata.json",
        {
            "run_id": "run-index-best",
            "profile": "base",
            "project": "demo",
            "created_at": "2026-04-06T10:00:00Z",
        },
    )
    write_json(
        run_dir / "effective_config.json",
        {
            "indexing": {"chunk_size": 1400, "chunk_overlap": 200},
            "evaluation": {"evaluators": ["basic"]},
        },
    )
    write_json(
        run_dir / "score_report.json",
        {
            "correctness": {},
            "cost": {},
            "maintainability": {},
            "architecture": {},
            "retrieval": {},
            "human_collaboration": {},
            "composite": 17.0,
        },
    )

    candidate_id = propose_candidate_from_architecture_recommendation(
        config_root=config_root,
        candidates_root=candidates_root,
        profile_name="base",
        project_name="demo",
        source_run_ids=["run-index-best"],
        architecture_recommendation={
            "focus": "indexing",
            "variant_type": "method_family",
            "proposal_strategy": "explore_indexing_method_family",
            "hypothesis": "improve indexing freshness",
            "gap_signals": [
                "vector_coverage_ratio",
                "index_freshness_ratio",
            ],
            "metric_thresholds": {
                "vector_coverage_ratio": 0.95,
                "index_freshness_ratio": 0.9,
            },
        },
        runs_root=runs_root,
    )

    effective_config = json.loads(
        (candidates_root / candidate_id / "effective_config.json").read_text(
            encoding="utf-8"
        )
    )

    assert effective_config["indexing"] == {
        "chunk_size": 1600,
        "chunk_overlap": 240,
    }


def test_builtin_architecture_recommendation_indexing_template_prefers_nearest_historical_config(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"
    runs_root = tmp_path / "runs"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {
            "description": "workflow",
            "defaults": {"indexing": {"chunk_size": 1000, "chunk_overlap": 40}},
        },
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )
    make_scored_run(
        runs_root,
        "run-i-near",
        profile="base",
        project="demo",
        config={"indexing": {"chunk_size": 1100, "chunk_overlap": 80}},
        composite=12.0,
    )
    make_scored_run(
        runs_root,
        "run-i-far",
        profile="base",
        project="demo",
        config={"indexing": {"chunk_size": 1500, "chunk_overlap": 220}},
        composite=16.0,
    )

    candidate_id = propose_candidate_from_architecture_recommendation(
        config_root=config_root,
        candidates_root=candidates_root,
        profile_name="base",
        project_name="demo",
        source_run_ids=["run-i-near", "run-i-far"],
        architecture_recommendation={
            "focus": "indexing",
            "variant_type": "method_family",
            "proposal_strategy": "explore_indexing_method_family",
            "hypothesis": "improve indexing freshness",
            "gap_signals": ["index_freshness_ratio"],
            "metric_thresholds": {
                "vector_coverage_ratio": 0.91,
                "index_freshness_ratio": 0.86,
            },
        },
        runs_root=runs_root,
    )

    effective_config = json.loads(
        (candidates_root / candidate_id / "effective_config.json").read_text(
            encoding="utf-8"
        )
    )

    assert effective_config["indexing"] == {
        "chunk_size": 1100,
        "chunk_overlap": 80,
    }


def test_optimize_shadow_run_executes_and_scores_candidate(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"
    runs_root = tmp_path / "runs"

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
        {"workflow": "base", "overrides": {}},
    )

    runner = CliRunner()
    create_result = runner.invoke(
        app,
        [
            "candidate",
            "create",
            "--profile",
            "base",
            "--project",
            "demo",
            "--config-root",
            str(config_root),
            "--candidates-root",
            str(candidates_root),
            "--notes",
            "shadow",
        ],
    )
    assert create_result.exit_code == 0
    candidate_id = create_result.stdout.strip()

    task_set = tmp_path / "task_set.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "task-a",
                    "workdir": str(tmp_path),
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

    shadow_result = runner.invoke(
        app,
        [
            "optimize",
            "shadow-run",
            "--candidate-id",
            candidate_id,
            "--task-set",
            str(task_set),
            "--candidates-root",
            str(candidates_root),
            "--runs-root",
            str(runs_root),
        ],
    )
    assert shadow_result.exit_code == 0

    run_id = shadow_result.stdout.strip()
    run_dir = runs_root / run_id
    score_report = json.loads(
        (run_dir / "score_report.json").read_text(encoding="utf-8")
    )
    run_metadata = json.loads(
        (run_dir / "run_metadata.json").read_text(encoding="utf-8")
    )

    assert run_metadata["candidate_id"] == candidate_id
    assert score_report["correctness"]["task_count"] == 1
    assert score_report["composite"] == 1.0


def test_optimize_shadow_run_applies_code_patch_in_workspace(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"
    runs_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"

    repo_root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)
    (repo_root / "hello.txt").write_text("old\n", encoding="utf-8")

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
            "overrides": {
                "runtime": {
                    "workspace": {
                        "source_repo": str(repo_root),
                    }
                }
            },
        },
    )

    patch_path = tmp_path / "hello.patch"
    patch_path.write_text(
        "--- a/hello.txt\n+++ b/hello.txt\n@@ -1 +1 @@\n-old\n+new\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    create_result = runner.invoke(
        app,
        [
            "candidate",
            "create",
            "--profile",
            "base",
            "--project",
            "demo",
            "--config-root",
            str(config_root),
            "--candidates-root",
            str(candidates_root),
            "--code-patch",
            str(patch_path),
            "--notes",
            "workspace patch",
        ],
    )
    assert create_result.exit_code == 0
    candidate_id = create_result.stdout.strip()

    task_set = tmp_path / "task_set.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "task-a",
                    "workdir": "${workspace_dir}",
                    "phases": [
                        {
                            "phase": "inspect",
                            "command": [
                                "python",
                                "-c",
                                "from pathlib import Path; print(Path('hello.txt').read_text(encoding='utf-8').strip())",
                            ],
                        }
                    ],
                }
            ]
        },
    )

    shadow_result = runner.invoke(
        app,
        [
            "optimize",
            "shadow-run",
            "--candidate-id",
            candidate_id,
            "--task-set",
            str(task_set),
            "--candidates-root",
            str(candidates_root),
            "--runs-root",
            str(runs_root),
        ],
    )
    assert shadow_result.exit_code == 0

    run_id = shadow_result.stdout.strip()
    run_dir = runs_root / run_id
    workspace_info = json.loads(
        (run_dir / "artifacts" / "workspace.json").read_text(encoding="utf-8")
    )

    assert workspace_info["patch_applied"] is True
    assert (
        Path(workspace_info["workspace_dir"])
        .joinpath("hello.txt")
        .read_text(encoding="utf-8")
        == "new\n"
    )
    assert (repo_root / "hello.txt").read_text(encoding="utf-8") == "old\n"
    assert (run_dir / "tasks" / "task-a" / "inspect.stdout.txt").read_text(
        encoding="utf-8"
    ).strip() == "new"


def test_optimize_shadow_run_accepts_already_applied_patch(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"
    runs_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"

    repo_root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)
    (repo_root / "hello.txt").write_text("new\n", encoding="utf-8")

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
            "overrides": {
                "runtime": {
                    "workspace": {
                        "source_repo": str(repo_root),
                    }
                }
            },
        },
    )

    patch_path = tmp_path / "hello.patch"
    patch_path.write_text(
        "--- a/hello.txt\n+++ b/hello.txt\n@@ -1 +1 @@\n-old\n+new\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    create_result = runner.invoke(
        app,
        [
            "candidate",
            "create",
            "--profile",
            "base",
            "--project",
            "demo",
            "--config-root",
            str(config_root),
            "--candidates-root",
            str(candidates_root),
            "--code-patch",
            str(patch_path),
            "--notes",
            "already applied patch",
        ],
    )
    assert create_result.exit_code == 0
    candidate_id = create_result.stdout.strip()

    task_set = tmp_path / "task_set.json"
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "task-a",
                    "workdir": "${workspace_dir}",
                    "phases": [
                        {
                            "phase": "inspect",
                            "command": [
                                "python",
                                "-c",
                                "from pathlib import Path; print(Path('hello.txt').read_text(encoding='utf-8').strip())",
                            ],
                        }
                    ],
                }
            ]
        },
    )

    shadow_result = runner.invoke(
        app,
        [
            "optimize",
            "shadow-run",
            "--candidate-id",
            candidate_id,
            "--task-set",
            str(task_set),
            "--candidates-root",
            str(candidates_root),
            "--runs-root",
            str(runs_root),
        ],
    )
    assert shadow_result.exit_code == 0

    run_id = shadow_result.stdout.strip()
    workspace_info = json.loads(
        (runs_root / run_id / "artifacts" / "workspace.json").read_text(
            encoding="utf-8"
        )
    )

    assert workspace_info["patch_applied"] is False
    assert workspace_info["patch_already_present"] is True


def test_optimize_shadow_run_resolves_relative_candidate_patch_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)
    (repo_root / "hello.txt").write_text("old\n", encoding="utf-8")

    write_json(Path("configs") / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        Path("configs") / "profiles" / "base.json",
        {
            "description": "workflow",
            "defaults": {"evaluation": {"evaluators": ["basic"]}},
        },
    )
    write_json(
        Path("configs") / "projects" / "demo.json",
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

    patch_path = tmp_path / "hello.patch"
    patch_path.write_text(
        "--- a/hello.txt\n+++ b/hello.txt\n@@ -1 +1 @@\n-old\n+new\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    create_result = runner.invoke(
        app,
        [
            "candidate",
            "create",
            "--profile",
            "base",
            "--project",
            "demo",
            "--config-root",
            "configs",
            "--candidates-root",
            "candidates",
            "--code-patch",
            str(patch_path),
            "--notes",
            "relative roots",
        ],
    )
    assert create_result.exit_code == 0
    candidate_id = create_result.stdout.strip()

    write_json(
        Path("task_set.json"),
        {
            "tasks": [
                {
                    "task_id": "task-a",
                    "workdir": "${workspace_dir}",
                    "phases": [
                        {
                            "phase": "inspect",
                            "command": [
                                "python",
                                "-c",
                                "from pathlib import Path; print(Path('hello.txt').read_text(encoding='utf-8').strip())",
                            ],
                        }
                    ],
                }
            ]
        },
    )

    shadow_result = runner.invoke(
        app,
        [
            "optimize",
            "shadow-run",
            "--candidate-id",
            candidate_id,
            "--task-set",
            "task_set.json",
            "--candidates-root",
            "candidates",
            "--runs-root",
            "runs",
        ],
    )
    assert shadow_result.exit_code == 0
