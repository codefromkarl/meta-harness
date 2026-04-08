from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from meta_harness.cli import app
from meta_harness.strategy_cards import (
    build_strategy_benchmark_spec,
    evaluate_strategy_card_compatibility,
    load_strategy_card,
    load_web_scrape_strategy_cards,
    recommend_web_scrape_strategy_cards,
    shortlist_strategy_cards,
    strategy_card_to_benchmark_variant,
)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_strategy_card_to_benchmark_variant_supports_patch_based_cards(
    tmp_path: Path,
) -> None:
    patch_path = tmp_path / "patches" / "incremental.patch"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text("--- a/a.txt\n+++ b/a.txt\n", encoding="utf-8")
    card_path = tmp_path / "incremental_refresh.json"
    write_json(
        card_path,
        {
            "strategy_id": "indexing/incremental-refresh-v1",
            "title": "Incremental Refresh",
            "source": "https://example.invalid/indexing/incremental-refresh",
            "category": "indexing",
            "change_type": "patch_based",
            "hypothesis": "incremental refresh reduces rebuild cost while preserving freshness",
            "expected_benefits": ["lower build latency"],
            "expected_costs": ["higher implementation complexity"],
            "risk_notes": ["requires snapshot consistency"],
            "code_patch": str(patch_path),
            "expected_signals": {
                "fingerprints": {"indexing.update_mode": "incremental"}
            },
            "tags": ["external", "incremental"],
        },
    )

    card = load_strategy_card(card_path)
    variant = strategy_card_to_benchmark_variant(card)

    assert variant["name"] == "indexing_incremental-refresh-v1"
    assert variant["variant_type"] == "implementation_patch"
    assert variant["implementation_id"] == "indexing/incremental-refresh-v1"
    assert variant["code_patch"] == str(patch_path)
    assert variant["expected_signals"] == {
        "fingerprints": {"indexing.update_mode": "incremental"}
    }
    assert variant["strategy_metadata"] == {
        "source": "https://example.invalid/indexing/incremental-refresh",
        "category": "indexing",
        "change_type": "patch_based",
        "compatibility": {},
        "expected_benefits": ["lower build latency"],
        "expected_costs": ["higher implementation complexity"],
        "risk_notes": ["requires snapshot consistency"],
    }
    assert variant["tags"] == [
        "external-strategy",
        "indexing",
        "patch_based",
        "external",
        "incremental",
    ]


def test_strategy_card_to_benchmark_variant_preserves_primitive_metadata(
    tmp_path: Path,
) -> None:
    card_path = tmp_path / "web_scrape_fast_path.json"
    write_json(
        card_path,
        {
            "strategy_id": "workflow/web-scrape-fast-path",
            "title": "Web Scrape Fast Path",
            "source": "https://example.invalid/workflow/web-scrape-fast-path",
            "category": "workflow",
            "primitive_id": "web_scrape",
            "capability_metadata": {
                "pack_id": "web_scrape",
                "role": "hot_path",
            },
            "change_type": "config_only",
            "config_patch": {"workflow": {"web_scrape": {"timeout_ms": 5000}}},
        },
    )

    card = load_strategy_card(card_path)
    variant = strategy_card_to_benchmark_variant(card)

    assert variant["strategy_metadata"]["primitive_id"] == "web_scrape"
    assert variant["strategy_metadata"]["capability_metadata"] == {
        "pack_id": "web_scrape",
        "role": "hot_path",
    }
    assert "web_scrape" in variant["tags"]


