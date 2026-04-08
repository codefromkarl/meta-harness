from __future__ import annotations

import json
from pathlib import Path

import pytest

from meta_harness.scoring import score_run
from meta_harness.retrieval_dataset_evaluator import evaluate_retrieval_dataset_run


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_steps(task_dir: Path, latency_ms: int) -> None:
    (task_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "step_id": "step-1",
                "phase": "benchmark_probe",
                "status": "completed",
                "latency_ms": latency_ms,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def make_run(run_dir: Path) -> None:
    write_json(
        run_dir / "run_metadata.json",
        {"run_id": run_dir.name, "profile": "benchmark", "project": "demo"},
    )


def make_retrieval_task(
    run_dir: Path,
    *,
    task_id: str,
    scenario: str,
    dataset_case: dict,
    observation: dict,
    success: bool = True,
    latency_ms: int = 120,
) -> None:
    task_dir = run_dir / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        task_dir / "task_result.json",
        {
            "task_id": task_id,
            "scenario": scenario,
            "success": success,
            "dataset_case": dataset_case,
        },
    )
    write_json(
        task_dir / "benchmark_probe.stdout.txt",
        {"validation": {"dataset_cases": [observation]}},
    )
    write_steps(task_dir, latency_ms=latency_ms)


def test_evaluate_retrieval_dataset_run_scores_rank_paths_and_grounding(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-retrieval"
    make_run(run_dir)
    make_retrieval_task(
        run_dir,
        task_id="exact-symbol-lookup",
        scenario="exact_symbol_lookup",
        dataset_case={
            "query": "codebase retrieval SearchService build context pack",
            "expected_paths": ["src/mcp/tools/codebaseRetrieval.ts"],
            "expected_rank_max": 3,
            "expected_grounding_refs": ["src/mcp/tools/codebaseRetrieval.ts#L1"],
            "expected_answer_contains": ["codebaseRetrieval", "SearchService"],
        },
        observation={
            "query": "codebase retrieval SearchService build context pack",
            "returnedPaths": [
                "noise/a.ts",
                "src/mcp/tools/codebaseRetrieval.ts",
            ],
            "matchedPaths": ["src/mcp/tools/codebaseRetrieval.ts"],
            "bestRank": 2,
            "groundingRefs": ["src/mcp/tools/codebaseRetrieval.ts#L1"],
            "answerText": "SearchService codebaseRetrieval",
        },
    )

    report = evaluate_retrieval_dataset_run(run_dir)

    assert report["correctness"]["retrieval_dataset_hit_rate"] == pytest.approx(1.0)
    assert report["correctness"]["retrieval_dataset_rank_satisfied_rate"] == pytest.approx(
        1.0
    )
    assert report["correctness"]["retrieval_dataset_grounding_coverage_rate"] == pytest.approx(
        1.0
    )
    assert report["correctness"]["retrieval_dataset_answer_match_rate"] == pytest.approx(
        1.0
    )
    assert report["capability_scores"]["retrieval_dataset"]["path_coverage_rate"] == pytest.approx(
        1.0
    )
    assert report["probes"]["retrieval_dataset.case_count"] == 1.0
    assert report["composite_adjustment"] > 0.5


def test_evaluate_retrieval_dataset_run_prefers_cli_retrieval_probe_for_rank_order(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-retrieval-cli"
    make_run(run_dir)
    make_retrieval_task(
        run_dir,
        task_id="exact-symbol-lookup",
        scenario="exact_symbol_lookup",
        dataset_case={
            "query": "codebase retrieval SearchService build context pack",
            "expected_paths": ["src/mcp/tools/codebaseRetrieval.ts"],
            "expected_rank_max": 2,
            "expected_grounding_refs": ["src/mcp/tools/codebaseRetrieval.ts#L1"],
        },
        observation={
            "query": "codebase retrieval SearchService build context pack",
            "returnedPaths": ["noise/a.ts", "noise/b.ts", "src/mcp/tools/codebaseRetrieval.ts"],
            "matchedPaths": ["src/mcp/tools/codebaseRetrieval.ts"],
            "bestRank": 3,
            "groundingRefs": ["src/mcp/tools/codebaseRetrieval.ts#L1"],
            "answerText": "fallback observation",
        },
    )
    task_dir = run_dir / "tasks" / "exact-symbol-lookup"
    write_json(
        task_dir / "cli_retrieval_probe.stdout.txt",
        {
            "tool": "codebase-retrieval",
            "repo_path": "/repo",
            "information_request": "codebase retrieval SearchService build context pack",
            "technical_terms": [],
            "content": [
                {
                    "type": "text",
                    "text": (
                        "## Retrieval Overview\n"
                        "### Top Files\n"
                        "- src/mcp/tools/codebaseRetrieval.ts\n"
                        "- noise/a.ts\n"
                    ),
                }
            ],
            "text": (
                "## Retrieval Overview\n"
                "### Top Files\n"
                "- src/mcp/tools/codebaseRetrieval.ts\n"
                "- noise/a.ts\n"
            ),
        },
    )

    report = evaluate_retrieval_dataset_run(run_dir)

    assert report["correctness"]["retrieval_dataset_rank_satisfied_rate"] == pytest.approx(
        1.0
    )
    assert report["capability_scores"]["retrieval_dataset"]["path_coverage_rate"] == pytest.approx(
        1.0
    )


def test_evaluate_retrieval_dataset_run_prefers_mcp_retrieval_probe_over_cli(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-retrieval-mcp"
    make_run(run_dir)
    make_retrieval_task(
        run_dir,
        task_id="exact-symbol-lookup",
        scenario="exact_symbol_lookup",
        dataset_case={
            "query": "codebase retrieval SearchService build context pack",
            "expected_paths": ["src/mcp/tools/codebaseRetrieval.ts"],
            "expected_rank_max": 1,
            "expected_grounding_refs": ["src/mcp/tools/codebaseRetrieval.ts#L1"],
        },
        observation={
            "query": "codebase retrieval SearchService build context pack",
            "returnedPaths": ["noise/a.ts", "noise/b.ts", "src/mcp/tools/codebaseRetrieval.ts"],
            "matchedPaths": ["src/mcp/tools/codebaseRetrieval.ts"],
            "bestRank": 3,
            "groundingRefs": ["src/mcp/tools/codebaseRetrieval.ts#L1"],
            "answerText": "fallback observation",
        },
    )
    task_dir = run_dir / "tasks" / "exact-symbol-lookup"
    write_json(
        task_dir / "cli_retrieval_probe.stdout.txt",
        {
            "tool": "codebase-retrieval",
            "repo_path": "/repo",
            "information_request": "codebase retrieval SearchService build context pack",
            "technical_terms": [],
            "content": [{"type": "text", "text": "### Top Files\n- noise/a.ts"}],
            "text": "### Top Files\n- noise/a.ts",
        },
    )
    write_json(
        task_dir / "mcp_retrieval_probe.stdout.txt",
        {
            "tool": "codebase-retrieval",
            "transport": "mcp",
            "query": "codebase retrieval SearchService build context pack",
            "topFiles": ["src/mcp/tools/codebaseRetrieval.ts", "noise/a.ts"],
            "groundingRefs": ["src/mcp/tools/codebaseRetrieval.ts#L1"],
            "text": "structured mcp artifact",
        },
    )

    report = evaluate_retrieval_dataset_run(run_dir)

    assert report["correctness"]["retrieval_dataset_rank_satisfied_rate"] == pytest.approx(
        1.0
    )
    assert report["correctness"]["retrieval_dataset_grounding_coverage_rate"] == pytest.approx(
        1.0
    )


def test_evaluate_retrieval_dataset_run_penalizes_missing_rank_and_grounding(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-retrieval-poor"
    make_run(run_dir)
    make_retrieval_task(
        run_dir,
        task_id="cross-file-dependency-trace",
        scenario="cross_file_dependency_trace",
        dataset_case={
            "query": "trace search service dependencies across retrieval and memory routing components",
            "expected_paths": [
                "src/search/SearchService.ts",
                "src/memory/MemoryRouter.ts",
            ],
            "expected_rank_max": 2,
            "expected_grounding_refs": [
                "src/search/SearchService.ts#L1",
                "src/memory/MemoryRouter.ts#L1",
            ],
            "expected_answer_contains": ["SearchService", "MemoryRouter"],
        },
        observation={
            "query": "trace search service dependencies across retrieval and memory routing components",
            "returnedPaths": ["src/search/SearchService.ts", "noise/a.ts"],
            "matchedPaths": ["src/search/SearchService.ts"],
            "bestRank": 4,
            "groundingRefs": [],
            "answerText": "SearchService only",
        },
        latency_ms=260,
    )

    report = evaluate_retrieval_dataset_run(run_dir)

    capability = report["capability_scores"]["retrieval_dataset"]
    assert capability["path_coverage_rate"] == pytest.approx(0.5)
    assert report["correctness"]["retrieval_dataset_rank_satisfied_rate"] == pytest.approx(
        0.0
    )
    assert report["correctness"]["retrieval_dataset_grounding_coverage_rate"] == pytest.approx(
        0.0
    )
    assert report["correctness"]["retrieval_dataset_answer_match_rate"] == pytest.approx(
        0.5
    )
    assert report["composite_adjustment"] < 0.5


def test_score_run_executes_relative_retrieval_dataset_script_from_source_repo(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    run_dir = tmp_path / "runs" / "run-retrieval-pack"
    make_run(run_dir)
    make_retrieval_task(
        run_dir,
        task_id="exact-symbol-lookup",
        scenario="exact_symbol_lookup",
        dataset_case={
            "query": "codebase retrieval SearchService build context pack",
            "expected_paths": ["src/mcp/tools/codebaseRetrieval.ts"],
            "expected_rank_max": 3,
        },
        observation={
            "query": "codebase retrieval SearchService build context pack",
            "returnedPaths": ["src/mcp/tools/codebaseRetrieval.ts"],
            "matchedPaths": ["src/mcp/tools/codebaseRetrieval.ts"],
            "bestRank": 1,
            "groundingRefs": ["src/mcp/tools/codebaseRetrieval.ts#L1"],
            "answerText": "SearchService codebaseRetrieval",
        },
    )
    write_json(
        run_dir / "effective_config.json",
        {
            "runtime": {
                "workspace": {
                    "source_repo": str(repo_root),
                }
            },
            "evaluation": {
                "evaluators": ["command"],
                "command_evaluators": [
                    {
                        "name": "retrieval-dataset/core",
                        "command": ["python", "scripts/eval_retrieval_dataset.py"],
                    }
                ],
            },
        },
    )

    report = score_run(run_dir)

    assert report["correctness"]["retrieval_dataset_hit_rate"] == pytest.approx(1.0)
    assert (
        report["capability_scores"]["retrieval_dataset"]["path_coverage_rate"]
        == pytest.approx(1.0)
    )
    assert report["cost"]["command_evaluators_run"] == 1
