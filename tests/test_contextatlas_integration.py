from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from meta_harness.scoring import score_run


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_contextatlas_command_evaluator_scores_profile_and_index_health(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-ctx"
    task_dir = run_dir / "tasks" / "contextatlas-maintenance"
    task_dir.mkdir(parents=True)

    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "contextatlas_run_eval.py"
    )
    write_json(
        run_dir / "effective_config.json",
        {
            "evaluation": {
                "evaluators": ["basic", "command"],
                "command_evaluators": [
                    {
                        "name": "contextatlas-health",
                        "command": ["python", str(script_path)],
                    }
                ],
            }
        },
    )
    write_json(
        run_dir / "run_metadata.json",
        {
            "run_id": "run-ctx",
            "profile": "contextatlas_maintenance",
            "project": "contextatlas",
        },
    )

    (task_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "step_id": "step-1",
                "phase": "health_check",
                "status": "completed",
                "latency_ms": 12,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (task_dir / "show_profile.stdout.txt").write_text(
        "项目：ContextAtlas\n描述：Imported from .omc/project-memory.json\n",
        encoding="utf-8",
    )
    (task_dir / "check_memory.stdout.txt").write_text(
        "memory consistency check: OK\n",
        encoding="utf-8",
    )
    (task_dir / "health_check.stdout.txt").write_text(
        json.dumps(
            {
                "snapshots": [
                    {
                        "hasCurrentSnapshot": True,
                        "hasVectorIndex": True,
                        "dbIntegrity": "ok",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = score_run(run_dir)

    assert report["maintainability"]["profile_present"] is True
    assert report["maintainability"]["memory_consistency_ok"] is True
    assert report["architecture"]["snapshot_ready"] is True
    assert report["architecture"]["vector_index_ready"] is True
    assert report["architecture"]["db_integrity_ok"] is True
    assert report["cost"]["command_evaluators_run"] == 1
    assert report["composite"] == 4.0


def test_contextatlas_command_evaluator_records_richer_index_memory_and_retrieval_metrics(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-rich"
    task_dir = run_dir / "tasks" / "contextatlas-maintenance"
    task_dir.mkdir(parents=True)

    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "contextatlas_run_eval.py"
    )
    write_json(
        run_dir / "effective_config.json",
        {
            "evaluation": {
                "evaluators": ["basic", "command"],
                "command_evaluators": [
                    {
                        "name": "contextatlas-health",
                        "command": ["python", str(script_path)],
                    }
                ],
            }
        },
    )
    write_json(
        run_dir / "run_metadata.json",
        {
            "run_id": "run-rich",
            "profile": "contextatlas_maintenance",
            "project": "contextatlas",
        },
    )

    (task_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "step_id": "step-1",
                "phase": "health_check",
                "status": "completed",
                "latency_ms": 12,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (task_dir / "show_profile.stdout.txt").write_text(
        "项目：ContextAtlas\n描述：Imported from .omc/project-memory.json\n最后更新：2026/4/5 09:30:00\n",
        encoding="utf-8",
    )
    (task_dir / "check_memory.stdout.txt").write_text(
        'Catalog 构建完成 {"moduleCount":42,"scopeCount":3}\nmemory consistency check: OK\n',
        encoding="utf-8",
    )
    (task_dir / "health_check.stdout.txt").write_text(
        json.dumps(
            {
                "snapshots": [
                    {
                        "hasCurrentSnapshot": True,
                        "hasVectorIndex": True,
                        "dbIntegrity": "ok",
                    }
                ],
                "indexing": {
                    "documentCount": 128,
                    "chunkCount": 960,
                    "coverageRatio": 0.94,
                    "freshnessRatio": 0.91,
                },
                "memory": {
                    "moduleCount": 42,
                    "scopeCount": 3,
                    "completeness": 0.88,
                    "freshness": 0.93,
                    "staleRatio": 0.04,
                },
                "retrieval": {
                    "hitRate": 0.79,
                    "mrr": 0.63,
                    "groundedAnswerRate": 0.86,
                },
            }
        ),
        encoding="utf-8",
    )

    report = score_run(run_dir)

    assert report["maintainability"]["memory_module_count"] == 42
    assert report["maintainability"]["memory_scope_count"] == 3
    assert report["maintainability"]["memory_completeness"] == 0.88
    assert report["maintainability"]["memory_freshness"] == 0.93
    assert report["maintainability"]["memory_stale_ratio"] == 0.04
    assert report["architecture"]["index_document_count"] == 128
    assert report["architecture"]["index_chunk_count"] == 960
    assert report["architecture"]["vector_coverage_ratio"] == 0.94
    assert report["architecture"]["index_freshness_ratio"] == 0.91
    assert report["retrieval"]["retrieval_hit_rate"] == 0.79
    assert report["retrieval"]["retrieval_mrr"] == 0.63
    assert report["retrieval"]["grounded_answer_rate"] == 0.86
    assert report["composite"] == 5.5


def test_contextatlas_command_evaluator_merges_benchmark_probe_metrics(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-probe"
    task_dir = run_dir / "tasks" / "contextatlas-benchmark"
    task_dir.mkdir(parents=True)

    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "contextatlas_run_eval.py"
    )
    write_json(
        run_dir / "effective_config.json",
        {
            "evaluation": {
                "evaluators": ["basic", "command"],
                "command_evaluators": [
                    {
                        "name": "contextatlas-health",
                        "command": ["python", str(script_path)],
                    }
                ],
            }
        },
    )
    write_json(
        run_dir / "run_metadata.json",
        {
            "run_id": "run-probe",
            "profile": "contextatlas_benchmark",
            "project": "contextatlas_benchmark",
        },
    )

    (task_dir / "steps.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "step_id": "step-1",
                        "phase": "health_check",
                        "status": "completed",
                        "latency_ms": 12,
                    }
                ),
                json.dumps(
                    {
                        "step_id": "step-2",
                        "phase": "benchmark_probe",
                        "status": "completed",
                        "latency_ms": 18,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (task_dir / "show_profile.stdout.txt").write_text(
        "项目：ContextAtlas\n描述：Imported from .omc/project-memory.json\n",
        encoding="utf-8",
    )
    (task_dir / "check_memory.stdout.txt").write_text(
        "memory consistency check: OK\n",
        encoding="utf-8",
    )
    (task_dir / "health_check.stdout.txt").write_text(
        json.dumps(
            {
                "snapshots": [
                    {
                        "hasCurrentSnapshot": True,
                        "hasVectorIndex": True,
                        "dbIntegrity": "ok",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (task_dir / "benchmark_probe.stdout.txt").write_text(
        json.dumps(
            {
                "indexing": {
                    "documentCount": 140,
                    "chunkCount": 2122,
                    "coverageRatio": 0.97,
                    "freshnessRatio": 1.0,
                },
                "memory": {
                    "moduleCount": 1,
                    "scopeCount": 1,
                    "completeness": 1.0,
                    "freshness": 1.0,
                    "staleRatio": 0.0,
                },
                "retrieval": {
                    "hitRate": 0.74,
                    "mrr": 0.58,
                    "groundedAnswerRate": 1.0,
                },
                "cost": {
                    "indexBuildLatencyMs": 245.0,
                    "indexPeakMemoryMb": 96.5,
                    "indexSizeBytes": 524288,
                    "indexEmbeddingCalls": 2122,
                    "indexFilesScannedCount": 140,
                    "indexFilesReindexedCount": 140,
                    "indexQueryP50Ms": 18.0,
                    "indexQueryP95Ms": 33.0,
                },
            }
        ),
        encoding="utf-8",
    )

    report = score_run(run_dir)

    assert report["architecture"]["index_document_count"] == 140
    assert report["architecture"]["index_chunk_count"] == 2122
    assert report["architecture"]["vector_coverage_ratio"] == 0.97
    assert report["architecture"]["index_freshness_ratio"] == 1.0
    assert report["maintainability"]["memory_completeness"] == 1.0
    assert report["maintainability"]["memory_freshness"] == 1.0
    assert report["maintainability"]["memory_stale_ratio"] == 0.0
    assert report["retrieval"]["retrieval_hit_rate"] == 0.74
    assert report["retrieval"]["retrieval_mrr"] == 0.58
    assert report["retrieval"]["grounded_answer_rate"] == 1.0
    assert report["cost"]["index_build_latency_ms"] == 245.0
    assert report["cost"]["index_peak_memory_mb"] == 96.5
    assert report["cost"]["index_size_bytes"] == 524288
    assert report["cost"]["index_embedding_calls"] == 2122
    assert report["cost"]["index_files_scanned_count"] == 140
    assert report["cost"]["index_files_reindexed_count"] == 140
    assert report["cost"]["index_query_p50_ms"] == 18.0
    assert report["cost"]["index_query_p95_ms"] == 33.0
    assert report["composite"] == 6.5


def test_contextatlas_command_evaluator_averages_multi_task_benchmark_metrics(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-probe-aggregate"
    task_a = run_dir / "tasks" / "scenario-a"
    task_b = run_dir / "tasks" / "scenario-b"
    task_a.mkdir(parents=True)
    task_b.mkdir(parents=True)

    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "contextatlas_run_eval.py"
    )
    write_json(
        run_dir / "effective_config.json",
        {
            "evaluation": {
                "evaluators": ["basic", "command"],
                "command_evaluators": [
                    {
                        "name": "contextatlas-health",
                        "command": ["python", str(script_path)],
                    }
                ],
            }
        },
    )
    write_json(
        run_dir / "run_metadata.json",
        {
            "run_id": "run-probe-aggregate",
            "profile": "contextatlas_benchmark",
            "project": "contextatlas_benchmark",
        },
    )

    for task_dir in (task_a, task_b):
        (task_dir / "steps.jsonl").write_text(
            json.dumps(
                {
                    "step_id": "step-1",
                    "phase": "benchmark_probe",
                    "status": "completed",
                    "latency_ms": 18,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (task_dir / "show_profile.stdout.txt").write_text(
            "项目：ContextAtlas\n描述：Imported from .omc/project-memory.json\n",
            encoding="utf-8",
        )
        (task_dir / "check_memory.stdout.txt").write_text(
            "memory consistency check: OK\n",
            encoding="utf-8",
        )
        (task_dir / "health_check.stdout.txt").write_text(
            json.dumps(
                {
                    "snapshots": [
                        {
                            "hasCurrentSnapshot": True,
                            "hasVectorIndex": True,
                            "dbIntegrity": "ok",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    (task_a / "benchmark_probe.stdout.txt").write_text(
        json.dumps(
            {
                "retrieval": {
                    "hitRate": 0.8,
                    "mrr": 0.7,
                    "groundedAnswerRate": 0.9,
                },
                "taskQuality": {
                    "taskSuccessRate": 0.8,
                    "taskGroundedSuccessRate": 0.6,
                    "taskCaseCount": 5,
                },
            }
        ),
        encoding="utf-8",
    )
    (task_b / "benchmark_probe.stdout.txt").write_text(
        json.dumps(
            {
                "retrieval": {
                    "hitRate": 0.6,
                    "mrr": 0.5,
                    "groundedAnswerRate": 0.7,
                },
                "taskQuality": {
                    "taskSuccessRate": 0.4,
                    "taskGroundedSuccessRate": 0.2,
                    "taskCaseCount": 4,
                },
            }
        ),
        encoding="utf-8",
    )

    report = score_run(run_dir)

    assert report["retrieval"]["retrieval_hit_rate"] == 0.7
    assert report["retrieval"]["retrieval_mrr"] == 0.6
    assert report["retrieval"]["grounded_answer_rate"] == 0.8
    assert report["correctness"]["task_success_rate"] == 0.6
    assert report["correctness"]["task_grounded_success_rate"] == 0.4
    assert report["correctness"]["task_case_count"] == 9


def test_contextatlas_command_evaluator_records_task_level_quality_metrics(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-task-quality"
    task_dir = run_dir / "tasks" / "contextatlas-benchmark"
    task_dir.mkdir(parents=True)

    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "contextatlas_run_eval.py"
    )
    write_json(
        run_dir / "effective_config.json",
        {
            "evaluation": {
                "evaluators": ["basic", "command"],
                "command_evaluators": [
                    {
                        "name": "contextatlas-health",
                        "command": ["python", str(script_path)],
                    }
                ],
            }
        },
    )
    write_json(
        run_dir / "run_metadata.json",
        {
            "run_id": "run-task-quality",
            "profile": "contextatlas_benchmark",
            "project": "contextatlas_benchmark",
        },
    )

    (task_dir / "steps.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "step_id": "step-1",
                        "phase": "health_check",
                        "status": "completed",
                        "latency_ms": 12,
                    }
                ),
                json.dumps(
                    {
                        "step_id": "step-2",
                        "phase": "benchmark_probe",
                        "status": "completed",
                        "latency_ms": 18,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (task_dir / "show_profile.stdout.txt").write_text(
        "项目：ContextAtlas\n描述：Imported from .omc/project-memory.json\n",
        encoding="utf-8",
    )
    (task_dir / "check_memory.stdout.txt").write_text(
        "memory consistency check: OK\n",
        encoding="utf-8",
    )
    (task_dir / "health_check.stdout.txt").write_text(
        json.dumps(
            {
                "snapshots": [
                    {
                        "hasCurrentSnapshot": True,
                        "hasVectorIndex": True,
                        "dbIntegrity": "ok",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (task_dir / "benchmark_probe.stdout.txt").write_text(
        json.dumps(
            {
                "taskQuality": {
                    "taskSuccessRate": 0.75,
                    "taskGroundedSuccessRate": 0.5,
                    "taskCaseCount": 8,
                }
            }
        ),
        encoding="utf-8",
    )

    report = score_run(run_dir)

    assert report["correctness"]["task_success_rate"] == 0.75
    assert report["correctness"]["task_grounded_success_rate"] == 0.5
    assert report["correctness"]["task_case_count"] == 8
    assert report["composite"] == 5.0


def test_contextatlas_benchmark_probe_applies_memory_routing_config(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-probe"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True)
    (workspace_dir / "package.json").write_text(
        '{"name":"fake-contextatlas","type":"module"}', encoding="utf-8"
    )
    real_node_modules = Path("/home/yuanzhi/Develop/tools/ContextAtlas/node_modules")
    (workspace_dir / "node_modules").symlink_to(
        real_node_modules, target_is_directory=True
    )

    write_json(
        workspace_dir / "src" / "db" / "index.ts",
        {},
    )
    (workspace_dir / "src" / "db" / "index.ts").write_text(
        "\n".join(
            [
                "export function initDb() {",
                "  return {",
                "    prepare(sql: string) {",
                "      return {",
                "        get() {",
                '          if (sql.includes("COUNT(*) as c FROM files")) return { c: 12 };',
                '          if (sql.includes("SUM(length(content))")) return { c: 30000 };',
                "          if (sql.includes(\"name='chunks_fts'\")) return { name: 'chunks_fts' };",
                '          if (sql.includes("COUNT(*) as c FROM chunks_fts")) return { c: 20 };',
                "          return undefined;",
                "        },",
                "        all() { return []; },",
                "      };",
                "    },",
                "    close() {},",
                "  };",
                "}",
            ]
        ),
        encoding="utf-8",
    )
    (workspace_dir / "src" / "storage" / "layout.ts").parent.mkdir(
        parents=True, exist_ok=True
    )
    (workspace_dir / "src" / "storage" / "layout.ts").write_text(
        "export function resolveCurrentSnapshotId() { return 'snap-test'; }\n",
        encoding="utf-8",
    )
    (workspace_dir / "src" / "search" / "fts.ts").parent.mkdir(
        parents=True, exist_ok=True
    )
    (workspace_dir / "src" / "search" / "fts.ts").write_text(
        "\n".join(
            [
                "export function searchFilesFts(_db: unknown, query: string, limit: number) {",
                "  const targetByQuery: Record<string, string> = {",
                "    'codebase retrieval SearchService build context pack': 'src/mcp/tools/codebaseRetrieval.ts',",
                "    'SearchService ContextPacker GraphExpander hybrid search': 'src/search/SearchService.ts',",
                "    'MemoryRouter route keywords scope cascade': 'src/memory/MemoryRouter.ts',",
                "    'health check queue snapshots current snapshot vector index': 'src/monitoring/indexHealth.ts',",
                "  };",
                "  const target = targetByQuery[query];",
                "  if (!target) return [];",
                "  const rows = [",
                "    { path: 'noise/a.ts', score: 4.0 },",
                "    { path: 'noise/b.ts', score: 3.0 },",
                "    { path: target, score: 2.0 },",
                "    { path: 'noise/c.ts', score: 1.0 },",
                "  ];",
                "  return rows.slice(0, limit);",
                "}",
            ]
        ),
        encoding="utf-8",
    )
    (workspace_dir / "src" / "memory" / "MemoryFinder.ts").parent.mkdir(
        parents=True, exist_ok=True
    )
    (workspace_dir / "src" / "memory" / "MemoryFinder.ts").write_text(
        "\n".join(
            [
                "export class MemoryFinder {",
                "  constructor(_projectRoot: string) {}",
                "  async find(_query: string) {",
                "    return [",
                "      {",
                "        memory: {",
                "          name: 'ContextWeaver Core',",
                "          lastUpdated: '2026-03-01T00:00:00.000Z',",
                "          api: { exports: ['SearchService'] },",
                "        },",
                "      },",
                "    ];",
                "  }",
                "}",
            ]
        ),
        encoding="utf-8",
    )

    probe_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "contextatlas_benchmark_probe.ts"
    )

    def run_probe(config: dict) -> dict:
        write_json(run_dir / "effective_config.json", config)
        completed = subprocess.run(
            ["node", "--import", "tsx", str(probe_path), "--project-id", "proj-test"],
            cwd=workspace_dir,
            env={**os.environ, "META_HARNESS_RUN_DIR": str(run_dir)},
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(completed.stdout.strip().splitlines()[-1])

    baseline = run_probe(
        {
            "retrieval": {"top_k": 8, "rerank_k": 8},
            "indexing": {"chunk_size": 1000, "chunk_overlap": 40},
            "contextatlas": {"memory": {"enabled": True}},
        }
    )
    lightweight = run_probe(
        {
            "retrieval": {"top_k": 8, "rerank_k": 8},
            "indexing": {"chunk_size": 1000, "chunk_overlap": 40},
            "contextatlas": {
                "memory": {
                    "enabled": True,
                    "routing_mode": "lightweight",
                    "freshness_bias": 0.4,
                    "stale_prune_threshold": 0.2,
                }
            },
        }
    )
    freshness_biased = run_probe(
        {
            "retrieval": {"top_k": 8, "rerank_k": 8},
            "indexing": {"chunk_size": 1000, "chunk_overlap": 40},
            "contextatlas": {
                "memory": {
                    "enabled": True,
                    "routing_mode": "freshness-biased",
                    "freshness_bias": 0.8,
                    "stale_prune_threshold": 0.12,
                }
            },
        }
    )
    strict_pruning = run_probe(
        {
            "retrieval": {"top_k": 8, "rerank_k": 8},
            "indexing": {"chunk_size": 1000, "chunk_overlap": 40},
            "contextatlas": {
                "memory": {
                    "enabled": True,
                    "routing_mode": "strict-pruning",
                    "freshness_bias": 0.6,
                    "stale_prune_threshold": 0.08,
                }
            },
        }
    )
    memory_off = run_probe(
        {
            "retrieval": {"top_k": 8, "rerank_k": 8},
            "indexing": {"chunk_size": 1000, "chunk_overlap": 40},
            "contextatlas": {"memory": {"enabled": False}},
        }
    )

    assert baseline["memory"]["completeness"] > lightweight["memory"]["completeness"]
    assert freshness_biased["memory"]["freshness"] > baseline["memory"]["freshness"]
    assert freshness_biased["memory"]["staleRatio"] < baseline["memory"]["staleRatio"]
    assert strict_pruning["memory"]["completeness"] < baseline["memory"]["completeness"]
    assert strict_pruning["memory"]["staleRatio"] <= baseline["memory"]["staleRatio"]
    assert memory_off["memory"] == {
        "moduleCount": 0,
        "scopeCount": 0,
        "completeness": 0,
        "freshness": 0,
        "staleRatio": 1,
    }


def test_contextatlas_benchmark_probe_applies_retrieval_and_indexing_config(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-probe"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True)
    (workspace_dir / "package.json").write_text(
        '{"name":"fake-contextatlas","type":"module"}', encoding="utf-8"
    )
    real_node_modules = Path("/home/yuanzhi/Develop/tools/ContextAtlas/node_modules")
    (workspace_dir / "node_modules").symlink_to(
        real_node_modules, target_is_directory=True
    )

    write_json(
        workspace_dir / "src" / "db" / "index.ts",
        {},
    )
    (workspace_dir / "src" / "db" / "index.ts").write_text(
        "\n".join(
            [
                "export function initDb() {",
                "  return {",
                "    prepare(sql: string) {",
                "      return {",
                "        get() {",
                '          if (sql.includes("COUNT(*) as c FROM files")) return { c: 12 };',
                '          if (sql.includes("SUM(length(content))")) return { c: 30000 };',
                "          if (sql.includes(\"name='chunks_fts'\")) return { name: 'chunks_fts' };",
                '          if (sql.includes("COUNT(*) as c FROM chunks_fts")) return { c: 20 };',
                "          return undefined;",
                "        },",
                "        all() { return []; },",
                "      };",
                "    },",
                "    close() {},",
                "  };",
                "}",
            ]
        ),
        encoding="utf-8",
    )
    (workspace_dir / "src" / "storage" / "layout.ts").parent.mkdir(
        parents=True, exist_ok=True
    )
    (workspace_dir / "src" / "storage" / "layout.ts").write_text(
        "export function resolveCurrentSnapshotId() { return 'snap-test'; }\n",
        encoding="utf-8",
    )
    (workspace_dir / "src" / "search" / "fts.ts").parent.mkdir(
        parents=True, exist_ok=True
    )
    (workspace_dir / "src" / "search" / "fts.ts").write_text(
        "\n".join(
            [
                "export function searchFilesFts(_db: unknown, query: string, limit: number) {",
                "  const targetByQuery: Record<string, string> = {",
                "    'codebase retrieval SearchService build context pack': 'src/mcp/tools/codebaseRetrieval.ts',",
                "    'SearchService ContextPacker GraphExpander hybrid search': 'src/search/SearchService.ts',",
                "    'MemoryRouter route keywords scope cascade': 'src/memory/MemoryRouter.ts',",
                "    'health check queue snapshots current snapshot vector index': 'src/monitoring/indexHealth.ts',",
                "  };",
                "  const target = targetByQuery[query];",
                "  if (!target) return [];",
                "  const rows = [",
                "    { path: 'noise/a.ts', score: 4.0 },",
                "    { path: 'noise/b.ts', score: 3.0 },",
                "    { path: target, score: 2.0 },",
                "    { path: 'noise/c.ts', score: 1.0 },",
                "  ];",
                "  return rows.slice(0, limit);",
                "}",
            ]
        ),
        encoding="utf-8",
    )
    (workspace_dir / "src" / "memory" / "MemoryFinder.ts").parent.mkdir(
        parents=True, exist_ok=True
    )
    (workspace_dir / "src" / "memory" / "MemoryFinder.ts").write_text(
        "\n".join(
            [
                "export class MemoryFinder {",
                "  constructor(_projectRoot: string) {}",
                "  async find(_query: string) {",
                "    return [",
                "      {",
                "        memory: {",
                "          name: 'ContextWeaver Core',",
                "          lastUpdated: '2026-03-01T00:00:00.000Z',",
                "          api: { exports: ['SearchService'] },",
                "        },",
                "      },",
                "    ];",
                "  }",
                "}",
            ]
        ),
        encoding="utf-8",
    )

    probe_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "contextatlas_benchmark_probe.ts"
    )

    def run_probe(config: dict, *, scenario: str | None = None) -> dict:
        write_json(run_dir / "effective_config.json", config)
        command = [
            "node",
            "--import",
            "tsx",
            str(probe_path),
            "--project-id",
            "proj-test",
        ]
        if scenario is not None:
            command.extend(["--scenario", scenario])
        completed = subprocess.run(
            command,
            cwd=workspace_dir,
            env={**os.environ, "META_HARNESS_RUN_DIR": str(run_dir)},
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(completed.stdout.strip().splitlines()[-1])

    baseline = run_probe(
        {
            "retrieval": {
                "top_k": 8,
                "rerank_k": 8,
            },
            "indexing": {"chunk_size": 1000, "chunk_overlap": 40},
            "contextatlas": {"memory": {"enabled": True}},
        }
    )
    retrieval_wide = run_probe(
        {
            "retrieval": {
                "top_k": 12,
                "rerank_k": 24,
            },
            "indexing": {"chunk_size": 1000, "chunk_overlap": 40},
            "contextatlas": {"memory": {"enabled": True}},
        }
    )
    indexing_dense = run_probe(
        {
            "retrieval": {
                "top_k": 8,
                "rerank_k": 8,
            },
            "indexing": {"chunk_size": 1200, "chunk_overlap": 160},
            "contextatlas": {"memory": {"enabled": True}},
        }
    )
    exact_lookup = run_probe(
        {
            "retrieval": {
                "top_k": 12,
                "rerank_k": 24,
            },
            "indexing": {"chunk_size": 1000, "chunk_overlap": 40},
            "contextatlas": {"memory": {"enabled": True}},
        },
        scenario="exact_symbol_lookup",
    )
    stale_recovery = run_probe(
        {
            "retrieval": {
                "top_k": 8,
                "rerank_k": 8,
            },
            "indexing": {"chunk_size": 1000, "chunk_overlap": 40},
            "contextatlas": {"memory": {"enabled": True}},
        },
        scenario="stale_index_recovery",
    )

    assert retrieval_wide["retrieval"]["hitRate"] > baseline["retrieval"]["hitRate"]
    assert retrieval_wide["retrieval"]["mrr"] > baseline["retrieval"]["mrr"]
    assert (
        indexing_dense["indexing"]["documentCount"]
        == baseline["indexing"]["documentCount"]
    )
    assert (
        indexing_dense["indexing"]["chunkCount"] == baseline["indexing"]["chunkCount"]
    )
    assert indexing_dense["retrieval"] == baseline["retrieval"]
    assert baseline["taskQuality"]["taskCaseCount"] >= 10
    assert baseline["probes"]["indexing.build_latency_ms"] > 0
    assert baseline["probes"]["indexing.peak_memory_mb"] > 0
    assert baseline["probes"]["indexing.index_size_bytes"] > 0
    assert baseline["probes"]["indexing.files_scanned_count"] == 12
    assert baseline["probes"]["indexing.files_reindexed_count"] == 12
    assert baseline["probes"]["indexing.query_p50_ms"] > 0
    assert baseline["probes"]["indexing.query_p95_ms"] >= baseline["probes"]["indexing.query_p50_ms"]
    assert indexing_dense["probes"]["indexing.index_size_bytes"] != baseline["probes"]["indexing.index_size_bytes"]
    assert exact_lookup["taskQuality"]["taskCaseCount"] < baseline["taskQuality"]["taskCaseCount"]
    assert stale_recovery["taskQuality"]["taskCaseCount"] < baseline["taskQuality"]["taskCaseCount"]
    assert exact_lookup["retrieval"]["hitRate"] > 0
    assert stale_recovery["taskQuality"]["taskSuccessRate"] >= 0
    assert (
        retrieval_wide["taskQuality"]["taskSuccessRate"]
        >= baseline["taskQuality"]["taskSuccessRate"]
    )


def test_contextatlas_task_set_template_contains_import_and_audit_steps() -> None:
    task_set_path = (
        Path(__file__).resolve().parents[1]
        / "task_sets"
        / "contextatlas"
        / "import_profile_and_audit.json"
    )

    payload = json.loads(task_set_path.read_text(encoding="utf-8"))
    phases = payload["tasks"][0]["phases"]
    phase_names = [phase["phase"] for phase in phases]

    assert phase_names == [
        "register_project",
        "import_profile",
        "show_profile",
        "check_memory",
        "health_check",
    ]
    assert payload["tasks"][0]["workdir"] == "${contextatlas.repo_path}"
    assert phases[0]["command"][5] == "${contextatlas.repo_path}"
    assert phases[4]["command"][-1] == "${contextatlas.project_id}"


def test_contextatlas_patch_workflow_assets_exist_and_reference_patch_flow() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    profile_payload = json.loads(
        (
            repo_root / "configs" / "profiles" / "contextatlas_patch_repair.json"
        ).read_text(encoding="utf-8")
    )
    project_payload = json.loads(
        (repo_root / "configs" / "projects" / "contextatlas_patch.json").read_text(
            encoding="utf-8"
        )
    )
    task_payload = json.loads(
        (repo_root / "task_sets" / "contextatlas" / "repair_with_patch.json").read_text(
            encoding="utf-8"
        )
    )

    assert profile_payload["defaults"]["evaluation"]["evaluators"] == [
        "basic",
        "command",
    ]
    assert project_payload["workflow"] == "contextatlas_patch_repair"
    assert (
        project_payload["overrides"]["evaluation"]["command_evaluators"][0]["command"][
            -1
        ]
        == "/home/yuanzhi/Develop/tools/meta-harness/scripts/contextatlas_patch_eval.py"
    )
    assert (
        project_payload["overrides"]["optimization"]["proposal_command"][0] == "python"
    )
    assert (
        project_payload["overrides"]["optimization"]["proposal_command"][-1]
        == "/home/yuanzhi/Develop/tools/meta-harness/scripts/contextatlas_patch_proposal.py"
    )
    assert project_payload["overrides"]["optimization"]["history_sources"] == [
        {"profile": "contextatlas_maintenance", "project": "contextatlas"},
        {"profile": "contextatlas_patch_repair", "project": "contextatlas_patch"},
    ]
    assert (
        project_payload["overrides"]["runtime"]["workspace"]["source_repo"]
        == "${contextatlas.repo_path}"
    )
    assert project_payload["overrides"]["optimization"]["headroom_defaults"][
        "indexing"
    ] == {
        "retrieval": {
            "chunk_size": 1200,
            "chunk_overlap": 160,
        },
        "signals": [
            "snapshot_ready",
            "vector_index_ready",
            "db_integrity_ok",
        ],
        "checks": [
            "snapshot_health",
            "vector_index_health",
            "db_integrity",
        ],
    }
    assert project_payload["overrides"]["optimization"]["headroom_defaults"][
        "memory"
    ] == {
        "budget": {
            "max_turns": 14,
            "max_retries": 2,
        },
        "signals": [
            "memory_completeness",
            "memory_freshness",
            "memory_stale_ratio",
        ],
        "checks": [
            "profile_import",
            "memory_consistency",
            "catalog_freshness",
        ],
    }
    assert project_payload["overrides"]["optimization"]["headroom_defaults"][
        "retrieval"
    ] == {
        "retrieval": {
            "top_k": 12,
            "rerank_k": 24,
        },
        "signals": [
            "retrieval_hit_rate",
            "retrieval_mrr",
            "grounded_answer_rate",
        ],
        "checks": [
            "topk_sweep",
            "rerank_eval",
            "query_quality_eval",
        ],
    }
    assert project_payload["overrides"]["optimization"]["headroom_thresholds"] == {
        "indexing": {
            "vector_coverage_ratio": 0.9,
            "index_freshness_ratio": 0.85,
        },
        "memory": {
            "memory_completeness": 0.8,
            "memory_freshness": 0.85,
            "memory_stale_ratio": 0.1,
        },
        "retrieval": {
            "retrieval_hit_rate": 0.7,
            "retrieval_mrr": 0.5,
            "grounded_answer_rate": 0.8,
        },
    }

    phase_names = [phase["phase"] for phase in task_payload["tasks"][0]["phases"]]
    assert phase_names == [
        "install_dependencies",
        "register_project",
        "import_profile",
        "build",
        "test_omc_import",
        "show_profile",
        "check_memory",
    ]
    assert task_payload["tasks"][0]["phases"][0]["command"][0] == "pnpm"
    assert task_payload["tasks"][0]["phases"][1]["command"][5] == "${workspace_dir}"


def test_contextatlas_benchmark_assets_exist_and_reference_retrieval_memory_ab_flow() -> (
    None
):
    repo_root = Path(__file__).resolve().parents[1]

    profile_payload = json.loads(
        (repo_root / "configs" / "profiles" / "contextatlas_benchmark.json").read_text(
            encoding="utf-8"
        )
    )
    project_payload = json.loads(
        (repo_root / "configs" / "projects" / "contextatlas_benchmark.json").read_text(
            encoding="utf-8"
        )
    )
    benchmark_payload = json.loads(
        (
            repo_root
            / "configs"
            / "benchmarks"
            / "contextatlas_retrieval_memory_ab.json"
        ).read_text(encoding="utf-8")
    )
    task_payload = json.loads(
        (
            repo_root / "task_sets" / "contextatlas" / "benchmark_retrieval_memory.json"
        ).read_text(encoding="utf-8")
    )

    assert profile_payload["defaults"]["evaluation"]["evaluators"] == [
        "basic",
        "command",
    ]
    assert project_payload["workflow"] == "contextatlas_benchmark"
    assert (
        project_payload["overrides"]["evaluation"]["command_evaluators"][0]["command"][
            -1
        ]
        == "/home/yuanzhi/Develop/tools/meta-harness/scripts/contextatlas_run_eval.py"
    )
    assert (
        project_payload["overrides"]["runtime"]["workspace"]["source_repo"]
        == "${contextatlas.repo_path}"
    )
    assert project_payload["overrides"]["contextatlas"]["memory"]["enabled"] is True

    assert benchmark_payload["experiment"] == "contextatlas_retrieval_memory_ab"
    assert benchmark_payload["baseline"] == "baseline"
    variant_names = [variant["name"] for variant in benchmark_payload["variants"]]
    assert variant_names == [
        "baseline",
        "retrieval_wide",
        "dense_chunking",
        "memory_off",
    ]
    assert benchmark_payload["variants"][1]["config_patch"] == {
        "retrieval": {
            "top_k": 12,
            "rerank_k": 24,
        }
    }
    assert benchmark_payload["variants"][2]["config_patch"] == {
        "indexing": {
            "chunk_size": 1200,
            "chunk_overlap": 160,
        }
    }
    assert benchmark_payload["variants"][3]["config_patch"] == {
        "contextatlas": {
            "memory": {
                "enabled": False,
            }
        }
    }

    phase_names = [phase["phase"] for phase in task_payload["tasks"][0]["phases"]]
    assert phase_names == [
        "install_dependencies",
        "register_project",
        "import_profile",
        "build",
        "index_workspace",
        "test_omc_import",
        "show_profile",
        "check_memory",
        "health_check",
        "benchmark_probe",
    ]
    assert task_payload["tasks"][0]["phases"][1]["command"][5] == "${workspace_dir}"
    assert task_payload["tasks"][0]["phases"][4]["command"][4] == "index"
    assert task_payload["tasks"][0]["phases"][4]["command"][5] == "${workspace_dir}"
    assert (
        task_payload["tasks"][0]["phases"][8]["command"][-1]
        == "${contextatlas.project_id}"
    )
    assert (
        task_payload["tasks"][0]["phases"][9]["command"][-1]
        == "${contextatlas.project_id}"
    )


def test_contextatlas_benchmark_assets_exist_and_reference_indexing_sweep_flow() -> (
    None
):
    repo_root = Path(__file__).resolve().parents[1]

    benchmark_payload = json.loads(
        (
            repo_root / "configs" / "benchmarks" / "contextatlas_indexing_sweep.json"
        ).read_text(encoding="utf-8")
    )

    assert benchmark_payload["experiment"] == "contextatlas_indexing_sweep"
    assert benchmark_payload["baseline"] == "baseline"
    variant_names = [variant["name"] for variant in benchmark_payload["variants"]]
    assert variant_names == [
        "baseline",
        "topk_12_rerank_24",
        "topk_16_rerank_32",
        "chunk_800_overlap_120",
        "chunk_1200_overlap_160",
    ]
    assert benchmark_payload["variants"][1]["config_patch"] == {
        "retrieval": {
            "top_k": 12,
            "rerank_k": 24,
        }
    }
    assert benchmark_payload["variants"][2]["config_patch"] == {
        "retrieval": {
            "top_k": 16,
            "rerank_k": 32,
        }
    }
    assert benchmark_payload["variants"][3]["config_patch"] == {
        "indexing": {
            "chunk_size": 800,
            "chunk_overlap": 120,
        }
    }
    assert benchmark_payload["variants"][4]["config_patch"] == {
        "indexing": {
            "chunk_size": 1200,
            "chunk_overlap": 160,
        }
    }


def test_contextatlas_indexing_architecture_v2_assets_exist() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    benchmark_payload = json.loads(
        (
            repo_root
            / "configs"
            / "benchmarks"
            / "contextatlas_indexing_architecture_v2.json"
        ).read_text(encoding="utf-8")
    )
    task_payload = json.loads(
        (
            repo_root
            / "task_sets"
            / "contextatlas"
            / "benchmark_indexing_architecture_v2.json"
        ).read_text(encoding="utf-8")
    )
    design_doc = (
        repo_root / "docs" / "contextatlas-indexing-benchmark-v2.md"
    ).read_text(encoding="utf-8")
    integration_doc = (repo_root / "docs" / "contextatlas-integration.md").read_text(
        encoding="utf-8"
    )

    assert benchmark_payload["experiment"] == "contextatlas_indexing_architecture_v2"
    assert benchmark_payload["baseline"] == "baseline_snapshot"
    assert benchmark_payload["analysis_mode"] == "architecture"
    assert benchmark_payload["repeats"] == 3
    assert benchmark_payload["report"]["group_by"] == ["scenario", "variant_type"]
    assert benchmark_payload["report"]["recommended_task_set"] == (
        "task_sets/contextatlas/benchmark_indexing_architecture_v2.json"
    )
    assert benchmark_payload["report"]["primary_axes"] == [
        "quality",
        "mechanism",
        "stability",
        "cost",
    ]
    assert [scenario["id"] for scenario in benchmark_payload["scenarios"]] == [
        "exact_symbol_lookup",
        "cross_file_dependency_trace",
        "index_freshness_sensitive",
        "recent_change_discovery",
        "stale_index_recovery",
        "large_repo_retrieval",
    ]
    assert [variant["name"] for variant in benchmark_payload["variants"]] == [
        "baseline_snapshot",
        "chunk_dense_quality_bias",
        "chunk_compact_cost_bias",
        "incremental_refresh_skeleton",
        "freshness_guard_skeleton",
    ]
    assert benchmark_payload["variants"][3]["variant_type"] == "method_family"
    assert benchmark_payload["variants"][3]["implementation_id"] == (
        "indexing/incremental-refresh-skeleton"
    )
    assert benchmark_payload["variants"][4]["config_patch"]["optimization"] == {
        "focus": "indexing",
        "indexing_strategy_hint": "freshness_guard",
    }
    assert [task["task_id"] for task in task_payload["tasks"]] == [
        "indexing-bootstrap",
        "exact-symbol-lookup",
        "cross-file-dependency-trace",
        "index-freshness-sensitive",
        "recent-change-discovery",
        "stale-index-recovery",
        "large-repo-retrieval",
    ]
    assert task_payload["tasks"][0].get("scenario") is None
    assert [task["scenario"] for task in task_payload["tasks"][1:]] == [
        "exact_symbol_lookup",
        "cross_file_dependency_trace",
        "index_freshness_sensitive",
        "recent_change_discovery",
        "stale_index_recovery",
        "large_repo_retrieval",
    ]
    assert task_payload["tasks"][1]["phases"][0]["command"][-2:] == [
        "--scenario",
        "exact_symbol_lookup",
    ]
    assert task_payload["tasks"][-1]["phases"][0]["command"][-2:] == [
        "--scenario",
        "large_repo_retrieval",
    ]
    assert "configs/benchmarks/contextatlas_indexing_architecture_v2.json" in design_doc
    assert "task_sets/contextatlas/benchmark_indexing_architecture_v2.json" in design_doc
    assert "indexing.build_latency_ms" in design_doc
    assert "indexing.peak_memory_mb" in design_doc
    assert "--spec configs/benchmarks/contextatlas_indexing_architecture_v2.json" in (
        integration_doc
    )


def test_contextatlas_benchmark_assets_exist_and_reference_memory_routing_sweep_flow() -> (
    None
):
    repo_root = Path(__file__).resolve().parents[1]

    benchmark_payload = json.loads(
        (
            repo_root
            / "configs"
            / "benchmarks"
            / "contextatlas_memory_routing_sweep.json"
        ).read_text(encoding="utf-8")
    )

    assert benchmark_payload["experiment"] == "contextatlas_memory_routing_sweep"
    assert benchmark_payload["baseline"] == "baseline"
    variant_names = [variant["name"] for variant in benchmark_payload["variants"]]
    assert variant_names == [
        "baseline",
        "memory_lightweight",
        "memory_freshness_bias",
        "memory_strict_pruning",
        "memory_off",
    ]
    assert benchmark_payload["variants"][1]["config_patch"] == {
        "contextatlas": {
            "memory": {
                "routing_mode": "lightweight",
                "freshness_bias": 0.4,
                "stale_prune_threshold": 0.2,
            }
        }
    }
    assert benchmark_payload["variants"][2]["config_patch"] == {
        "contextatlas": {
            "memory": {
                "routing_mode": "freshness-biased",
                "freshness_bias": 0.8,
                "stale_prune_threshold": 0.12,
            }
        }
    }
    assert benchmark_payload["variants"][3]["config_patch"] == {
        "contextatlas": {
            "memory": {
                "routing_mode": "strict-pruning",
                "freshness_bias": 0.6,
                "stale_prune_threshold": 0.08,
            }
        }
    }
    assert benchmark_payload["variants"][4]["config_patch"] == {
        "contextatlas": {
            "memory": {
                "enabled": False,
            }
        }
    }


def test_contextatlas_benchmark_assets_exist_and_reference_default_suite_flow() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    suite_payload = json.loads(
        (
            repo_root / "configs" / "benchmarks" / "contextatlas_default_suite.json"
        ).read_text(encoding="utf-8")
    )

    assert suite_payload["suite"] == "contextatlas_default_suite"
    assert suite_payload["benchmarks"] == [
        {
            "spec": "configs/benchmarks/contextatlas_retrieval_memory_ab.json",
        },
        {
            "spec": "configs/benchmarks/contextatlas_indexing_sweep.json",
            "focus": "indexing",
        },
        {
            "spec": "configs/benchmarks/contextatlas_indexing_architecture_v2.json",
            "focus": "indexing",
            "task_set": "task_sets/contextatlas/benchmark_indexing_architecture_v2.json",
        },
        {
            "spec": "configs/benchmarks/contextatlas_memory_routing_sweep.json",
            "focus": "memory",
        },
        {
            "spec": "configs/benchmarks/contextatlas_stability_penalty_calibration.json",
            "focus": "retrieval",
            "task_set": "task_sets/contextatlas/benchmark_stability_penalty_calibration.json",
        },
    ]


def test_contextatlas_combo_and_current_best_assets_exist() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    combo_payload = json.loads(
        (
            repo_root / "configs" / "benchmarks" / "contextatlas_combo_validation.json"
        ).read_text(encoding="utf-8")
    )
    current_best_payload = json.loads(
        (
            repo_root
            / "configs"
            / "projects"
            / "contextatlas_benchmark_current_best.json"
        ).read_text(encoding="utf-8")
    )

    assert combo_payload["experiment"] == "contextatlas_combo_validation"
    assert combo_payload["baseline"] == "old_baseline"
    assert [variant["name"] for variant in combo_payload["variants"]] == [
        "old_baseline",
        "retrieval_wide_only",
        "indexing_dense_only",
        "retrieval_wide_plus_indexing_dense",
    ]
    assert combo_payload["variants"][1]["config_patch"] == {
        "retrieval": {
            "top_k": 12,
            "rerank_k": 24,
        }
    }
    assert combo_payload["variants"][2]["config_patch"] == {
        "indexing": {
            "chunk_size": 1200,
            "chunk_overlap": 160,
        }
    }
    assert combo_payload["variants"][3]["config_patch"] == {
        "retrieval": {
            "top_k": 12,
            "rerank_k": 24,
        },
        "indexing": {
            "chunk_size": 1200,
            "chunk_overlap": 160,
        },
    }

    assert current_best_payload["workflow"] == "contextatlas_benchmark"
    assert current_best_payload["overrides"]["retrieval"] == {
        "top_k": 16,
        "rerank_k": 32,
    }
    assert current_best_payload["overrides"]["indexing"] == {
        "chunk_size": 1000,
        "chunk_overlap": 40,
    }
    assert current_best_payload["overrides"]["contextatlas"]["memory"] == {
        "enabled": True,
        "routing_mode": "baseline",
    }


def test_contextatlas_benchmark_methodology_doc_mentions_decoupled_indexing_and_stability() -> (
    None
):
    repo_root = Path(__file__).resolve().parents[1]
    methodology = (
        repo_root / "docs" / "contextatlas-benchmark-methodology.md"
    ).read_text(encoding="utf-8")
    integration_doc = (repo_root / "docs" / "contextatlas-integration.md").read_text(
        encoding="utf-8"
    )

    assert "retrieval 只管 `top_k / rerank_k`" in methodology
    assert "indexing 只管 `chunk_size / chunk_overlap`" in methodology
    assert "最小重复次数" in methodology
    assert "高分但不稳定" in methodology
    assert "penalty 参数校准" in methodology
    assert '"indexing": {"chunk_size": 1200' in integration_doc


def test_contextatlas_penalty_calibration_assets_exist() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    calibration_payload = json.loads(
        (
            repo_root
            / "configs"
            / "benchmarks"
            / "contextatlas_stability_penalty_calibration.json"
        ).read_text(encoding="utf-8")
    )
    calibration_task_set_payload = json.loads(
        (
            repo_root
            / "task_sets"
            / "contextatlas"
            / "benchmark_stability_penalty_calibration.json"
        ).read_text(encoding="utf-8")
    )
    default_suite_payload = json.loads(
        (
            repo_root / "configs" / "benchmarks" / "contextatlas_default_suite.json"
        ).read_text(encoding="utf-8")
    )

    assert (
        calibration_payload["experiment"]
        == "contextatlas_stability_penalty_calibration"
    )
    assert calibration_payload["baseline"] == "penalty_default"
    assert calibration_payload["repeats"] == 3
    assert calibration_payload["report"] == {
        "recommended_task_set": "task_sets/contextatlas/benchmark_stability_penalty_calibration.json",
        "goal": "amplify repeat-to-repeat variance for penalty calibration",
    }
    assert [variant["name"] for variant in calibration_payload["variants"]] == [
        "penalty_default",
        "penalty_balanced",
        "penalty_range_heavy",
        "penalty_stddev_heavy",
    ]
    assert calibration_payload["variants"][1]["config_patch"] == {
        "evaluation": {
            "stability": {
                "unstable_high_score_penalty": 0.5,
                "range_weight": 1.0,
                "stddev_weight": 1.0,
            }
        }
    }
    assert calibration_payload["variants"][2]["config_patch"] == {
        "evaluation": {
            "stability": {
                "unstable_high_score_penalty": 0.35,
                "range_weight": 1.75,
                "stddev_weight": 0.75,
            }
        }
    }
    assert calibration_payload["variants"][3]["config_patch"] == {
        "evaluation": {
            "stability": {
                "unstable_high_score_penalty": 0.35,
                "range_weight": 0.75,
                "stddev_weight": 1.75,
            }
        }
    }
    assert [task["task_id"] for task in calibration_task_set_payload["tasks"]] == [
        "contextatlas-stability-calibration"
    ]
    calibration_phases = [
        phase["phase"] for phase in calibration_task_set_payload["tasks"][0]["phases"]
    ]
    assert calibration_phases[-3:] == [
        "health_check",
        "variance_probe",
        "benchmark_probe",
    ]
    assert "run_metadata.json" in json.dumps(calibration_task_set_payload)
    assert default_suite_payload["benchmarks"][-1] == {
        "spec": "configs/benchmarks/contextatlas_stability_penalty_calibration.json",
        "focus": "retrieval",
        "task_set": "task_sets/contextatlas/benchmark_stability_penalty_calibration.json",
    }


def test_contextatlas_patch_proposal_emits_code_patch_for_omc_failures() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "contextatlas_patch_proposal.py"

    completed = subprocess.run(
        ["python", str(script_path)],
        input=json.dumps(
            {
                "profile": "contextatlas_patch_repair",
                "project": "contextatlas_patch",
                "matching_runs": [{"run_id": "run-omc"}],
                "failure_records": [
                    {
                        "run_id": "run-omc",
                        "family": "profile show",
                        "signature": "profile show empty because .omc project memory not imported",
                        "raw_error": "profile show empty because .omc project memory not imported",
                    }
                ],
            }
        ),
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["proposal"]["strategy"] == "restore_omc_profile_import_path"
    assert payload["proposal"]["source_runs"] == ["run-omc"]
    assert payload["code_patch"].startswith("--- a/src/memory/MemoryStore.ts")


def test_contextatlas_patch_proposal_uses_score_gaps_without_failures() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "contextatlas_patch_proposal.py"

    completed = subprocess.run(
        ["python", str(script_path)],
        input=json.dumps(
            {
                "profile": "contextatlas_patch_repair",
                "project": "contextatlas_patch",
                "matching_runs": [
                    {
                        "run_id": "run-quality-gap",
                        "score": {
                            "maintainability": {
                                "profile_present": False,
                                "memory_consistency_ok": False,
                            },
                            "architecture": {
                                "snapshot_ready": True,
                                "vector_index_ready": True,
                                "db_integrity_ok": True,
                            },
                            "composite": 6.0,
                        },
                    }
                ],
                "failure_records": [],
            }
        ),
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["proposal"]["strategy"] == "close_profile_memory_quality_gap"
    assert payload["proposal"]["source_runs"] == ["run-quality-gap"]
    assert payload["code_patch"].startswith("--- a/src/memory/MemoryStore.ts")


def test_contextatlas_patch_proposal_uses_indexing_headroom_for_architecture_gaps() -> (
    None
):
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "contextatlas_patch_proposal.py"

    completed = subprocess.run(
        ["python", str(script_path)],
        input=json.dumps(
            {
                "profile": "contextatlas_patch_repair",
                "project": "contextatlas_patch",
                "effective_config": {
                    "retrieval": {
                        "top_k": 8,
                        "chunk_size": 1000,
                    },
                    "optimization": {
                        "headroom_defaults": {
                            "indexing": {
                                "retrieval": {
                                    "chunk_size": 1200,
                                    "chunk_overlap": 160,
                                },
                                "signals": [
                                    "snapshot_ready",
                                    "vector_index_ready",
                                    "db_integrity_ok",
                                ],
                                "checks": [
                                    "snapshot_health",
                                    "vector_index_health",
                                    "db_integrity",
                                ],
                            }
                        }
                    },
                },
                "matching_runs": [
                    {
                        "run_id": "run-index-gap",
                        "created_at": "2026-04-05T09:00:00Z",
                        "score": {
                            "maintainability": {
                                "profile_present": True,
                                "memory_consistency_ok": True,
                            },
                            "architecture": {
                                "snapshot_ready": False,
                                "vector_index_ready": True,
                                "db_integrity_ok": True,
                            },
                            "composite": 9.0,
                        },
                    }
                ],
                "failure_records": [],
            }
        ),
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["proposal"]["strategy"] == "explore_indexing_headroom"
    assert payload["config_patch"]["retrieval"] == {
        "chunk_size": 1200,
        "chunk_overlap": 160,
    }
    assert payload["config_patch"]["optimization"]["focus"] == "indexing"
    assert payload["config_patch"]["optimization"]["headroom"] == {
        "category": "indexing",
        "latest_run_id": "run-index-gap",
        "best_run_id": "run-index-gap",
        "healthy_streak_runs": 0,
        "latest_gap_reasons": ["snapshot_ready"],
        "historical_gap_counts": {
            "snapshot_ready": 1,
            "vector_index_ready": 0,
            "db_integrity_ok": 0,
        },
        "metric_thresholds": {
            "vector_coverage_ratio": 0.9,
            "index_freshness_ratio": 0.85,
        },
    }
    assert payload["config_patch"]["contextatlas"]["headroom"]["indexing"] == {
        "signals": [
            "snapshot_ready",
            "vector_index_ready",
            "db_integrity_ok",
        ],
        "checks": [
            "snapshot_health",
            "vector_index_health",
            "db_integrity",
        ],
    }


def test_contextatlas_patch_proposal_avoids_redundant_patch_when_latest_run_is_healthy() -> (
    None
):
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "contextatlas_patch_proposal.py"

    completed = subprocess.run(
        ["python", str(script_path)],
        input=json.dumps(
            {
                "profile": "contextatlas_patch_repair",
                "project": "contextatlas_patch",
                "matching_runs": [
                    {
                        "run_id": "run-old-gap",
                        "created_at": "2026-04-05T09:00:00Z",
                        "score": {
                            "maintainability": {
                                "profile_present": False,
                                "memory_consistency_ok": False,
                            },
                            "architecture": {
                                "snapshot_ready": True,
                                "vector_index_ready": True,
                                "db_integrity_ok": True,
                            },
                            "composite": 6.0,
                        },
                    },
                    {
                        "run_id": "run-latest-healthy",
                        "created_at": "2026-04-05T10:00:00Z",
                        "score": {
                            "maintainability": {
                                "profile_present": True,
                                "memory_consistency_ok": True,
                            },
                            "architecture": {
                                "snapshot_ready": True,
                                "vector_index_ready": True,
                                "db_integrity_ok": True,
                            },
                            "composite": 12.0,
                        },
                        "run_context": {
                            "contextatlas": {
                                "latest_profile_source": ".omc/project-memory.json",
                                "latest_profile_updated_at": "2026/4/5 09:30:00",
                                "catalog_stats": {
                                    "module_count": 2,
                                    "scope_count": 1,
                                },
                            }
                        },
                    },
                ],
                "effective_config": {
                    "optimization": {
                        "headroom_defaults": {
                            "memory": {
                                "budget": {
                                    "max_turns": 14,
                                    "max_retries": 2,
                                },
                                "signals": [
                                    "memory_completeness",
                                    "memory_freshness",
                                    "memory_stale_ratio",
                                ],
                                "checks": [
                                    "profile_import",
                                    "memory_consistency",
                                    "catalog_freshness",
                                ],
                            }
                        }
                    }
                },
                "failure_records": [],
            }
        ),
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["proposal"]["strategy"] == "explore_memory_headroom"
    assert payload["proposal"]["source_runs"] == ["run-latest-healthy", "run-old-gap"]
    assert "code_patch" not in payload
    assert payload["config_patch"]["budget"] == {"max_turns": 14, "max_retries": 2}
    assert payload["config_patch"]["optimization"]["focus"] == "memory"
    assert payload["config_patch"]["optimization"]["headroom"] == {
        "category": "memory",
        "latest_run_id": "run-latest-healthy",
        "best_run_id": "run-latest-healthy",
        "healthy_streak_runs": 1,
        "historical_gap_counts": {
            "profile_present": 1,
            "memory_consistency_ok": 1,
        },
        "latest_profile_source": ".omc/project-memory.json",
        "latest_profile_updated_at": "2026/4/5 09:30:00",
        "latest_catalog_stats": {
            "module_count": 2,
            "scope_count": 1,
        },
        "metric_thresholds": {
            "memory_completeness": 0.8,
            "memory_freshness": 0.85,
            "memory_stale_ratio": 0.1,
        },
    }
    assert payload["config_patch"]["contextatlas"]["headroom"]["memory"] == {
        "signals": [
            "memory_completeness",
            "memory_freshness",
            "memory_stale_ratio",
        ],
        "checks": [
            "profile_import",
            "memory_consistency",
            "catalog_freshness",
        ],
    }


def test_contextatlas_patch_proposal_ignores_stale_failures_when_latest_run_is_healthy() -> (
    None
):
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "contextatlas_patch_proposal.py"

    completed = subprocess.run(
        ["python", str(script_path)],
        input=json.dumps(
            {
                "profile": "contextatlas_patch_repair",
                "project": "contextatlas_patch",
                "matching_runs": [
                    {
                        "run_id": "run-old-gap",
                        "created_at": "2026-04-05T09:00:00Z",
                        "score": {
                            "maintainability": {
                                "profile_present": False,
                                "memory_consistency_ok": False,
                            },
                            "architecture": {
                                "snapshot_ready": True,
                                "vector_index_ready": True,
                                "db_integrity_ok": True,
                            },
                            "composite": 6.0,
                        },
                    },
                    {
                        "run_id": "run-latest-healthy",
                        "created_at": "2026-04-05T10:00:00Z",
                        "score": {
                            "maintainability": {
                                "profile_present": True,
                                "memory_consistency_ok": True,
                            },
                            "architecture": {
                                "snapshot_ready": True,
                                "vector_index_ready": True,
                                "db_integrity_ok": True,
                            },
                            "composite": 12.0,
                        },
                    },
                ],
                "failure_records": [
                    {
                        "run_id": "run-old-gap",
                        "family": "profile show",
                        "signature": "profile show empty because .omc project memory not imported",
                        "raw_error": "profile show empty because .omc project memory not imported",
                    }
                ],
            }
        ),
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["proposal"]["strategy"] == "explore_memory_headroom"
    assert payload["proposal"]["latest_run_id"] == "run-latest-healthy"
    assert "code_patch" not in payload


def test_contextatlas_patch_proposal_uses_retrieval_headroom_when_quality_is_healthy() -> (
    None
):
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "contextatlas_patch_proposal.py"

    completed = subprocess.run(
        ["python", str(script_path)],
        input=json.dumps(
            {
                "profile": "contextatlas_patch_repair",
                "project": "contextatlas_patch",
                "effective_config": {
                    "retrieval": {
                        "top_k": 8,
                        "chunk_size": 1000,
                    },
                    "optimization": {
                        "headroom_defaults": {
                            "retrieval": {
                                "retrieval": {
                                    "top_k": 12,
                                    "rerank_k": 24,
                                },
                                "signals": [
                                    "retrieval_hit_rate",
                                    "retrieval_mrr",
                                    "grounded_answer_rate",
                                ],
                                "checks": [
                                    "topk_sweep",
                                    "rerank_eval",
                                    "query_quality_eval",
                                ],
                            }
                        }
                    },
                },
                "matching_runs": [
                    {
                        "run_id": "run-healthy-a",
                        "created_at": "2026-04-05T11:00:00Z",
                        "score": {
                            "maintainability": {
                                "profile_present": True,
                                "memory_consistency_ok": True,
                            },
                            "architecture": {
                                "snapshot_ready": True,
                                "vector_index_ready": True,
                                "db_integrity_ok": True,
                            },
                            "composite": 12.0,
                        },
                    }
                ],
                "failure_records": [],
            }
        ),
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["proposal"]["strategy"] == "explore_retrieval_headroom"
    assert payload["config_patch"]["retrieval"] == {
        "top_k": 12,
        "rerank_k": 24,
    }
    assert payload["config_patch"]["optimization"]["focus"] == "retrieval"
    assert payload["config_patch"]["optimization"]["headroom"] == {
        "category": "retrieval",
        "latest_run_id": "run-healthy-a",
        "best_run_id": "run-healthy-a",
        "healthy_streak_runs": 1,
        "composite_gap_to_best": 0.0,
        "metric_thresholds": {
            "retrieval_hit_rate": 0.7,
            "retrieval_mrr": 0.5,
            "grounded_answer_rate": 0.8,
        },
    }
    assert payload["config_patch"]["contextatlas"]["headroom"]["retrieval"] == {
        "signals": [
            "retrieval_hit_rate",
            "retrieval_mrr",
            "grounded_answer_rate",
        ],
        "checks": [
            "topk_sweep",
            "rerank_eval",
            "query_quality_eval",
        ],
    }


def test_contextatlas_patch_proposal_uses_memory_headroom_for_richer_memory_metric_gaps() -> (
    None
):
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "contextatlas_patch_proposal.py"

    completed = subprocess.run(
        ["python", str(script_path)],
        input=json.dumps(
            {
                "profile": "contextatlas_patch_repair",
                "project": "contextatlas_patch",
                "effective_config": {
                    "optimization": {
                        "headroom_defaults": {
                            "memory": {
                                "budget": {
                                    "max_turns": 14,
                                    "max_retries": 2,
                                },
                                "signals": [
                                    "memory_completeness",
                                    "memory_freshness",
                                    "memory_stale_ratio",
                                ],
                                "checks": [
                                    "profile_import",
                                    "memory_consistency",
                                    "catalog_freshness",
                                ],
                            }
                        }
                    }
                },
                "matching_runs": [
                    {
                        "run_id": "run-memory-metric-gap",
                        "created_at": "2026-04-05T12:00:00Z",
                        "score": {
                            "maintainability": {
                                "profile_present": True,
                                "memory_consistency_ok": True,
                                "memory_completeness": 0.62,
                                "memory_freshness": 0.82,
                                "memory_stale_ratio": 0.18,
                            },
                            "architecture": {
                                "snapshot_ready": True,
                                "vector_index_ready": True,
                                "db_integrity_ok": True,
                            },
                            "retrieval": {
                                "retrieval_hit_rate": 0.82,
                                "retrieval_mrr": 0.67,
                                "grounded_answer_rate": 0.88,
                            },
                            "composite": 12.0,
                        },
                    }
                ],
                "failure_records": [],
            }
        ),
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["proposal"]["strategy"] == "explore_memory_headroom"
    assert payload["config_patch"]["optimization"]["headroom"][
        "latest_metric_gaps"
    ] == [
        "memory_completeness",
        "memory_freshness",
        "memory_stale_ratio",
    ]
    assert payload["config_patch"]["optimization"]["headroom"][
        "latest_metric_values"
    ] == {
        "memory_completeness": 0.62,
        "memory_freshness": 0.82,
        "memory_stale_ratio": 0.18,
    }
    assert payload["config_patch"]["optimization"]["headroom"]["metric_thresholds"] == {
        "memory_completeness": 0.8,
        "memory_freshness": 0.85,
        "memory_stale_ratio": 0.1,
    }


def test_contextatlas_patch_proposal_uses_indexing_headroom_for_richer_indexing_metric_gaps() -> (
    None
):
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "contextatlas_patch_proposal.py"

    completed = subprocess.run(
        ["python", str(script_path)],
        input=json.dumps(
            {
                "profile": "contextatlas_patch_repair",
                "project": "contextatlas_patch",
                "effective_config": {
                    "retrieval": {
                        "top_k": 8,
                        "chunk_size": 1000,
                    }
                },
                "matching_runs": [
                    {
                        "run_id": "run-index-metric-gap",
                        "created_at": "2026-04-05T12:10:00Z",
                        "score": {
                            "maintainability": {
                                "profile_present": True,
                                "memory_consistency_ok": True,
                                "memory_completeness": 0.92,
                                "memory_freshness": 0.93,
                                "memory_stale_ratio": 0.03,
                            },
                            "architecture": {
                                "snapshot_ready": True,
                                "vector_index_ready": True,
                                "db_integrity_ok": True,
                                "vector_coverage_ratio": 0.68,
                                "index_freshness_ratio": 0.79,
                            },
                            "retrieval": {
                                "retrieval_hit_rate": 0.81,
                                "retrieval_mrr": 0.61,
                                "grounded_answer_rate": 0.9,
                            },
                            "composite": 12.0,
                        },
                    }
                ],
                "failure_records": [],
            }
        ),
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["proposal"]["strategy"] == "explore_indexing_headroom"
    assert payload["config_patch"]["optimization"]["headroom"][
        "latest_gap_reasons"
    ] == [
        "vector_coverage_ratio",
        "index_freshness_ratio",
    ]
    assert payload["config_patch"]["optimization"]["headroom"][
        "latest_metric_values"
    ] == {
        "vector_coverage_ratio": 0.68,
        "index_freshness_ratio": 0.79,
    }
    assert payload["config_patch"]["optimization"]["headroom"]["metric_thresholds"] == {
        "vector_coverage_ratio": 0.9,
        "index_freshness_ratio": 0.85,
    }


def test_contextatlas_patch_proposal_uses_retrieval_headroom_for_richer_retrieval_metric_gaps() -> (
    None
):
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "contextatlas_patch_proposal.py"

    completed = subprocess.run(
        ["python", str(script_path)],
        input=json.dumps(
            {
                "profile": "contextatlas_patch_repair",
                "project": "contextatlas_patch",
                "effective_config": {
                    "retrieval": {
                        "top_k": 8,
                        "chunk_size": 1000,
                    }
                },
                "matching_runs": [
                    {
                        "run_id": "run-retrieval-metric-gap",
                        "created_at": "2026-04-05T12:20:00Z",
                        "score": {
                            "maintainability": {
                                "profile_present": True,
                                "memory_consistency_ok": True,
                                "memory_completeness": 0.9,
                                "memory_freshness": 0.92,
                                "memory_stale_ratio": 0.04,
                            },
                            "architecture": {
                                "snapshot_ready": True,
                                "vector_index_ready": True,
                                "db_integrity_ok": True,
                                "vector_coverage_ratio": 0.94,
                                "index_freshness_ratio": 0.91,
                            },
                            "retrieval": {
                                "retrieval_hit_rate": 0.41,
                                "retrieval_mrr": 0.27,
                                "grounded_answer_rate": 0.69,
                            },
                            "composite": 11.4,
                        },
                    }
                ],
                "failure_records": [],
            }
        ),
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["proposal"]["strategy"] == "explore_retrieval_headroom"
    assert payload["config_patch"]["optimization"]["headroom"][
        "latest_metric_gaps"
    ] == [
        "retrieval_hit_rate",
        "retrieval_mrr",
        "grounded_answer_rate",
    ]
    assert payload["config_patch"]["optimization"]["headroom"][
        "latest_metric_values"
    ] == {
        "retrieval_hit_rate": 0.41,
        "retrieval_mrr": 0.27,
        "grounded_answer_rate": 0.69,
    }
    assert payload["config_patch"]["optimization"]["headroom"]["metric_thresholds"] == {
        "retrieval_hit_rate": 0.7,
        "retrieval_mrr": 0.5,
        "grounded_answer_rate": 0.8,
    }


def test_contextatlas_patch_proposal_uses_configured_metric_threshold_overrides() -> (
    None
):
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "contextatlas_patch_proposal.py"

    completed = subprocess.run(
        ["python", str(script_path)],
        input=json.dumps(
            {
                "profile": "contextatlas_patch_repair",
                "project": "contextatlas_patch",
                "effective_config": {
                    "optimization": {
                        "headroom_thresholds": {
                            "retrieval": {
                                "retrieval_hit_rate": 0.9,
                                "retrieval_mrr": 0.7,
                                "grounded_answer_rate": 0.9,
                            }
                        }
                    }
                },
                "matching_runs": [
                    {
                        "run_id": "run-custom-threshold-gap",
                        "created_at": "2026-04-05T12:30:00Z",
                        "score": {
                            "maintainability": {
                                "profile_present": True,
                                "memory_consistency_ok": True,
                                "memory_completeness": 0.92,
                                "memory_freshness": 0.94,
                                "memory_stale_ratio": 0.03,
                            },
                            "architecture": {
                                "snapshot_ready": True,
                                "vector_index_ready": True,
                                "db_integrity_ok": True,
                                "vector_coverage_ratio": 0.95,
                                "index_freshness_ratio": 0.92,
                            },
                            "retrieval": {
                                "retrieval_hit_rate": 0.82,
                                "retrieval_mrr": 0.63,
                                "grounded_answer_rate": 0.88,
                            },
                            "composite": 12.0,
                        },
                    }
                ],
                "failure_records": [],
            }
        ),
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["proposal"]["strategy"] == "explore_retrieval_headroom"
    assert payload["config_patch"]["optimization"]["headroom"]["metric_thresholds"] == {
        "retrieval_hit_rate": 0.9,
        "retrieval_mrr": 0.7,
        "grounded_answer_rate": 0.9,
    }