def test_build_strategy_benchmark_spec_skips_non_executable_cards(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "dense_chunking.json"
    research_only = tmp_path / "paper_only.json"
    write_json(
        executable,
        {
            "strategy_id": "indexing/dense-chunking-v2",
            "title": "Dense Chunking",
            "source": "https://example.invalid/indexing/dense-chunking",
            "category": "indexing",
            "change_type": "config_only",
            "config_patch": {"indexing": {"chunk_size": 1200, "chunk_overlap": 160}},
            "expected_signals": {
                "fingerprints": {"indexing.chunk_profile": "1200/160"}
            },
        },
    )
    write_json(
        research_only,
        {
            "strategy_id": "indexing/graph-posting-lists",
            "title": "Graph Posting Lists",
            "source": "https://example.invalid/indexing/graph-posting-lists",
            "category": "indexing",
            "change_type": "not_yet_executable",
            "expected_benefits": ["better graph traversal recall"],
        },
    )

    spec = build_strategy_benchmark_spec(
        experiment="external-indexing-comparison",
        baseline_name="current_indexing",
        strategy_cards=[
            load_strategy_card(executable),
            load_strategy_card(research_only),
        ],
        scenarios=[
            {"id": "index_freshness_sensitive", "label": "Index Freshness Sensitive", "weight": 1.2}
        ],
    )

    assert spec["experiment"] == "external-indexing-comparison"
    assert spec["baseline"] == "current_indexing"
    assert spec["analysis_mode"] == "architecture"
    assert spec["report"]["group_by"] == ["scenario", "variant_type"]
    assert [variant["name"] for variant in spec["variants"]] == [
        "current_indexing",
        "indexing_dense-chunking-v2",
    ]
    assert spec["variants"][1]["config_patch"] == {
        "indexing": {"chunk_size": 1200, "chunk_overlap": 160}
    }


def test_strategy_build_spec_command_writes_benchmark_spec(tmp_path: Path) -> None:
    card_path = tmp_path / "freshness_guard.json"
    output_path = tmp_path / "external_strategy_benchmark.json"
    write_json(
        card_path,
        {
            "strategy_id": "indexing/freshness-guard-v1",
            "title": "Freshness Guard",
            "source": "https://example.invalid/indexing/freshness-guard",
            "category": "indexing",
            "change_type": "config_only",
            "variant_name": "freshness_guard_external",
            "config_patch": {
                "indexing": {
                    "chunk_size": 1200,
                    "chunk_overlap": 160,
                    "freshness_guard": True,
                }
            },
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "strategy",
            "build-spec",
            "--experiment",
            "external-strategy-eval",
            "--baseline",
            "current_indexing",
            "--output",
            str(output_path),
            str(card_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["experiment"] == "external-strategy-eval"
    assert payload["baseline"] == "current_indexing"
    assert [variant["name"] for variant in payload["variants"]] == [
        "current_indexing",
        "freshness_guard_external",
    ]

def test_web_scrape_strategy_cards_load_from_directory() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    config_root = repo_root / "configs"

    cards = load_web_scrape_strategy_cards(config_root)

    assert [card.strategy_id for card in cards] == [
        "web_scrape/headless-fingerprint-proxy",
        "web_scrape/html-to-markdown-llm",
        "web_scrape/selector-only",
        "web_scrape/vlm-visual-extract",
    ]
    assert all(card.primitive_id == "web_scrape" for card in cards)
    assert all("page_profile" in card.capability_metadata for card in cards)
    assert all("workload_profile" in card.capability_metadata for card in cards)


def test_web_scrape_strategy_recommendations_match_page_and_workload_profiles(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "web scrape", "defaults": {}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )

    repo_root = Path(__file__).resolve().parents[1]
    card_paths = [
        repo_root / "configs" / "strategy_cards" / "web_scrape" / "html_to_markdown_llm.json",
        repo_root / "configs" / "strategy_cards" / "web_scrape" / "selector_only.json",
        repo_root / "configs" / "strategy_cards" / "web_scrape" / "vlm_visual_extract.json",
        repo_root
        / "configs"
        / "strategy_cards"
        / "web_scrape"
        / "headless_fingerprint_proxy.json",
    ]

    cases = [
        (
            "low-ad-hoc",
            {"content_complexity": "low", "render_required": False},
            {"usage_mode": "ad_hoc", "batch_size": 1, "project_name": "demo"},
            "web_scrape/html-to-markdown-llm",
        ),
        (
            "low-recurring",
            {"content_complexity": "low", "schema_stability": "high"},
            {"usage_mode": "recurring", "batch_size": 100, "project_name": "demo"},
            "web_scrape/selector-only",
        ),
        (
            "high-ad-hoc",
            {"content_complexity": "high", "render_required": True, "media_dependency": True},
            {"usage_mode": "ad_hoc", "batch_size": 1, "project_name": "demo"},
            "web_scrape/vlm-visual-extract",
        ),
        (
            "high-recurring",
            {
                "content_complexity": "high",
                "render_required": True,
                "interaction_required": True,
                "anti_bot_level": "high",
            },
            {"usage_mode": "recurring", "batch_size": 200, "project_name": "demo"},
            "web_scrape/headless-fingerprint-proxy",
        ),
    ]

    for _, page_profile, workload_profile, expected_strategy_id in cases:
        payload = recommend_web_scrape_strategy_cards(
            page_profile=page_profile,
            workload_profile=workload_profile,
            strategy_card_paths=card_paths,
            config_root=config_root,
            limit=1,
        )
        assert payload["selected_strategy_id"] == expected_strategy_id
        assert payload["recommendations"][0]["strategy_id"] == expected_strategy_id
        assert payload["recommendations"][0]["recommendation_score"] > 0


def test_recommend_web_scrape_strategy_cards_returns_audit_report_shape() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    payload = recommend_web_scrape_strategy_cards(
        page_profile={
            "content_complexity": "high",
            "render_required": True,
            "anti_bot_level": "high",
            "media_dependency": True,
        },
        workload_profile={
            "usage_mode": "ad_hoc",
            "budget_mode": "high_success",
        },
        config_root=repo_root / "configs",
        limit=2,
    )

    assert payload["assessment"]["page_bucket"] == "high"
    assert payload["assessment"]["workload_bucket"] == "ad_hoc"
    assert payload["primary_recommendation"]["strategy_id"] == "web_scrape/vlm-visual-extract"
    assert payload["primary_recommendation"]["expected_benefits"]
    assert payload["primary_recommendation"]["expected_costs"]
    assert payload["primary_recommendation"]["rationale"]
    assert len(payload["alternatives"]) == 1


def test_evaluate_strategy_card_compatibility_detects_missing_runtime_keys_and_paths(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {
            "description": "workflow",
            "defaults": {},
        },
    )
    write_json(
        config_root / "projects" / "demo.json",
        {
            "workflow": "base",
            "overrides": {
                "runtime": {"workspace": {"source_repo": str(repo_root)}},
            },
        },
    )
    card_path = tmp_path / "incremental.json"
    write_json(
        card_path,
        {
            "strategy_id": "indexing/incremental-v2",
            "title": "Incremental V2",
            "source": "reference://incremental-v2",
            "category": "indexing",
            "change_type": "patch_based",
            "code_patch": str(tmp_path / "missing.patch"),
            "compatibility": {
                "required_runtime_keys": [
                    "runtime.workspace.source_repo",
                    "indexing.update_mode"
                ],
                "required_paths": [
                    "src/storage/layout.ts"
                ],
            },
        },
    )

    card = load_strategy_card(card_path)
    report = evaluate_strategy_card_compatibility(
        card,
        config_root=config_root,
        profile_name="base",
        project_name="demo",
    )

    assert report["status"] == "blocked"
    assert "indexing.update_mode" in report["missing_runtime_keys"]
    assert "src/storage/layout.ts" in report["missing_paths"]
    assert report["can_benchmark"] is False
    assert report["can_create_candidate"] is False


def test_evaluate_strategy_card_compatibility_marks_review_required_cards(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "storage").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "storage" / "layout.ts").write_text(
        "export const layout = true;\n", encoding="utf-8"
    )
    patch_path = tmp_path / "relative.patch"
    patch_path.write_text("--- a/a.txt\n+++ b/a.txt\n", encoding="utf-8")
    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {
            "description": "workflow",
            "defaults": {"indexing": {"update_mode": "incremental"}},
        },
    )
    write_json(
        config_root / "projects" / "demo.json",
        {
            "workflow": "base",
            "overrides": {
                "runtime": {"workspace": {"source_repo": str(repo_root)}},
            },
        },
    )
    card_path = tmp_path / "review_required.json"
    write_json(
        card_path,
        {
            "strategy_id": "indexing/review-required",
            "title": "Review Required",
            "source": "reference://review-required",
            "category": "indexing",
            "change_type": "patch_based",
            "code_patch": str(patch_path),
            "compatibility": {
                "required_runtime_keys": [
                    "runtime.workspace.source_repo",
                    "indexing.update_mode"
                ],
                "required_paths": [
                    "src/storage/layout.ts"
                ],
                "review_required": True,
            },
        },
    )

    card = load_strategy_card(card_path)
    report = evaluate_strategy_card_compatibility(
        card,
        config_root=config_root,
        profile_name="base",
        project_name="demo",
    )

    assert report["status"] == "review_required"
    assert report["missing_runtime_keys"] == []
    assert report["missing_paths"] == []
    assert report["can_benchmark"] is True
    assert report["can_create_candidate"] is True


def test_evaluate_strategy_card_compatibility_reports_primitive_metadata(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
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
                "runtime": {"workspace": {"source_repo": str(repo_root)}},
            },
        },
    )
    card_path = tmp_path / "web_scrape_fast_path.json"
    write_json(
        card_path,
        {
            "strategy_id": "workflow/web-scrape-fast-path",
            "title": "Web Scrape Fast Path",
            "source": "https://example.invalid/workflow/web-scrape-fast-path",
            "category": "workflow",
            "primitive_id": "web_scrape",
            "capability_metadata": {
                "pack_id": "web_scrape",
                "role": "hot_path",
            },
            "change_type": "config_only",
            "config_patch": {"workflow": {"web_scrape": {"timeout_ms": 5000}}},
        },
    )

    report = evaluate_strategy_card_compatibility(
        load_strategy_card(card_path),
        config_root=config_root,
        profile_name="base",
        project_name="demo",
        strategy_card_path=card_path,
    )

    assert report["status"] == "executable"
    assert report["primitive_id"] == "web_scrape"
    assert report["capability_metadata"] == {
        "pack_id": "web_scrape",
        "role": "hot_path",
    }


