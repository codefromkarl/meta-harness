from __future__ import annotations

import json
from pathlib import Path
import subprocess

from typer.testing import CliRunner

from meta_harness.cli import app
from meta_harness.optimizer import propose_candidate_from_architecture_recommendation


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

    assert proposal["strategy"] == "increase_budget_on_repeated_failures"
    assert proposal["source_runs"] == ["run-a", "run-b"]
    assert effective_config["budget"]["max_turns"] == 18


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


def test_optimize_propose_passes_run_context_to_proposal_command(
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
                "assert run['run_context']['tasks'][0]['completed_phases'] == 3",
                "assert run['run_context']['contextatlas']['profile_present'] is True",
                "assert run['run_context']['contextatlas']['memory_consistency_ok'] is True",
                "assert run['run_context']['contextatlas']['latest_profile_source'] == '.omc/project-memory.json'",
                "assert run['run_context']['contextatlas']['catalog_stats']['module_count'] == 2",
                "assert run['run_context']['contextatlas']['targeted_tests_ok'] is True",
                "print(json.dumps({",
                "  'notes': 'run context proposal',",
                "  'proposal': {",
                "    'strategy': 'run_context_command',",
                "    'source_runs': [run['run_id']]",
                "  }",
                "}))",
            ]
        ),
        encoding="utf-8",
    )

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "contextatlas_patch_repair.json",
        {"description": "workflow", "defaults": {}},
    )
    write_json(
        config_root / "projects" / "contextatlas_patch.json",
        {
            "workflow": "contextatlas_patch_repair",
            "overrides": {
                "optimization": {
                    "proposal_command": ["python", str(script_path)],
                }
            },
        },
    )

    run_dir = runs_root / "run-ctx"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    write_json(
        run_dir / "run_metadata.json",
        {
            "run_id": "run-ctx",
            "profile": "contextatlas_patch_repair",
            "project": "contextatlas_patch",
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
    (task_dir / "show_profile.stderr.txt").write_text(
        "\n".join(
            [
                "项目：workspace",
                "描述：Imported from .omc/project-memory.json",
                "最后更新：2026/4/5 09:30:00",
            ]
        ),
        encoding="utf-8",
    )
    (task_dir / "check_memory.stderr.txt").write_text(
        "\n".join(
            [
                'Catalog 构建完成 {"moduleCount":2,"scopeCount":1}',
                "memory consistency check: OK",
            ]
        ),
        encoding="utf-8",
    )
    (task_dir / "test_omc_import.stdout.txt").write_text(
        "tests 2\npass 2\nfail 0\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "optimize",
            "propose",
            "--profile",
            "contextatlas_patch_repair",
            "--project",
            "contextatlas_patch",
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
    assert proposal["strategy"] == "run_context_command"


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
                "assert 'contextatlas' not in run['run_context']",
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
                "    'contextatlas': {'memory': {'routing_mode': 'freshness-biased'}}",
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

    assert proposal == {
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
    assert effective_config["contextatlas"]["memory"]["routing_mode"] == "freshness-biased"


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
    assert effective_config["contextatlas"]["memory"] == {
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

    assert effective_config["contextatlas"]["memory"] == {
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
            "contextatlas": {
                "memory": {
                    "enabled": True,
                    "routing_mode": "freshness-biased",
                    "freshness_bias": 0.72,
                    "stale_prune_threshold": 0.14,
                }
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

    assert effective_config["contextatlas"]["memory"] == {
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
