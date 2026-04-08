from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from meta_harness.benchmark import run_benchmark
from meta_harness.cli import app
import meta_harness.cli as cli_module


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def make_task_set(path: Path, *, workdir: str) -> None:
    write_json(
        path,
        {
            "tasks": [
                {
                    "task_id": "benchmark-task",
                    "workdir": workdir,
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


def make_task_set_with_metadata(
    path: Path,
    *,
    workdir: str,
    scenario: str,
    difficulty: str = "medium",
    weight: float = 1.0,
) -> None:
    write_json(
        path,
        {
            "tasks": [
                {
                    "task_id": "benchmark-task",
                    "scenario": scenario,
                    "difficulty": difficulty,
                    "weight": weight,
                    "workdir": workdir,
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


def test_run_benchmark_supports_harness_native_variant_and_metadata(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    repo_root = tmp_path / "repo"
    task_set = tmp_path / "task_set.json"
    spec_path = tmp_path / "benchmark.json"

    repo_root.mkdir(parents=True, exist_ok=True)
    write_json(
        repo_root / "source.txt",
        {"message": "workspace source"},
    )
    make_task_set(task_set, workdir=str(repo_root))
    write_json(
        spec_path,
        {
            "experiment": "harness-native",
            "baseline": "baseline",
            "variants": [
                {"name": "baseline"},
                {
                    "name": "candidate_harness",
                    "variant_type": "harness",
                    "candidate_harness": {
                        "candidate_id": "cand-harness-1",
                        "harness_spec_id": "harness-demo",
                        "iteration_id": "iter-1",
                        "proposal_id": "proposal-1",
                        "wrapper_path": "scripts/generated/demo_harness_wrapper.py",
                        "source_artifacts": [
                            "reports/integration/harness-demo/harness_spec.reviewed.json",
                            "reports/integration/harness-demo/harness_review_result.json",
                        ],
                        "provenance": {
                            "review_result_path": "reports/integration/harness-demo/harness_review_result.json",
                            "source": "integration_service",
                        },
                        "runtime": {
                            "binding": {
                                "binding_id": "harness/demo",
                                "adapter_kind": "command",
                                "command": ["python", "-c", "print('harness-run')"],
                            }
                        },
                    },
                },
            ],
        },
    )

    payload = run_benchmark(
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        profile_name="base",
        project_name="demo",
        task_set_path=task_set,
        spec_path=spec_path,
        effective_config_override={
            "runtime": {"workspace": {"source_repo": str(repo_root)}},
            "evaluation": {"evaluators": ["basic"]},
        },
    )

    harness_variant = next(
        item for item in payload["variants"] if item["name"] == "candidate_harness"
    )
    assert harness_variant["variant_type"] == "harness"
    assert harness_variant["candidate_harness"]["candidate_id"]
    assert harness_variant["candidate_harness"]["harness_spec_id"] == "harness-demo"
    assert harness_variant["candidate_harness"]["iteration_id"] == "iter-1"
    assert harness_variant["candidate_harness"]["proposal_id"] == "proposal-1"
    assert harness_variant["candidate_harness"]["wrapper_path"].endswith(
        "demo_harness_wrapper.py"
    )
    assert harness_variant["candidate_harness"]["source_artifacts"]
    assert harness_variant["candidate_harness"]["provenance"]["source"] == "integration_service"
    assert harness_variant["candidate_harness"]["runtime"]["binding"]["binding_id"] == "harness/demo"
    assert harness_variant["candidate_harness"]["runtime"]["binding"]["command"] == [
        "python",
        "-c",
        "print('harness-run')",
    ]


def test_observe_benchmark_runs_variants_and_selects_best(tmp_path: Path) -> None:
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
                "retrieval = payload.get('retrieval', {})",
                "memory = (payload.get('memory') or {})",
                "top_k = int(retrieval.get('top_k', 8))",
                "memory_enabled = memory.get('enabled', True)",
                "hit_rate = 0.55 if top_k <= 8 else 0.82",
                "mrr = 0.33 if top_k <= 8 else 0.64",
                "grounded = 0.61 if top_k <= 8 else 0.88",
                "memory_completeness = 0.91 if memory_enabled else 0.42",
                "memory_freshness = 0.9 if memory_enabled else 0.5",
                "memory_stale_ratio = 0.05 if memory_enabled else 0.31",
                "composite_adjustment = 2.0 if top_k > 8 else 0.5",
                "if not memory_enabled:",
                "    composite_adjustment -= 1.0",
                "print(json.dumps({",
                "  'maintainability': {",
                "    'profile_present': True,",
                "    'memory_consistency_ok': True,",
                "    'memory_completeness': memory_completeness,",
                "    'memory_freshness': memory_freshness,",
                "    'memory_stale_ratio': memory_stale_ratio",
                "  },",
                "  'architecture': {",
                "    'snapshot_ready': True,",
                "    'vector_index_ready': True,",
                "    'db_integrity_ok': True,",
                "    'vector_coverage_ratio': 0.95,",
                "    'index_freshness_ratio': 0.92",
                "  },",
                "  'retrieval': {",
                "    'retrieval_hit_rate': hit_rate,",
                "    'retrieval_mrr': mrr,",
                "    'grounded_answer_rate': grounded",
                "  },",
                "  'composite_adjustment': composite_adjustment",
                "}))",
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
                "memory": {"enabled": True},
                "evaluation": {
                    "evaluators": ["basic", "command"],
                    "command_evaluators": [
                        {
                            "name": "benchmark-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                },
            },
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
    write_json(
        spec_path,
        {
            "experiment": "retrieval-memory-ab",
            "baseline": "baseline",
            "variants": [
                {"name": "baseline"},
                {"name": "larger_top_k", "config_patch": {"retrieval": {"top_k": 12}}},
                {
                    "name": "memory_off",
                    "config_patch": {"memory": {"enabled": False}},
                },
            ],
        },
    )
    make_task_set(task_set, workdir=str(repo_root))

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark",
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
            "--task-set",
            str(task_set),
            "--spec",
            str(spec_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)

    assert payload["experiment"] == "retrieval-memory-ab"
    assert payload["baseline"] == "baseline"
    assert payload["best_variant"] == "larger_top_k"
    assert len(payload["variants"]) == 3
    by_name = {item["name"]: item for item in payload["variants"]}
    assert by_name["baseline"]["score"]["composite"] == 1.5
    assert by_name["larger_top_k"]["score"]["composite"] == 3.0
    assert by_name["memory_off"]["score"]["composite"] == 0.5
    assert by_name["larger_top_k"]["delta_from_baseline"]["composite"] == 1.5
    assert by_name["memory_off"]["delta_from_baseline"]["composite"] == -1.0
    assert (
        by_name["memory_off"]["delta_from_baseline"]["maintainability"][
            "memory_completeness"
        ]
        == -0.49
    )
    assert (
        by_name["larger_top_k"]["delta_from_baseline"]["retrieval"][
            "retrieval_hit_rate"
        ]
        == 0.27
    )


def test_observe_benchmark_auto_compacts_runs_by_default(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    repo_root = tmp_path / "repo"
    task_set = tmp_path / "task_set.json"
    evaluator_script = tmp_path / "score_from_config.py"
    spec_path = tmp_path / "benchmark.json"
    calls: list[dict[str, object]] = []

    repo_root.mkdir(parents=True, exist_ok=True)
    evaluator_script.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "print(json.dumps({'composite_adjustment': 0.0}))",
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
                "evaluation": {
                    "evaluators": ["basic", "command"],
                    "command_evaluators": [
                        {
                            "name": "benchmark-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                },
            },
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
    write_json(
        spec_path,
        {
            "experiment": "auto-compact-benchmark",
            "baseline": "baseline",
            "variants": [{"name": "baseline"}, {"name": "variant-b"}],
        },
    )
    make_task_set(task_set, workdir=str(repo_root))

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
        return {"dry_run": False, "compacted_runs": [{"run_id": "old", "removed": ["workspace"]}]}

    monkeypatch.setattr(cli_module, "compact_runs", fake_compact_runs)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark",
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
            "--task-set",
            str(task_set),
            "--spec",
            str(spec_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["run_compaction"] == {
        "dry_run": False,
        "compacted_runs": [{"run_id": "old", "removed": ["workspace"]}],
    }
    assert calls == [
        {
            "runs_root": runs_root,
            "candidates_root": candidates_root,
            "dry_run": False,
            "experiment": None,
            "benchmark_family": None,
            "status": None,
            "include_artifacts": False,
            "compactable_statuses": None,
            "cleanup_auxiliary_dirs": True,
        }
    ]


def test_observe_benchmark_reuses_equivalent_candidates_on_repeat_runs(
    tmp_path: Path,
) -> None:
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
                "print(json.dumps({'composite_adjustment': 0.0}))",
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
                "evaluation": {
                    "evaluators": ["basic", "command"],
                    "command_evaluators": [
                        {
                            "name": "benchmark-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                },
            },
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
    write_json(
        spec_path,
        {
            "experiment": "repeat-benchmark",
            "baseline": "baseline",
            "variants": [{"name": "baseline"}, {"name": "variant-b"}],
        },
    )
    make_task_set(task_set, workdir=str(repo_root))

    runner = CliRunner()
    first = runner.invoke(
        app,
        [
            "observe",
            "benchmark",
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
            "--task-set",
            str(task_set),
            "--spec",
            str(spec_path),
        ],
    )
    second = runner.invoke(
        app,
        [
            "observe",
            "benchmark",
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
            "--task-set",
            str(task_set),
            "--spec",
            str(spec_path),
        ],
    )

    assert first.exit_code == 0
    assert second.exit_code == 0
    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)
    assert [item["candidate_id"] for item in second_payload["variants"]] == [
        item["candidate_id"] for item in first_payload["variants"]
    ]
    candidate_dirs = [path for path in candidates_root.iterdir() if path.is_dir()]
    assert len(candidate_dirs) == 2


def test_observe_benchmark_can_disable_auto_compaction(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    repo_root = tmp_path / "repo"
    task_set = tmp_path / "task_set.json"
    evaluator_script = tmp_path / "score_from_config.py"
    spec_path = tmp_path / "benchmark.json"
    calls: list[dict[str, object]] = []

    repo_root.mkdir(parents=True, exist_ok=True)
    evaluator_script.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "print(json.dumps({'composite_adjustment': 0.0}))",
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
                "evaluation": {
                    "evaluators": ["basic", "command"],
                    "command_evaluators": [
                        {
                            "name": "benchmark-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                },
            },
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
    write_json(
        spec_path,
        {
            "experiment": "auto-compact-disabled",
            "baseline": "baseline",
            "variants": [{"name": "baseline"}],
        },
    )
    make_task_set(task_set, workdir=str(repo_root))

    def fake_compact_runs(*args, **kwargs) -> dict[str, object]:
        calls.append({"args": args, "kwargs": kwargs})
        return {"dry_run": False, "compacted_runs": []}

    monkeypatch.setattr(cli_module, "compact_runs", fake_compact_runs)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark",
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
            "--task-set",
            str(task_set),
            "--spec",
            str(spec_path),
            "--no-auto-compact-runs",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert "run_compaction" not in payload
    assert calls == []


def test_observe_benchmark_v2_surfaces_variant_metadata_and_task_scenarios(
    tmp_path: Path,
) -> None:
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
                "print(json.dumps({'composite_adjustment': 1.0}))",
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
                "evaluation": {
                    "evaluators": ["basic", "command"],
                    "command_evaluators": [
                        {
                            "name": "benchmark-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                },
            },
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
    write_json(
        spec_path,
        {
            "experiment": "method-comparison",
            "baseline": "baseline",
            "analysis_mode": "architecture",
            "report": {
                "group_by": ["scenario", "variant_type"],
                "primary_axes": ["quality", "mechanism", "stability"],
            },
            "scenarios": [
                {
                    "id": "exact_symbol_lookup",
                    "label": "Exact Symbol Lookup",
                    "weight": 1.0,
                }
            ],
            "variants": [
                {"name": "baseline", "variant_type": "parameter"},
                {
                    "name": "freshness_routing_v2",
                    "variant_type": "method_family",
                    "hypothesis": "reduce stale memory interference",
                    "implementation_id": "memory-routing/freshness-v2",
                    "expected_signals": {
                        "fingerprints": {
                            "memory.routing_mode": "freshness-biased",
                        }
                    },
                    "tags": ["memory", "method-change"],
                    "config_patch": {
                        "memory": {"routing_mode": "freshness-biased"}
                    },
                },
            ],
        },
    )
    make_task_set_with_metadata(
        task_set,
        workdir=str(repo_root),
        scenario="exact_symbol_lookup",
        difficulty="hard",
        weight=1.2,
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark",
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
            "--task-set",
            str(task_set),
            "--spec",
            str(spec_path),
            "--no-auto-compact-runs",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)

    assert payload["analysis_mode"] == "architecture"
    assert payload["report"] == {
        "group_by": ["scenario", "variant_type"],
        "primary_axes": ["quality", "mechanism", "stability"],
    }
    assert payload["scenarios"] == [
        {
            "id": "exact_symbol_lookup",
            "label": "Exact Symbol Lookup",
            "weight": 1.0,
        }
    ]
    assert payload["task_scenarios"] == [
        {
            "task_id": "benchmark-task",
            "scenario": "exact_symbol_lookup",
            "difficulty": "hard",
            "weight": 1.2,
        }
    ]
    by_name = {item["name"]: item for item in payload["variants"]}
    assert by_name["baseline"]["variant_type"] == "parameter"
    assert by_name["freshness_routing_v2"]["variant_type"] == "method_family"
    assert by_name["freshness_routing_v2"]["hypothesis"] == (
        "reduce stale memory interference"
    )
    assert by_name["freshness_routing_v2"]["implementation_id"] == (
        "memory-routing/freshness-v2"
    )
    assert by_name["freshness_routing_v2"]["expected_signals"] == {
        "fingerprints": {
            "memory.routing_mode": "freshness-biased",
        }
    }
    assert by_name["freshness_routing_v2"]["tags"] == ["memory", "method-change"]


def test_observe_benchmark_supports_code_patch_variants(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    repo_root = tmp_path / "repo"
    task_set = tmp_path / "task_set.json"
    evaluator_script = tmp_path / "score_from_config.py"
    spec_path = tmp_path / "benchmark.json"
    patch_path = tmp_path / "patched-marker.diff"

    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "package.json").write_text(
        '{"name":"demo","version":"1.0.0"}', encoding="utf-8"
    )
    (repo_root / "repo_marker.txt").write_text("original\n", encoding="utf-8")
    evaluator_script.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "print(json.dumps({'composite_adjustment': 0.0}))",
            ]
        ),
        encoding="utf-8",
    )
    patch_path.write_text(
        "\n".join(
            [
                "--- a/repo_marker.txt",
                "+++ b/repo_marker.txt",
                "@@ -1 +1 @@",
                "-original",
                "+patched",
                "",
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
                "evaluation": {
                    "evaluators": ["basic", "command"],
                    "command_evaluators": [
                        {
                            "name": "benchmark-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                },
            },
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
    write_json(
        spec_path,
        {
            "experiment": "code-patch-benchmark",
            "baseline": "baseline",
            "variants": [
                {"name": "baseline"},
                {
                    "name": "patched_impl",
                    "variant_type": "implementation_patch",
                    "code_patch": str(patch_path),
                },
            ],
        },
    )
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "workspace-task",
                    "workdir": "${workspace_dir}",
                    "phases": [
                        {
                            "phase": "check_marker",
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

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark",
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
            "--task-set",
            str(task_set),
            "--spec",
            str(spec_path),
            "--no-auto-compact-runs",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    by_name = {item["name"]: item for item in payload["variants"]}
    baseline_workspace = (
        runs_root / by_name["baseline"]["run_id"] / "workspace" / "repo_marker.txt"
    )
    patched_workspace = (
        runs_root / by_name["patched_impl"]["run_id"] / "workspace" / "repo_marker.txt"
    )
    assert baseline_workspace.read_text(encoding="utf-8").strip() == "original"
    assert patched_workspace.read_text(encoding="utf-8").strip() == "patched"


def test_observe_benchmark_v2_reports_mechanism_and_validates_expected_signals(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    repo_root = tmp_path / "repo"
    task_set = tmp_path / "task_set.json"
    spec_path = tmp_path / "benchmark.json"

    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "package.json").write_text(
        '{"name":"demo","version":"1.0.0"}', encoding="utf-8"
    )
    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {
            "description": "workflow",
            "defaults": {
                "evaluation": {
                    "evaluators": ["basic"],
                },
            },
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
    write_json(
        spec_path,
        {
            "experiment": "mechanism-validation",
            "baseline": "baseline",
            "analysis_mode": "architecture",
            "variants": [
                {"name": "baseline", "variant_type": "parameter"},
                {
                    "name": "freshness_method",
                    "variant_type": "method_family",
                    "config_patch": {
                        "memory": {"routing_mode": "freshness-biased"}
                    },
                    "expected_signals": {
                        "fingerprints": {
                            "memory.routing_mode": "freshness-biased",
                        },
                        "probes": {
                            "memory.stale_filtered_count": {"min": 1},
                            "memory.routing_confidence": {"min": 0.8},
                        },
                    },
                },
            ],
        },
    )
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "mechanism-task",
                    "scenario": "memory_staleness_resistance",
                    "workdir": "${workspace_dir}",
                    "phases": [
                        {
                            "phase": "benchmark_probe",
                            "command": [
                                "python",
                                "-c",
                                (
                                    "import json, os; "
                                    "from pathlib import Path; "
                                    "cfg = json.loads(Path(os.environ['META_HARNESS_RUN_DIR']).joinpath('effective_config.json').read_text(encoding='utf-8')); "
                                    "routing = ((cfg.get('memory') or {}).get('routing_mode') or 'baseline'); "
                                    "payload = {"
                                    "'fingerprints': {'memory.routing_mode': routing}, "
                                    "'probes': {'memory.stale_filtered_count': 2 if routing == 'freshness-biased' else 0, 'memory.routing_confidence': 0.91 if routing == 'freshness-biased' else 0.4}"
                                    "}; "
                                    "print(json.dumps(payload))"
                                ),
                            ],
                        }
                    ],
                }
            ]
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark",
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
            "--task-set",
            str(task_set),
            "--spec",
            str(spec_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    by_name = {item["name"]: item for item in payload["variants"]}
    assert by_name["baseline"]["mechanism"] == {
        "fingerprints": {"memory.routing_mode": "baseline"},
        "probes": {
            "memory.routing_confidence": 0.4,
            "memory.stale_filtered_count": 0.0,
        },
        "validation": {
            "expected_signals_satisfied": True,
            "missing_signals": [],
            "mismatch_signals": [],
        },
    }
    assert by_name["freshness_method"]["mechanism"] == {
        "fingerprints": {"memory.routing_mode": "freshness-biased"},
        "probes": {
            "memory.routing_confidence": 0.91,
            "memory.stale_filtered_count": 2.0,
        },
        "validation": {
            "expected_signals_satisfied": True,
            "missing_signals": [],
            "mismatch_signals": [],
        },
    }


def test_observe_benchmark_v2_preserves_probe_degradation_validation(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    repo_root = tmp_path / "repo"
    task_set = tmp_path / "task_set.json"
    spec_path = tmp_path / "benchmark.json"

    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "package.json").write_text(
        '{"name":"demo","version":"1.0.0"}', encoding="utf-8"
    )
    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {
            "description": "workflow",
            "defaults": {
                "evaluation": {
                    "evaluators": ["basic"],
                },
            },
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
    write_json(
        spec_path,
        {
            "experiment": "probe-degradation-validation",
            "baseline": "baseline",
            "variants": [
                {"name": "baseline"},
                {
                    "name": "memory_api_degraded",
                    "variant_type": "method_family",
                    "config_patch": {
                        "memory": {"routing_mode": "legacy-incompatible"}
                    },
                },
            ],
        },
    )
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "mechanism-task",
                    "scenario": "memory_api_incompatible",
                    "workdir": "${workspace_dir}",
                    "phases": [
                        {
                            "phase": "benchmark_probe",
                            "command": [
                                "python",
                                "-c",
                                (
                                    "import json, os; "
                                    "from pathlib import Path; "
                                    "cfg = json.loads(Path(os.environ['META_HARNESS_RUN_DIR']).joinpath('effective_config.json').read_text(encoding='utf-8')); "
                                    "routing = ((cfg.get('memory') or {}).get('routing_mode') or 'baseline'); "
                                    "degraded = routing == 'legacy-incompatible'; "
                                    "payload = {"
                                    "'fingerprints': {'memory.routing_mode': routing}, "
                                    "'probes': {'memory.routing_confidence': 0.25 if degraded else 0.9}, "
                                    "'validation': {'memory_lookup_degraded': degraded, 'memory_error': 'listFeatures is not a function' if degraded else None}"
                                    "}; "
                                    "print(json.dumps(payload))"
                                ),
                            ],
                        }
                    ],
                }
            ]
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark",
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
            "--task-set",
            str(task_set),
            "--spec",
            str(spec_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    by_name = {item["name"]: item for item in payload["variants"]}
    assert by_name["baseline"]["mechanism"]["probe_validation"] == {
        "memory_lookup_degraded": False,
        "memory_error": None,
    }
    assert by_name["memory_api_degraded"]["mechanism"]["probe_validation"] == {
        "memory_lookup_degraded": True,
        "memory_error": "listFeatures is not a function",
    }
    assert by_name["memory_api_degraded"]["mechanism"]["validation"] == {
        "expected_signals_satisfied": True,
        "missing_signals": [],
        "mismatch_signals": [],
    }


def test_observe_benchmark_v2_groups_capability_gains_by_scenario(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    repo_root = tmp_path / "repo"
    task_set = tmp_path / "task_set.json"
    spec_path = tmp_path / "benchmark.json"

    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "package.json").write_text(
        '{"name":"demo","version":"1.0.0"}', encoding="utf-8"
    )
    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {
            "description": "workflow",
            "defaults": {
                "evaluation": {"evaluators": ["basic"]},
            },
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
    write_json(
        spec_path,
        {
            "experiment": "scenario-capability",
            "baseline": "baseline",
            "analysis_mode": "architecture",
            "variants": [
                {"name": "baseline"},
                {
                    "name": "memory_method",
                    "variant_type": "method_family",
                    "config_patch": {"features": {"memory_method": True}},
                },
            ],
        },
    )
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "exact-task",
                    "scenario": "exact_symbol_lookup",
                    "difficulty": "easy",
                    "weight": 1.0,
                    "workdir": "${workspace_dir}",
                    "phases": [
                        {
                            "phase": "prepare",
                            "command": ["python", "-c", "print('ok')"],
                        }
                    ],
                },
                {
                    "task_id": "memory-task",
                    "scenario": "memory_staleness_resistance",
                    "difficulty": "hard",
                    "weight": 1.5,
                    "workdir": "${workspace_dir}",
                    "phases": [
                        {
                            "phase": "prepare",
                            "command": [
                                "python",
                                "-c",
                                (
                                    "import json, os, sys; "
                                    "from pathlib import Path; "
                                    "cfg = json.loads(Path(os.environ['META_HARNESS_RUN_DIR']).joinpath('effective_config.json').read_text(encoding='utf-8')); "
                                    "enabled = ((cfg.get('features') or {}).get('memory_method') is True); "
                                    "sys.exit(0 if enabled else 1)"
                                ),
                            ],
                        }
                    ],
                },
            ]
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark",
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
            "--task-set",
            str(task_set),
            "--spec",
            str(spec_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    by_name = {item["name"]: item for item in payload["variants"]}
    assert by_name["baseline"]["capability_gains"] == {
        "exact_symbol_lookup": {
            "task_count": 1,
            "repeat_count": 1,
            "success_rate": 1.0,
            "weighted_success_rate": 1.0,
            "delta_from_baseline": {
                "success_rate": 0.0,
                "weighted_success_rate": 0.0,
            },
        },
        "memory_staleness_resistance": {
            "task_count": 1,
            "repeat_count": 1,
            "success_rate": 0.0,
            "weighted_success_rate": 0.0,
            "delta_from_baseline": {
                "success_rate": 0.0,
                "weighted_success_rate": 0.0,
            },
        },
    }
    assert by_name["memory_method"]["capability_gains"] == {
        "exact_symbol_lookup": {
            "task_count": 1,
            "repeat_count": 1,
            "success_rate": 1.0,
            "weighted_success_rate": 1.0,
            "delta_from_baseline": {
                "success_rate": 0.0,
                "weighted_success_rate": 0.0,
            },
        },
        "memory_staleness_resistance": {
            "task_count": 1,
            "repeat_count": 1,
            "success_rate": 1.0,
            "weighted_success_rate": 1.0,
            "delta_from_baseline": {
                "success_rate": 1.0,
                "weighted_success_rate": 1.0,
            },
        },
    }


def test_observe_benchmark_can_limit_output_to_requested_metric_focus(
    tmp_path: Path,
) -> None:
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
                "memory_enabled = (payload.get('memory') or {}).get('enabled', True)",
                "print(json.dumps({",
                "  'maintainability': {",
                "    'profile_present': True,",
                "    'memory_consistency_ok': True,",
                "    'memory_completeness': 0.9 if memory_enabled else 0.4,",
                "    'memory_freshness': 0.91 if memory_enabled else 0.45,",
                "    'memory_stale_ratio': 0.03 if memory_enabled else 0.3",
                "  },",
                "  'architecture': {",
                "    'snapshot_ready': True,",
                "    'vector_index_ready': True,",
                "    'db_integrity_ok': True",
                "  },",
                "  'retrieval': {",
                "    'retrieval_hit_rate': 0.81,",
                "    'retrieval_mrr': 0.63,",
                "    'grounded_answer_rate': 0.88",
                "  },",
                "  'composite_adjustment': 1.0",
                "}))",
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
                "memory": {"enabled": True},
                "evaluation": {
                    "evaluators": ["basic", "command"],
                    "command_evaluators": [
                        {
                            "name": "benchmark-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                },
            },
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
    write_json(
        spec_path,
        {
            "experiment": "memory-toggle",
            "baseline": "memory_on",
            "variants": [
                {"name": "memory_on"},
                {
                    "name": "memory_off",
                    "config_patch": {"memory": {"enabled": False}},
                },
            ],
        },
    )
    make_task_set(task_set, workdir=str(repo_root))

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark",
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
            "--task-set",
            str(task_set),
            "--spec",
            str(spec_path),
            "--focus",
            "memory",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["best_variant"] == "memory_on"
    by_name = {item["name"]: item for item in payload["variants"]}
    assert "retrieval" not in by_name["memory_off"]["delta_from_baseline"]
    assert by_name["memory_off"]["delta_from_baseline"]["maintainability"] == {
        "memory_completeness": -0.5,
        "memory_freshness": -0.46,
        "memory_stale_ratio": 0.27,
    }


def test_observe_benchmark_repeats_variants_and_reports_stability_stats(
    tmp_path: Path,
) -> None:
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
                "top_k = int((payload.get('retrieval') or {}).get('top_k', 8))",
                "bonus = 1.5 if top_k > 8 else 0.5",
                "print(json.dumps({'retrieval': {'retrieval_hit_rate': 0.8 if top_k > 8 else 0.5}, 'composite_adjustment': bonus}))",
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
                        {
                            "name": "benchmark-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                },
            },
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
    write_json(
        spec_path,
        {
            "experiment": "repeat-benchmark",
            "baseline": "baseline",
            "repeats": 2,
            "variants": [
                {"name": "baseline"},
                {"name": "larger_top_k", "config_patch": {"retrieval": {"top_k": 12}}},
            ],
        },
    )
    make_task_set(task_set, workdir=str(repo_root))

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark",
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
            "--task-set",
            str(task_set),
            "--spec",
            str(spec_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["repeat_count"] == 2
    by_name = {item["name"]: item for item in payload["variants"]}
    assert len(by_name["baseline"]["run_ids"]) == 2
    assert by_name["baseline"]["stability"] == {
        "repeat_count": 2,
        "composite_min": 1.5,
        "composite_max": 1.5,
        "composite_range": 0.0,
        "composite_stddev": 0.0,
    }
    assert by_name["larger_top_k"]["score"]["composite"] == 2.5


def test_observe_benchmark_flags_high_score_unstable_variants(
    tmp_path: Path,
) -> None:
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
                "variant = ((payload.get('proposal') or {}).get('variant_name') or 'baseline')",
                "bonus = 0.0",
                "if variant == 'spiky':",
                "    bonus = 1.5",
                "print(json.dumps({'composite_adjustment': bonus}))",
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
                "evaluation": {
                    "evaluators": ["basic", "command"],
                    "command_evaluators": [
                        {
                            "name": "benchmark-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                    "stability": {
                        "min_repeats": 3,
                        "max_composite_range": -0.1,
                        "high_score_threshold": 2.0,
                    },
                },
            },
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
    write_json(
        spec_path,
        {
            "experiment": "stability-policy",
            "baseline": "baseline",
            "repeats": 2,
            "variants": [
                {"name": "baseline"},
                {
                    "name": "spiky",
                    "config_patch": {"proposal": {"variant_name": "spiky"}},
                },
            ],
        },
    )
    make_task_set(task_set, workdir=str(repo_root))

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark",
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
            "--task-set",
            str(task_set),
            "--spec",
            str(spec_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    by_name = {item["name"]: item for item in payload["variants"]}
    assert payload["stability_policy"] == {
        "min_repeats": 3,
        "max_composite_range": -0.1,
        "high_score_threshold": 2.0,
        "range_weight": 1.0,
        "stddev_weight": 1.0,
    }
    assert by_name["baseline"]["stability_assessment"] == {
        "meets_min_repeats": False,
        "is_stable": False,
        "is_high_score_unstable": False,
    }
    assert by_name["spiky"]["stability_assessment"] == {
        "meets_min_repeats": False,
        "is_stable": False,
        "is_high_score_unstable": True,
    }


def test_observe_benchmark_downweights_high_score_unstable_variants(
    tmp_path: Path,
) -> None:
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
                "run_meta = json.loads(Path('run_metadata.json').read_text(encoding='utf-8'))",
                "variant = ((payload.get('proposal') or {}).get('variant_name') or 'baseline')",
                "bonus = 0.2",
                "if variant == 'spiky':",
                "    run_id = str(run_meta.get('run_id', '0'))",
                "    parity = int(run_id[-1], 16) % 2 if run_id[-1].lower() in '0123456789abcdef' else 0",
                "    bonus = 2.0 if parity == 0 else 0.0",
                "elif variant == 'steady':",
                "    bonus = 1.0",
                "print(json.dumps({'composite_adjustment': bonus}))",
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
                "evaluation": {
                    "evaluators": ["basic", "command"],
                    "command_evaluators": [
                        {
                            "name": "benchmark-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                    "stability": {
                        "min_repeats": 2,
                        "max_composite_range": 0.5,
                        "high_score_threshold": 2.0,
                        "unstable_high_score_penalty": 0.75,
                    },
                },
            },
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
    write_json(
        spec_path,
        {
            "experiment": "stability-penalty",
            "baseline": "baseline",
            "repeats": 2,
            "variants": [
                {"name": "baseline"},
                {
                    "name": "spiky",
                    "config_patch": {"proposal": {"variant_name": "spiky"}},
                },
                {
                    "name": "steady",
                    "config_patch": {"proposal": {"variant_name": "steady"}},
                },
            ],
        },
    )
    make_task_set(task_set, workdir=str(repo_root))

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark",
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
            "--task-set",
            str(task_set),
            "--spec",
            str(spec_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    by_name = {item["name"]: item for item in payload["variants"]}
    assert (
        by_name["spiky"]["score"]["composite"] > by_name["steady"]["score"]["composite"]
    )
    assert by_name["spiky"]["ranking_penalty"] > 0.0
    assert by_name["spiky"]["ranking_score"] < by_name["steady"]["ranking_score"]
    assert payload["best_variant"] == "steady"


def test_observe_benchmark_applies_variant_specific_stability_policy(
    tmp_path: Path,
) -> None:
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
                "run_meta = json.loads(Path('run_metadata.json').read_text(encoding='utf-8'))",
                "variant = ((payload.get('proposal') or {}).get('variant_name') or 'baseline')",
                "bonus = 1.0",
                "if variant == 'strict':",
                "    run_id = str(run_meta.get('run_id', '0'))",
                "    parity = int(run_id[-1], 16) % 2 if run_id[-1].lower() in '0123456789abcdef' else 0",
                "    bonus = 2.0 if parity == 0 else 1.0",
                "elif variant == 'lenient':",
                "    run_id = str(run_meta.get('run_id', '0'))",
                "    parity = int(run_id[-1], 16) % 2 if run_id[-1].lower() in '0123456789abcdef' else 0",
                "    bonus = 2.0 if parity == 0 else 1.0",
                "print(json.dumps({'composite_adjustment': bonus}))",
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
                "evaluation": {
                    "evaluators": ["basic", "command"],
                    "command_evaluators": [
                        {
                            "name": "benchmark-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                    "stability": {
                        "min_repeats": 2,
                        "max_composite_range": 1.0,
                        "high_score_threshold": 2.0,
                        "unstable_high_score_penalty": 0.5,
                    },
                },
            },
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
    write_json(
        spec_path,
        {
            "experiment": "variant-specific-stability-policy",
            "baseline": "baseline",
            "repeats": 2,
            "variants": [
                {"name": "baseline"},
                {
                    "name": "strict",
                    "config_patch": {
                        "proposal": {"variant_name": "strict"},
                        "evaluation": {
                            "stability": {
                                "max_composite_range": 0.5,
                                "high_score_threshold": 2.0,
                                "unstable_high_score_penalty": 0.5,
                            }
                        },
                    },
                },
                {
                    "name": "lenient",
                    "config_patch": {
                        "proposal": {"variant_name": "lenient"},
                        "evaluation": {
                            "stability": {
                                "max_composite_range": 2.0,
                                "high_score_threshold": 2.0,
                                "unstable_high_score_penalty": 0.5,
                            }
                        },
                    },
                },
            ],
        },
    )
    make_task_set(task_set, workdir=str(repo_root))

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark",
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
            "--task-set",
            str(task_set),
            "--spec",
            str(spec_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    by_name = {item["name"]: item for item in payload["variants"]}
    assert by_name["strict"]["stability_policy"]["max_composite_range"] == 0.5
    assert by_name["lenient"]["stability_policy"]["max_composite_range"] == 2.0
    assert by_name["strict"]["stability_assessment"]["is_high_score_unstable"] is True
    assert by_name["lenient"]["stability_assessment"]["is_high_score_unstable"] is False
    assert by_name["strict"]["ranking_penalty"] > 0.0
    assert by_name["lenient"]["ranking_penalty"] == 0.0


def test_observe_benchmark_downweights_high_cost_indexing_variants_in_ranking(
    tmp_path: Path,
) -> None:
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
                "indexing = payload.get('indexing', {})",
                "chunk_size = int(indexing.get('chunk_size', 1000))",
                "if chunk_size >= 1400:",
                "    composite_adjustment = 1.5",
                "    freshness = 0.97",
                "    cost = {'index_build_latency_ms': 360.0, 'index_size_bytes': 860000}",
                "elif chunk_size >= 1200:",
                "    composite_adjustment = 1.2",
                "    freshness = 0.95",
                "    cost = {'index_build_latency_ms': 230.0, 'index_size_bytes': 620000}",
                "else:",
                "    composite_adjustment = 0.9",
                "    freshness = 0.9",
                "    cost = {'index_build_latency_ms': 180.0, 'index_size_bytes': 480000}",
                "print(json.dumps({",
                "  'architecture': {'vector_coverage_ratio': 0.94, 'index_freshness_ratio': freshness},",
                "  'cost': cost,",
                "  'composite_adjustment': composite_adjustment",
                "}))",
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
                "evaluation": {
                    "evaluators": ["basic", "command"],
                    "command_evaluators": [
                        {
                            "name": "benchmark-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                    "stability": {
                        "cost_weights": {
                            "index_build_latency_ms": 0.0015,
                            "index_size_bytes": 0.000001,
                        }
                    },
                },
            },
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
    write_json(
        spec_path,
        {
            "experiment": "indexing-cost-ranking",
            "baseline": "baseline",
            "variants": [
                {"name": "baseline"},
                {
                    "name": "balanced",
                    "config_patch": {"indexing": {"chunk_size": 1200}},
                },
                {
                    "name": "heavy",
                    "config_patch": {"indexing": {"chunk_size": 1400}},
                },
            ],
        },
    )
    make_task_set(task_set, workdir=str(repo_root))

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark",
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
            "--task-set",
            str(task_set),
            "--spec",
            str(spec_path),
            "--focus",
            "indexing",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    by_name = {item["name"]: item for item in payload["variants"]}
    assert payload["best_by_quality"] == "heavy"
    assert (
        by_name["heavy"]["score"]["composite"]
        > by_name["balanced"]["score"]["composite"]
    )
    assert by_name["heavy"]["cost_penalty"] > by_name["balanced"]["cost_penalty"] > 0.0
    assert by_name["heavy"]["ranking_score"] < by_name["balanced"]["ranking_score"]
    assert payload["best_variant"] == "balanced"
    assert payload["stability_policy"]["cost_weights"] == {
        "index_build_latency_ms": 0.0015,
        "index_size_bytes": 0.000001,
    }


def test_observe_benchmark_reports_cost_stability_metrics_when_configured(
    tmp_path: Path,
) -> None:
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
                "run_meta = json.loads(Path('run_metadata.json').read_text(encoding='utf-8'))",
                "variant = ((payload.get('proposal') or {}).get('variant_name') or 'baseline')",
                "parity = int(str(run_meta.get('run_id', '0'))[-1], 16) % 2",
                "if variant == 'noisy_cost':",
                "    latency = 450.0 if parity == 0 else 180.0",
                "    size = 910000 if parity == 0 else 420000",
                "else:",
                "    latency = 200.0",
                "    size = 500000",
                "print(json.dumps({",
                "  'cost': {'index_build_latency_ms': latency, 'index_size_bytes': size},",
                "  'composite_adjustment': 1.0",
                "}))",
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
                "evaluation": {
                    "evaluators": ["basic", "command"],
                    "command_evaluators": [
                        {
                            "name": "benchmark-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                    "stability": {
                        "min_repeats": 2,
                        "max_composite_range": 0.5,
                        "cost_weights": {
                            "index_build_latency_ms": 0.0015,
                            "index_size_bytes": 0.000001,
                        },
                        "max_cost_weighted_range": 0.2,
                    },
                },
            },
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
    write_json(
        spec_path,
        {
            "experiment": "cost-stability-reporting",
            "baseline": "baseline",
            "repeats": 2,
            "variants": [
                {"name": "baseline"},
                {
                    "name": "noisy_cost",
                    "config_patch": {"proposal": {"variant_name": "noisy_cost"}},
                },
            ],
        },
    )
    make_task_set(task_set, workdir=str(repo_root))

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark",
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
            "--task-set",
            str(task_set),
            "--spec",
            str(spec_path),
            "--focus",
            "indexing",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    by_name = {item["name"]: item for item in payload["variants"]}
    assert by_name["baseline"]["stability"]["cost_weighted_range"] == 0.0
    assert by_name["noisy_cost"]["stability"]["cost_weighted_range"] == 0.895
    assert by_name["noisy_cost"]["stability"]["cost_weighted_stddev"] == 0.4475
    assert by_name["noisy_cost"]["stability_assessment"] == {
        "meets_min_repeats": True,
        "is_stable": False,
        "is_high_score_unstable": True,
        "is_cost_stable": False,
    }


def test_observe_benchmark_downweights_high_score_cost_unstable_variants(
    tmp_path: Path,
) -> None:
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
                "run_meta = json.loads(Path('run_metadata.json').read_text(encoding='utf-8'))",
                "variant = ((payload.get('proposal') or {}).get('variant_name') or 'baseline')",
                "parity = int(str(run_meta.get('run_id', '0'))[-1], 16) % 2",
                "if variant == 'spiky_cost':",
                "    bonus = 2.0",
                "    latency = 520.0 if parity == 0 else 180.0",
                "    size = 960000 if parity == 0 else 430000",
                "elif variant == 'steady_cost':",
                "    bonus = 1.7",
                "    latency = 240.0",
                "    size = 520000",
                "else:",
                "    bonus = 0.5",
                "    latency = 200.0",
                "    size = 500000",
                "print(json.dumps({",
                "  'cost': {'index_build_latency_ms': latency, 'index_size_bytes': size},",
                "  'composite_adjustment': bonus",
                "}))",
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
                "evaluation": {
                    "evaluators": ["basic", "command"],
                    "command_evaluators": [
                        {
                            "name": "benchmark-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                    "stability": {
                        "min_repeats": 2,
                        "max_composite_range": 0.5,
                        "high_score_threshold": 2.0,
                        "unstable_high_score_penalty": 0.75,
                        "cost_weights": {
                            "index_build_latency_ms": 0.0015,
                            "index_size_bytes": 0.000001,
                        },
                        "max_cost_weighted_range": 0.2,
                    },
                },
            },
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
    write_json(
        spec_path,
        {
            "experiment": "cost-stability-penalty",
            "baseline": "baseline",
            "repeats": 2,
            "variants": [
                {"name": "baseline"},
                {
                    "name": "spiky_cost",
                    "config_patch": {"proposal": {"variant_name": "spiky_cost"}},
                },
                {
                    "name": "steady_cost",
                    "config_patch": {"proposal": {"variant_name": "steady_cost"}},
                },
            ],
        },
    )
    make_task_set(task_set, workdir=str(repo_root))

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark",
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
            "--task-set",
            str(task_set),
            "--spec",
            str(spec_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    by_name = {item["name"]: item for item in payload["variants"]}
    assert by_name["spiky_cost"]["score"]["composite"] > by_name["steady_cost"]["score"][
        "composite"
    ]
    assert by_name["spiky_cost"]["stability"]["cost_weighted_range"] == 1.04
    assert by_name["spiky_cost"]["ranking_penalty"] > 0.0
    assert by_name["spiky_cost"]["ranking_score"] < by_name["steady_cost"][
        "ranking_score"
    ]
    assert payload["best_variant"] == "steady_cost"


def test_observe_benchmark_emits_report_ready_summary_fields(tmp_path: Path) -> None:
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
                "top_k = int((payload.get('retrieval') or {}).get('top_k', 8))",
                "print(json.dumps({",
                "  'retrieval': {'retrieval_hit_rate': 0.82 if top_k > 8 else 0.55},",
                "  'composite_adjustment': 1.5 if top_k > 8 else 0.2",
                "}))",
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
                "evaluation": {
                    "evaluators": ["basic", "command"],
                    "command_evaluators": [
                        {
                            "name": "benchmark-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                    "stability": {
                        "min_repeats": 2,
                        "max_composite_range": 0.25,
                        "high_score_threshold": 2.0,
                        "unstable_high_score_penalty": 0.5,
                        "stddev_weight": 1.5,
                        "range_weight": 0.75,
                    },
                },
            },
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
    write_json(
        spec_path,
        {
            "experiment": "report-ready",
            "baseline": "baseline",
            "repeats": 2,
            "variants": [
                {"name": "baseline"},
                {"name": "wide", "config_patch": {"retrieval": {"top_k": 12}}},
            ],
        },
    )
    make_task_set(task_set, workdir=str(repo_root))

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark",
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
            "--task-set",
            str(task_set),
            "--spec",
            str(spec_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["report_summary"]["best_variant"] == payload["best_variant"]
    assert payload["report_summary"]["best_by_quality"] == payload["best_by_quality"]
    assert (
        payload["report_summary"]["best_by_stability"] == payload["best_by_stability"]
    )
    assert (
        payload["report_summary"]["top_variants_by_ranking_score"][0]["name"] == "wide"
    )
    assert (
        "ranking_score" in payload["report_summary"]["top_variants_by_ranking_score"][0]
    )
    assert (
        "ranking_penalty"
        in payload["report_summary"]["top_variants_by_ranking_score"][0]
    )


def test_observe_benchmark_supports_indexing_metric_focus(tmp_path: Path) -> None:
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
                "indexing = payload.get('indexing', {})",
                "chunk_size = int(indexing.get('chunk_size', 1000))",
                "freshness = 0.96 if chunk_size > 1000 else 0.88",
                "print(json.dumps({",
                "  'architecture': {'vector_coverage_ratio': 0.94, 'index_freshness_ratio': freshness},",
                "  'cost': {'index_build_latency_ms': 280.0 if chunk_size > 1000 else 200.0, 'index_size_bytes': 640000 if chunk_size > 1000 else 480000},",
                "  'composite_adjustment': 1.0",
                "}))",
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
                "evaluation": {
                    "evaluators": ["basic", "command"],
                    "command_evaluators": [
                        {
                            "name": "benchmark-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                },
            },
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
    write_json(
        spec_path,
        {
            "experiment": "indexing-focus",
            "baseline": "baseline",
            "variants": [
                {"name": "baseline"},
                {
                    "name": "larger_chunks",
                    "config_patch": {"indexing": {"chunk_size": 1200}},
                },
            ],
        },
    )
    make_task_set(task_set, workdir=str(repo_root))

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark",
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
            "--task-set",
            str(task_set),
            "--spec",
            str(spec_path),
            "--focus",
            "indexing",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    by_name = {item["name"]: item for item in payload["variants"]}
    assert payload["best_variant"] == "larger_chunks"
    assert by_name["larger_chunks"]["delta_from_baseline"]["architecture"] == {
        "index_freshness_ratio": 0.08,
        "vector_coverage_ratio": 0.0,
    }
    assert by_name["larger_chunks"]["delta_from_baseline"]["cost"] == {
        "index_build_latency_ms": 80.0,
        "index_size_bytes": 160000.0,
    }


def test_observe_benchmark_suite_runs_multiple_specs_and_summarizes_results(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    repo_root = tmp_path / "repo"
    task_set = tmp_path / "task_set.json"
    evaluator_script = tmp_path / "score_from_config.py"
    spec_retrieval = tmp_path / "retrieval.json"
    spec_memory = tmp_path / "memory.json"
    suite_path = tmp_path / "suite.json"

    repo_root.mkdir(parents=True, exist_ok=True)
    evaluator_script.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "from pathlib import Path",
                "payload = json.loads(Path('effective_config.json').read_text(encoding='utf-8'))",
                "retrieval = payload.get('retrieval', {})",
                "memory = (payload.get('memory') or {})",
                "top_k = int(retrieval.get('top_k', 8))",
                "memory_enabled = memory.get('enabled', True)",
                "routing_mode = memory.get('routing_mode', 'baseline')",
                "hit_rate = 0.82 if top_k > 8 else 0.55",
                "mrr = 0.64 if top_k > 8 else 0.33",
                "grounded = 0.88 if top_k > 8 else 0.61",
                "memory_completeness = 0.95 if routing_mode == 'freshness-biased' else (0.42 if not memory_enabled else 0.88)",
                "memory_freshness = 0.96 if routing_mode == 'freshness-biased' else (0.5 if not memory_enabled else 0.9)",
                "memory_stale_ratio = 0.04 if routing_mode == 'freshness-biased' else (0.31 if not memory_enabled else 0.09)",
                "composite_adjustment = 2.0 if top_k > 8 else 0.5",
                "if routing_mode == 'freshness-biased':",
                "    composite_adjustment += 0.6",
                "if not memory_enabled:",
                "    composite_adjustment -= 1.0",
                "print(json.dumps({",
                "  'maintainability': {",
                "    'profile_present': True,",
                "    'memory_consistency_ok': True,",
                "    'memory_completeness': memory_completeness,",
                "    'memory_freshness': memory_freshness,",
                "    'memory_stale_ratio': memory_stale_ratio",
                "  },",
                "  'architecture': {",
                "    'snapshot_ready': True,",
                "    'vector_index_ready': True,",
                "    'db_integrity_ok': True,",
                "    'vector_coverage_ratio': 0.95,",
                "    'index_freshness_ratio': 0.92",
                "  },",
                "  'retrieval': {",
                "    'retrieval_hit_rate': hit_rate,",
                "    'retrieval_mrr': mrr,",
                "    'grounded_answer_rate': grounded",
                "  },",
                "  'composite_adjustment': composite_adjustment",
                "}))",
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
                "memory": {"enabled": True},
                "evaluation": {
                    "evaluators": ["basic", "command"],
                    "command_evaluators": [
                        {
                            "name": "suite-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                },
            },
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
    write_json(
        spec_retrieval,
        {
            "experiment": "retrieval-sweep",
            "baseline": "baseline",
            "variants": [
                {"name": "baseline"},
                {
                    "name": "retrieval_wide",
                    "config_patch": {"retrieval": {"top_k": 12}},
                },
            ],
        },
    )
    write_json(
        spec_memory,
        {
            "experiment": "memory-sweep",
            "baseline": "baseline",
            "variants": [
                {"name": "baseline"},
                {
                    "name": "freshness_bias",
                    "config_patch": {
                        "memory": {
                            "routing_mode": "freshness-biased",
                        }
                    },
                },
                {
                    "name": "memory_off",
                    "config_patch": {"memory": {"enabled": False}},
                },
            ],
        },
    )
    write_json(
        suite_path,
        {
            "suite": "default-memory-suite",
            "benchmarks": [
                {"spec": str(spec_retrieval), "focus": "retrieval"},
                {"spec": str(spec_memory), "focus": "memory"},
            ],
        },
    )
    make_task_set(task_set, workdir=str(repo_root))

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark-suite",
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
            "--task-set",
            str(task_set),
            "--suite",
            str(suite_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["suite"] == "default-memory-suite"
    assert payload["benchmark_count"] == 2
    assert payload["best_by_experiment"] == {
        "retrieval-sweep": "retrieval_wide",
        "memory-sweep": "freshness_bias",
    }
    assert payload["best_by_quality_by_experiment"] == {
        "retrieval-sweep": "retrieval_wide",
        "memory-sweep": "freshness_bias",
    }
    assert payload["best_by_stability_by_experiment"] == {
        "retrieval-sweep": "retrieval_wide",
        "memory-sweep": "freshness_bias",
    }
    assert [item["experiment"] for item in payload["benchmarks"]] == [
        "retrieval-sweep",
        "memory-sweep",
    ]


def test_observe_benchmark_suite_emits_transfer_dashboard_for_multiple_task_families(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    repo_root = tmp_path / "repo"
    task_set = tmp_path / "task_set.json"
    evaluator_script = tmp_path / "transfer_score.py"
    spec_web = tmp_path / "web_transfer.json"
    spec_analysis = tmp_path / "analysis_transfer.json"
    suite_path = tmp_path / "suite.json"

    repo_root.mkdir(parents=True, exist_ok=True)
    evaluator_script.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "from pathlib import Path",
                "payload = json.loads(Path('effective_config.json').read_text(encoding='utf-8'))",
                "binding = ((payload.get('runtime') or {}).get('binding') or {}).get('binding_id', 'baseline')",
                "workflow_primitives = (payload.get('workflow') or {}).get('primitives') or {}",
                "if 'data_analysis' in workflow_primitives:",
                "    primitive = 'data_analysis'",
                "    success = 0.93 if 'claude' in binding else 0.71",
                "    payload_rate = 0.96 if 'claude' in binding else 0.42",
                "    reply_rate = 0.91 if 'claude' in binding else 0.33",
                "    artifact_rate = 0.9 if 'claude' in binding else 0.4",
                "    latency = 1500 if 'claude' in binding else 2100",
                "else:",
                "    primitive = 'web_scrape'",
                "    success = 0.95 if 'claude' in binding else 0.74",
                "    payload_rate = 0.98 if 'claude' in binding else 0.45",
                "    reply_rate = 0.92 if 'claude' in binding else 0.36",
                "    artifact_rate = 0.94 if 'claude' in binding else 0.41",
                "    latency = 1300 if 'claude' in binding else 1900",
                "print(json.dumps({",
                "  'capability_scores': {",
                "    primitive: {",
                "      'success_rate': success,",
                "      'latency_ms': latency,",
                "      'binding_payload_rate': payload_rate,",
                "      'assistant_reply_rate': reply_rate,",
                "      'artifact_coverage_rate': artifact_rate",
                "    }",
                "  },",
                "  'workflow_scores': {",
                "    'binding_execution_rate': payload_rate,",
                "    'method_trace_coverage_rate': artifact_rate",
                "  },",
                "  'composite_adjustment': 2.0 if 'claude' in binding else 0.3",
                "}))",
            ]
        ),
        encoding="utf-8",
    )
    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "workflow.json",
        {
            "description": "workflow",
            "defaults": {
                "evaluation": {
                    "evaluators": ["basic", "command"],
                    "command_evaluators": [
                        {
                            "name": "transfer-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                },
                "runtime": {
                    "binding": {
                        "binding_id": "openclaw/codex/default",
                    }
                },
            },
        },
    )
    write_json(
        config_root / "projects" / "workflow_demo.json",
        {
            "workflow": "workflow",
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
        spec_web,
        {
            "experiment": "web-transfer",
            "baseline": "source_binding",
            "variants": [
                {"name": "source_binding"},
                {
                    "name": "target_binding",
                    "config_patch": {
                        "runtime": {
                            "binding": {
                                "binding_id": "openclaw/claude/web_scrape",
                            }
                        }
                    },
                },
            ],
        },
    )
    write_json(
        spec_analysis,
        {
            "experiment": "analysis-transfer",
            "baseline": "source_binding",
            "variants": [
                {
                    "name": "source_binding",
                    "config_patch": {
                        "workflow": {
                            "primitives": {
                                "data_analysis": {"analysis_mode": "sample_then_plan"}
                            }
                        }
                    },
                },
                {
                    "name": "target_binding",
                    "config_patch": {
                        "runtime": {
                            "binding": {
                                "binding_id": "openclaw/claude/data_analysis",
                            }
                        },
                        "workflow": {
                            "primitives": {
                                "data_analysis": {"analysis_mode": "sample_then_plan"}
                            }
                        }
                    },
                },
            ],
        },
    )
    write_json(
        suite_path,
        {
            "suite": "transfer-suite",
            "benchmarks": [
                {"spec": str(spec_web), "focus": "binding"},
                {"spec": str(spec_analysis), "focus": "binding"},
            ],
        },
    )
    make_task_set(task_set, workdir=str(repo_root))

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark-suite",
            "--profile",
            "workflow",
            "--project",
            "workflow_demo",
            "--config-root",
            str(config_root),
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
            "--task-set",
            str(task_set),
            "--suite",
            str(suite_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    dashboard = payload["transfer_dashboard"]
    assert dashboard["experiment_count"] == 2
    assert dashboard["by_primitive"]["web_scrape"] == {
        "experiment_count": 1,
        "bindings": ["openclaw/claude/web_scrape"],
        "average_binding_execution_rate": 0.98,
        "average_method_trace_coverage_rate": 0.94,
        "average_binding_payload_rate": 0.98,
        "average_assistant_reply_rate": 0.92,
        "average_artifact_coverage_rate": 0.94,
    }
    assert dashboard["by_primitive"]["data_analysis"] == {
        "experiment_count": 1,
        "bindings": ["openclaw/claude/data_analysis"],
        "average_binding_execution_rate": 0.96,
        "average_method_trace_coverage_rate": 0.9,
        "average_binding_payload_rate": 0.96,
        "average_assistant_reply_rate": 0.91,
        "average_artifact_coverage_rate": 0.9,
    }
    assert dashboard["experiments"] == [
        {
            "experiment": "analysis-transfer",
            "primitive_id": "data_analysis",
            "best_variant": "target_binding",
            "binding_id": "openclaw/claude/data_analysis",
            "focus": "binding",
            "binding_execution_rate": 0.96,
            "method_trace_coverage_rate": 0.9,
            "binding_payload_rate": 0.96,
            "assistant_reply_rate": 0.91,
            "artifact_coverage_rate": 0.9,
        },
        {
            "experiment": "web-transfer",
            "primitive_id": "web_scrape",
            "best_variant": "target_binding",
            "binding_id": "openclaw/claude/web_scrape",
            "focus": "binding",
            "binding_execution_rate": 0.98,
            "method_trace_coverage_rate": 0.94,
            "binding_payload_rate": 0.98,
            "assistant_reply_rate": 0.92,
            "artifact_coverage_rate": 0.94,
        },
    ]


def test_observe_benchmark_suite_auto_compacts_runs_by_default(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    repo_root = tmp_path / "repo"
    task_set = tmp_path / "task_set.json"
    evaluator_script = tmp_path / "score_from_config.py"
    spec_path = tmp_path / "benchmark.json"
    suite_path = tmp_path / "suite.json"
    calls: list[dict[str, object]] = []

    repo_root.mkdir(parents=True, exist_ok=True)
    evaluator_script.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "print(json.dumps({'composite_adjustment': 0.0}))",
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
                "evaluation": {
                    "evaluators": ["basic", "command"],
                    "command_evaluators": [
                        {
                            "name": "benchmark-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                },
            },
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
    write_json(
        spec_path,
        {
            "experiment": "suite-auto-compact",
            "baseline": "baseline",
            "variants": [{"name": "baseline"}],
        },
    )
    write_json(
        suite_path,
        {
            "suite": "compact-suite",
            "benchmarks": [{"spec": str(spec_path)}],
        },
    )
    make_task_set(task_set, workdir=str(repo_root))

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
        return {"dry_run": False, "compacted_runs": [{"run_id": "suite-old", "removed": ["workspace"]}]}

    monkeypatch.setattr(cli_module, "compact_runs", fake_compact_runs)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark-suite",
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
            "--task-set",
            str(task_set),
            "--suite",
            str(suite_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["run_compaction"] == {
        "dry_run": False,
        "compacted_runs": [{"run_id": "suite-old", "removed": ["workspace"]}],
    }
    assert calls == [
        {
            "runs_root": runs_root,
            "candidates_root": candidates_root,
            "dry_run": False,
            "experiment": None,
            "benchmark_family": None,
            "status": None,
            "include_artifacts": False,
            "compactable_statuses": None,
            "cleanup_auxiliary_dirs": True,
        }
    ]


def test_observe_benchmark_suite_allows_per_benchmark_task_sets(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    repo_root = tmp_path / "repo"
    default_task_set = tmp_path / "default_task_set.json"
    special_task_set = tmp_path / "special_task_set.json"
    evaluator_script = tmp_path / "score_from_task_result.py"
    first_spec = tmp_path / "first.json"
    second_spec = tmp_path / "second.json"
    suite_path = tmp_path / "suite.json"

    repo_root.mkdir(parents=True, exist_ok=True)
    evaluator_script.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "from pathlib import Path",
                "task_result = json.loads(next(Path('tasks').glob('*/task_result.json')).read_text(encoding='utf-8'))",
                "scenario = task_result.get('scenario') or 'none'",
                "bonus = 1.0 if scenario == 'special_scenario' else 0.2",
                "print(json.dumps({'retrieval': {'retrieval_hit_rate': bonus}, 'composite_adjustment': bonus}))",
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
                "evaluation": {
                    "evaluators": ["basic", "command"],
                    "command_evaluators": [
                        {
                            "name": "task-set-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                },
            },
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
    make_task_set(default_task_set, workdir=str(repo_root))
    make_task_set_with_metadata(
        special_task_set,
        workdir=str(repo_root),
        scenario="special_scenario",
    )
    write_json(
        first_spec,
        {
            "experiment": "default-task-set-benchmark",
            "baseline": "baseline",
            "variants": [{"name": "baseline"}],
        },
    )
    write_json(
        second_spec,
        {
            "experiment": "special-task-set-benchmark",
            "baseline": "baseline",
            "variants": [{"name": "baseline"}],
        },
    )
    write_json(
        suite_path,
        {
            "suite": "mixed-task-set-suite",
            "benchmarks": [
                {"spec": str(first_spec)},
                {"spec": str(second_spec), "task_set": str(special_task_set)},
            ],
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark-suite",
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
            "--task-set",
            str(default_task_set),
            "--suite",
            str(suite_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    by_experiment = {item["experiment"]: item for item in payload["benchmarks"]}
    assert by_experiment["default-task-set-benchmark"]["task_scenarios"] == []
    assert by_experiment["special-task-set-benchmark"]["task_scenarios"] == [
        {
            "task_id": "benchmark-task",
            "scenario": "special_scenario",
            "difficulty": "medium",
            "weight": 1.0,
        }
    ]
    assert (
        by_experiment["special-task-set-benchmark"]["variants"][0]["score"]["composite"]
        > by_experiment["default-task-set-benchmark"]["variants"][0]["score"][
            "composite"
        ]
    )


def test_observe_benchmark_suite_freezes_workspace_source_once_for_all_benchmarks(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    repo_root = tmp_path / "repo"
    task_set = tmp_path / "task_set.json"
    evaluator_script = tmp_path / "score_from_workspace.py"
    first_spec = tmp_path / "first.json"
    second_spec = tmp_path / "second.json"
    suite_path = tmp_path / "suite.json"

    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "package.json").write_text(
        '{"name":"demo","version":"1.0.0"}', encoding="utf-8"
    )
    (repo_root / "repo_marker.txt").write_text("original", encoding="utf-8")
    evaluator_script.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "from pathlib import Path",
                "workspace = json.loads(Path('artifacts/workspace.json').read_text(encoding='utf-8'))",
                "marker = Path(workspace['workspace_dir']).joinpath('repo_marker.txt').read_text(encoding='utf-8').strip()",
                "print(json.dumps({'composite_adjustment': 0.0 if marker == 'original' else 1.0}))",
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
                "evaluation": {
                    "evaluators": ["basic", "command"],
                    "command_evaluators": [
                        {
                            "name": "workspace-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                },
            },
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
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "freeze-check",
                    "workdir": "${workspace_dir}",
                    "phases": [
                        {
                            "phase": "prepare",
                            "command": ["python", "-c", "print('ready')"],
                        },
                        {
                            "phase": "mutate_source",
                            "command": [
                                "python",
                                "-c",
                                (
                                    "from pathlib import Path; "
                                    "Path(r'${source_repo}').joinpath('repo_marker.txt').write_text('mutated', encoding='utf-8')"
                                ),
                            ],
                        },
                    ],
                }
            ]
        },
    )
    write_json(
        first_spec,
        {
            "experiment": "first-benchmark",
            "baseline": "baseline",
            "variants": [{"name": "baseline"}],
        },
    )
    write_json(
        second_spec,
        {
            "experiment": "second-benchmark",
            "baseline": "baseline",
            "variants": [{"name": "baseline"}],
        },
    )
    write_json(
        suite_path,
        {
            "suite": "frozen-suite",
            "benchmarks": [
                {"spec": str(first_spec)},
                {"spec": str(second_spec)},
            ],
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark-suite",
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
            "--task-set",
            str(task_set),
            "--suite",
            str(suite_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    scores = [
        item["variants"][0]["score"]["composite"] for item in payload["benchmarks"]
    ]

    assert scores == [2.0, 2.0]
    assert (repo_root / "repo_marker.txt").read_text(encoding="utf-8") == "mutated"


def test_observe_benchmark_freezes_workspace_source_once_for_all_variants(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    repo_root = tmp_path / "repo"
    task_set = tmp_path / "task_set.json"
    evaluator_script = tmp_path / "score_from_workspace.py"
    spec_path = tmp_path / "benchmark.json"

    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "package.json").write_text(
        '{"name":"demo","version":"1.0.0"}', encoding="utf-8"
    )
    (repo_root / "repo_marker.txt").write_text("original", encoding="utf-8")
    evaluator_script.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "from pathlib import Path",
                "workspace = json.loads(Path('artifacts/workspace.json').read_text(encoding='utf-8'))",
                "marker = Path(workspace['workspace_dir']).joinpath('repo_marker.txt').read_text(encoding='utf-8').strip()",
                "print(json.dumps({'composite_adjustment': 0.0 if marker == 'original' else 1.0}))",
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
                "evaluation": {
                    "evaluators": ["basic", "command"],
                    "command_evaluators": [
                        {
                            "name": "workspace-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                },
            },
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
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "freeze-check",
                    "workdir": "${workspace_dir}",
                    "phases": [
                        {
                            "phase": "prepare",
                            "command": ["python", "-c", "print('ready')"],
                        },
                        {
                            "phase": "mutate_source",
                            "command": [
                                "python",
                                "-c",
                                (
                                    "from pathlib import Path; "
                                    "Path(r'${source_repo}').joinpath('repo_marker.txt').write_text('mutated', encoding='utf-8')"
                                ),
                            ],
                        },
                    ],
                }
            ]
        },
    )
    write_json(
        spec_path,
        {
            "experiment": "frozen-benchmark",
            "baseline": "baseline",
            "variants": [
                {"name": "baseline"},
                {"name": "variant-b"},
            ],
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark",
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
            "--task-set",
            str(task_set),
            "--spec",
            str(spec_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    scores = [item["score"]["composite"] for item in payload["variants"]]

    assert scores == [2.0, 2.0]
    assert (repo_root / "repo_marker.txt").read_text(encoding="utf-8") == "mutated"


def test_observe_benchmark_materializes_workspace_before_running_task_set(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    repo_root = tmp_path / "repo"
    task_set = tmp_path / "task_set.json"
    evaluator_script = tmp_path / "score_from_config.py"
    spec_path = tmp_path / "benchmark.json"

    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "package.json").write_text(
        '{"name":"demo","version":"1.0.0"}', encoding="utf-8"
    )
    (repo_root / "repo_marker.txt").write_text("from-source-repo", encoding="utf-8")
    evaluator_script.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "print(json.dumps({'composite_adjustment': 0.0}))",
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
                "evaluation": {
                    "evaluators": ["basic", "command"],
                    "command_evaluators": [
                        {
                            "name": "benchmark-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                },
            },
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
    write_json(
        spec_path,
        {
            "experiment": "workspace-materialization",
            "baseline": "baseline",
            "variants": [{"name": "baseline"}],
        },
    )
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "workspace-task",
                    "workdir": "${workspace_dir}",
                    "phases": [
                        {
                            "phase": "prepare",
                            "command": [
                                "python",
                                "-c",
                                (
                                    "from pathlib import Path; "
                                    "marker = Path('repo_marker.txt').read_text(encoding='utf-8'); "
                                    "Path('workspace_marker.txt').write_text(marker, encoding='utf-8'); "
                                    "print(marker)"
                                ),
                            ],
                        }
                    ],
                }
            ]
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark",
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
            "--task-set",
            str(task_set),
            "--spec",
            str(spec_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    run_id = payload["variants"][0]["run_id"]
    run_dir = runs_root / run_id
    task_dir = run_dir / "tasks" / "workspace-task"
    task_result = json.loads(
        (task_dir / "task_result.json").read_text(encoding="utf-8")
    )
    workspace_artifact = json.loads(
        (run_dir / "artifacts" / "workspace.json").read_text(encoding="utf-8")
    )

    assert task_result["success"] is True
    assert task_result["workdir"] == str(run_dir / "workspace")
    assert workspace_artifact["workspace_dir"] == str(run_dir / "workspace")
    assert (run_dir / "workspace" / "workspace_marker.txt").read_text(
        encoding="utf-8"
    ) == ("from-source-repo")


def test_observe_benchmark_workspace_omits_node_modules_by_default(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    repo_root = tmp_path / "repo"
    task_set = tmp_path / "task_set.json"
    evaluator_script = tmp_path / "score_from_config.py"
    spec_path = tmp_path / "benchmark.json"

    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "package.json").write_text(
        '{"name":"demo","version":"1.0.0"}', encoding="utf-8"
    )
    (repo_root / "repo_marker.txt").write_text("from-source-repo", encoding="utf-8")
    (repo_root / "node_modules").mkdir()
    (repo_root / "node_modules" / "copied.txt").write_text("too-big", encoding="utf-8")
    evaluator_script.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "print(json.dumps({'composite_adjustment': 0.0}))",
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
                "evaluation": {
                    "evaluators": ["basic", "command"],
                    "command_evaluators": [
                        {
                            "name": "benchmark-score",
                            "command": ["python", str(evaluator_script)],
                        }
                    ],
                },
            },
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
    write_json(
        spec_path,
        {
            "experiment": "workspace-excludes-node-modules",
            "baseline": "baseline",
            "variants": [{"name": "baseline"}],
        },
    )
    write_json(
        task_set,
        {
            "tasks": [
                {
                    "task_id": "workspace-task",
                    "workdir": "${workspace_dir}",
                    "phases": [
                        {
                            "phase": "prepare",
                            "command": [
                                "python",
                                "-c",
                                (
                                    "from pathlib import Path; "
                                    "assert Path('repo_marker.txt').exists(); "
                                    "assert not Path('node_modules').exists(); "
                                    "print('workspace-clean')"
                                ),
                            ],
                        }
                    ],
                }
            ]
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "observe",
            "benchmark",
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
            "--task-set",
            str(task_set),
            "--spec",
            str(spec_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    run_id = payload["variants"][0]["run_id"]
    run_dir = runs_root / run_id
    task_result = json.loads(
        (run_dir / "tasks" / "workspace-task" / "task_result.json").read_text(
            encoding="utf-8"
        )
    )

    assert task_result["success"] is True
    assert not (run_dir / "workspace" / "node_modules").exists()