def test_strategy_create_candidate_command_materializes_candidate_from_card(
    tmp_path: Path,
) -> None:
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
            "config_patch": {
                "indexing": {
                    "chunk_size": 1200,
                    "chunk_overlap": 160,
                    "freshness_guard": True,
                }
            },
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "strategy",
            "create-candidate",
            "--profile",
            "base",
            "--project",
            "demo",
            "--config-root",
            str(config_root),
            "--candidates-root",
            str(candidates_root),
            str(card_path),
        ],
    )

    assert result.exit_code == 0
    candidate_id = result.stdout.strip()
    candidate_dir = candidates_root / candidate_id
    proposal = json.loads((candidate_dir / "proposal.json").read_text(encoding="utf-8"))
    effective_config = json.loads(
        (candidate_dir / "effective_config.json").read_text(encoding="utf-8")
    )

    assert proposal["strategy"] == "external_strategy_card"
    assert proposal["strategy_id"] == "indexing/freshness-guard-v1"
    assert proposal["source"] == "reference://freshness-guard"
    assert proposal["variant_type"] == "parameter"
    assert effective_config["indexing"] == {
        "chunk_size": 1200,
        "chunk_overlap": 160,
        "freshness_guard": True,
    }


def test_strategy_create_candidate_reuses_equivalent_candidate(
    tmp_path: Path,
) -> None:
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
            "config_patch": {
                "indexing": {
                    "chunk_size": 1200,
                    "chunk_overlap": 160,
                    "freshness_guard": True,
                }
            },
        },
    )

    runner = CliRunner()
    first = runner.invoke(
        app,
        [
            "strategy",
            "create-candidate",
            "--profile",
            "base",
            "--project",
            "demo",
            "--config-root",
            str(config_root),
            "--candidates-root",
            str(candidates_root),
            str(card_path),
        ],
    )
    second = runner.invoke(
        app,
        [
            "strategy",
            "create-candidate",
            "--profile",
            "base",
            "--project",
            "demo",
            "--config-root",
            str(config_root),
            "--candidates-root",
            str(candidates_root),
            str(card_path),
        ],
    )

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert second.stdout.strip() == first.stdout.strip()
    candidate_dirs = [path for path in candidates_root.iterdir() if path.is_dir()]
    assert len(candidate_dirs) == 1


def test_strategy_create_candidate_command_blocks_incompatible_card(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    card_path = tmp_path / "blocked.json"

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
                "runtime": {"workspace": {"source_repo": str(repo_root)}},
            },
        },
    )
    write_json(
        card_path,
        {
            "strategy_id": "indexing/blocked-v1",
            "title": "Blocked",
            "source": "reference://blocked",
            "category": "indexing",
            "change_type": "config_only",
            "config_patch": {"indexing": {"chunk_size": 1200}},
            "compatibility": {
                "required_runtime_keys": ["indexing.update_mode"]
            },
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "strategy",
            "create-candidate",
            "--profile",
            "base",
            "--project",
            "demo",
            "--config-root",
            str(config_root),
            "--candidates-root",
            str(candidates_root),
            str(card_path),
        ],
    )

    assert result.exit_code != 0
    assert "missing runtime keys" in result.stdout.lower() or "missing runtime keys" in str(result.exception).lower()


def test_strategy_benchmark_command_runs_generated_spec_from_cards(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    repo_root = tmp_path / "repo"
    task_set = tmp_path / "task_set.json"
    evaluator_script = tmp_path / "score_from_config.py"
    card_path = tmp_path / "dense_chunking.json"

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
                "freshness = 0.96 if chunk_size >= 1200 else 0.88",
                "print(json.dumps({",
                "  'architecture': {'vector_coverage_ratio': 0.94, 'index_freshness_ratio': freshness},",
                "  'cost': {'index_build_latency_ms': 240.0 if chunk_size >= 1200 else 180.0},",
                "  'composite_adjustment': 1.0 if chunk_size >= 1200 else 0.2",
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
        task_set,
        {
            "tasks": [
                {
                    "task_id": "benchmark-task",
                    "scenario": "index_freshness_sensitive",
                    "difficulty": "medium",
                    "weight": 1.0,
                    "workdir": str(repo_root),
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
    write_json(
        card_path,
        {
            "strategy_id": "indexing/dense-chunking-v2",
            "title": "Dense Chunking",
            "source": "reference://dense-chunking",
            "category": "indexing",
            "change_type": "config_only",
            "config_patch": {"indexing": {"chunk_size": 1200, "chunk_overlap": 160}},
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "strategy",
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
            "--experiment",
            "external-dense-chunking",
            "--baseline",
            "current_indexing",
            str(card_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["experiment"] == "external-dense-chunking"
    assert payload["best_variant"] == "indexing_dense-chunking-v2"
    assert [variant["name"] for variant in payload["variants"]] == [
        "current_indexing",
        "indexing_dense-chunking-v2",
    ]


def test_strategy_inspect_command_reports_gate_status(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    card_path = tmp_path / "inspect.json"

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
                "runtime": {"workspace": {"source_repo": str(repo_root)}},
            },
        },
    )
    write_json(
        card_path,
        {
            "strategy_id": "indexing/inspect-v1",
            "title": "Inspect",
            "source": "reference://inspect",
            "category": "indexing",
            "change_type": "config_only",
            "config_patch": {"indexing": {"chunk_size": 1200}},
            "compatibility": {
                "required_runtime_keys": ["runtime.workspace.source_repo"],
                "review_required": True,
            },
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "strategy",
            "inspect",
            "--profile",
            "base",
            "--project",
            "demo",
            "--config-root",
            str(config_root),
            str(card_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "review_required"
    assert payload["can_benchmark"] is True
    assert payload["can_create_candidate"] is True


def test_shortlist_strategy_cards_groups_by_gate_and_priority(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "storage").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "storage" / "layout.ts").write_text(
        "export const layout = true;\n", encoding="utf-8"
    )
    patch_path = tmp_path / "review.patch"
    patch_path.write_text("--- a/a.txt\n+++ b/a.txt\n", encoding="utf-8")

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {
            "description": "workflow",
            "defaults": {"indexing": {"update_mode": "incremental"}},
        },
    )
    write_json(
        config_root / "projects" / "demo.json",
        {
            "workflow": "base",
            "overrides": {
                "runtime": {"workspace": {"source_repo": str(repo_root)}},
            },
        },
    )

    executable_path = tmp_path / "executable.json"
    review_path = tmp_path / "review.json"
    blocked_path = tmp_path / "blocked.json"
    write_json(
        executable_path,
        {
            "strategy_id": "indexing/executable",
            "title": "Executable",
            "source": "reference://executable",
            "category": "indexing",
            "group": "chunking",
            "priority": 20,
            "change_type": "config_only",
            "config_patch": {"indexing": {"chunk_size": 1200}},
        },
    )
    write_json(
        review_path,
        {
            "strategy_id": "indexing/review",
            "title": "Review",
            "source": "reference://review",
            "category": "indexing",
            "group": "incremental",
            "priority": 10,
            "change_type": "patch_based",
            "code_patch": str(patch_path),
            "compatibility": {
                "required_runtime_keys": [
                    "runtime.workspace.source_repo",
                    "indexing.update_mode",
                ],
                "required_paths": ["src/storage/layout.ts"],
                "review_required": True,
            },
        },
    )
    write_json(
        blocked_path,
        {
            "strategy_id": "indexing/blocked",
            "title": "Blocked",
            "source": "reference://blocked",
            "category": "indexing",
            "group": "graph",
            "priority": 5,
            "change_type": "config_only",
            "config_patch": {"indexing": {"chunk_size": 1400}},
            "compatibility": {
                "required_runtime_keys": ["indexing.nonexistent_mode"],
            },
        },
    )

    payload = shortlist_strategy_cards(
        strategy_card_paths=[executable_path, review_path, blocked_path],
        config_root=config_root,
        profile_name="base",
        project_name="demo",
    )

    assert payload["summary"] == {
        "total": 3,
        "executable": 1,
        "review_required": 1,
        "blocked": 1,
    }
    assert [item["strategy_id"] for item in payload["groups"]["executable"]] == [
        "indexing/executable"
    ]
    assert [item["strategy_id"] for item in payload["groups"]["review_required"]] == [
        "indexing/review"
    ]
    assert [item["strategy_id"] for item in payload["groups"]["blocked"]] == [
        "indexing/blocked"
    ]
    assert payload["groups"]["review_required"][0]["priority"] == 10
    assert payload["groups"]["review_required"][0]["group"] == "incremental"
    assert payload["groups"]["blocked"][0]["missing_runtime_keys"] == [
        "indexing.nonexistent_mode"
    ]


def test_strategy_shortlist_command_reports_grouped_cards(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
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
                "runtime": {"workspace": {"source_repo": str(repo_root)}},
            },
        },
    )
    executable_path = tmp_path / "b.json"
    blocked_path = tmp_path / "a.json"
    write_json(
        executable_path,
        {
            "strategy_id": "indexing/b",
            "title": "B",
            "source": "reference://b",
            "category": "indexing",
            "priority": 20,
            "change_type": "config_only",
            "config_patch": {"indexing": {"chunk_size": 1200}},
        },
    )
    write_json(
        blocked_path,
        {
            "strategy_id": "indexing/a",
            "title": "A",
            "source": "reference://a",
            "category": "indexing",
            "priority": 10,
            "change_type": "config_only",
            "config_patch": {"indexing": {"chunk_size": 800}},
            "compatibility": {"required_runtime_keys": ["indexing.update_mode"]},
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "strategy",
            "shortlist",
            "--profile",
            "base",
            "--project",
            "demo",
            "--config-root",
            str(config_root),
            str(executable_path),
            str(blocked_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["summary"]["total"] == 2
    assert payload["summary"]["blocked"] == 1
    assert payload["groups"]["executable"][0]["strategy_id"] == "indexing/b"
    assert payload["groups"]["blocked"][0]["strategy_id"] == "indexing/a"


def test_strategy_recommend_web_scrape_command_reports_recommendations(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    page_profile_path = tmp_path / "page_profile.json"
    workload_profile_path = tmp_path / "workload_profile.json"
    write_json(
        page_profile_path,
        {
            "complexity": "low",
            "requires_rendering": False,
            "anti_bot_level": "low",
        },
    )
    write_json(
        workload_profile_path,
        {
            "usage_mode": "recurring",
            "batch_size": 50,
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "strategy",
            "recommend-web-scrape",
            "--page-profile",
            str(page_profile_path),
            "--workload-profile",
            str(workload_profile_path),
            "--config-root",
            str(repo_root / "configs"),
            "--limit",
            "2",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["selected_strategy_id"] == "web_scrape/selector-only"
    assert len(payload["recommendations"]) == 2
    assert payload["assessment"]["workload_bucket"] == "recurring"
    assert payload["primary_recommendation"]["strategy_id"] == "web_scrape/selector-only"


def test_strategy_audit_web_scrape_command_reports_alignment(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    page_profile_path = tmp_path / "page_profile.json"
    workload_profile_path = tmp_path / "workload_profile.json"
    benchmark_report_path = tmp_path / "benchmark.json"
    write_json(
        page_profile_path,
        {
            "complexity": "high",
            "requires_rendering": True,
            "anti_bot_level": "high",
        },
    )
    write_json(
        workload_profile_path,
        {
            "usage_mode": "ad_hoc",
        },
    )
    write_json(
        benchmark_report_path,
        {
            "experiment": "web-scrape-audit",
            "best_variant": "selector_only",
            "best_by_quality": "selector_only",
            "best_by_stability": "selector_only",
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "strategy",
            "audit-web-scrape",
            "--page-profile",
            str(page_profile_path),
            "--workload-profile",
            str(workload_profile_path),
            "--benchmark-report",
            str(benchmark_report_path),
            "--config-root",
            str(repo_root / "configs"),
            "--limit",
            "2",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["primary_recommendation"]["strategy_id"] == "web_scrape/vlm-visual-extract"
    assert payload["alignment"]["benchmark_best_variant"] == "selector_only"
    assert payload["alignment"]["aligned"] is False


def test_strategy_build_web_scrape_audit_spec_command_writes_spec(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    page_profile_path = tmp_path / "page_profile.json"
    workload_profile_path = tmp_path / "workload_profile.json"
    output_path = tmp_path / "web-scrape-benchmark.json"
    write_json(
        page_profile_path,
        {
            "complexity": "low",
            "requires_rendering": False,
        },
    )
    write_json(
        workload_profile_path,
        {
            "usage_mode": "recurring",
            "batch_size": 50,
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "strategy",
            "build-web-scrape-audit-spec",
            "--page-profile",
            str(page_profile_path),
            "--workload-profile",
            str(workload_profile_path),
            "--output",
            str(output_path),
            "--config-root",
            str(repo_root / "configs"),
            "--limit",
            "2",
            "--repeats",
            "2",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["output_path"] == str(output_path)
    assert payload["benchmark_spec"]["repeats"] == 2
    assert output_path.exists()
