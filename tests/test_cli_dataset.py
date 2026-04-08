from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from meta_harness.cli import app
from meta_harness.datasets import build_dataset_from_task_set


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_dataset_extract_failures_writes_dataset_json(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    output_path = tmp_path / "datasets" / "failure_cases.json"
    run_dir = runs_root / "run123"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)

    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run123", "profile": "base", "project": "demo"},
    )
    write_json(run_dir / "effective_config.json", {"evaluation": {"evaluators": ["basic"]}})
    (task_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "run_id": "run123",
                "task_id": "task-a",
                "step_id": "step-1",
                "phase": "compile",
                "status": "failed",
                "error": "Trait bound `Foo: Clone` is not satisfied",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "dataset",
            "extract-failures",
            "--runs-root",
            str(runs_root),
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["dataset_id"] == "failure-signatures"
    assert payload["case_count"] == 1
    assert payload["schema_version"] == "2026-04-06"
    assert payload["cases"][0]["run_id"] == "run123"
    assert payload["cases"][0]["task_id"] == "task-a"
    assert payload["cases"][0]["failure_signature"] == "trait bound foo clone is not satisfied"


def test_build_dataset_from_task_set_preserves_task_metadata(tmp_path: Path) -> None:
    task_set_path = tmp_path / "task_set.json"
    write_json(
        task_set_path,
        {
            "tasks": [
                {
                    "task_id": "task-a",
                    "scenario": "cross_file_dependency_trace",
                    "difficulty": "hard",
                    "weight": 1.5,
                    "expectations": {"must_pass": ["build", "tests"]},
                    "dataset_case": {
                        "query": "trace search service dependencies",
                        "expected_paths": [
                            "src/search/SearchService.ts",
                            "src/memory/MemoryRouter.ts",
                        ],
                        "expected_rank_max": 3,
                        "expected_grounding_refs": [
                            "src/search/SearchService.ts#L1",
                            "src/memory/MemoryRouter.ts#L1",
                        ],
                        "expected_answer_contains": [
                            "SearchService",
                            "MemoryRouter",
                        ],
                    },
                    "workdir": "/tmp/workspace",
                    "phases": [
                        {"phase": "prepare", "command": ["python", "-c", "print('ok')"]},
                        {"phase": "review", "command": ["python", "-c", "print('done')"]},
                    ],
                }
            ]
        },
    )

    payload = build_dataset_from_task_set(
        task_set_path,
        dataset_id="benchmark-cases",
        version="v2",
    )

    assert payload["dataset_id"] == "benchmark-cases"
    assert payload["version"] == "v2"
    assert payload["schema_version"] == "2026-04-06"
    assert payload["case_count"] == 1
    case = payload["cases"][0]
    assert case["source_type"] == "task_set"
    assert case["task_id"] == "task-a"
    assert case["scenario"] == "cross_file_dependency_trace"
    assert case["difficulty"] == "hard"
    assert case["weight"] == 1.5
    assert case["expectations"] == {"must_pass": ["build", "tests"]}
    assert case["phase_names"] == ["prepare", "review"]
    assert case["query"] == "trace search service dependencies"
    assert case["expected_paths"] == [
        "src/search/SearchService.ts",
        "src/memory/MemoryRouter.ts",
    ]
    assert case["expected_rank_max"] == 3
    assert case["expected_grounding_refs"] == [
        "src/search/SearchService.ts#L1",
        "src/memory/MemoryRouter.ts#L1",
    ]
    assert case["expected_answer_contains"] == [
        "SearchService",
        "MemoryRouter",
    ]


def test_dataset_build_task_set_writes_versioned_dataset_artifact(tmp_path: Path) -> None:
    task_set_path = tmp_path / "task_set.json"
    output_path = tmp_path / "datasets" / "benchmark-cases" / "v2" / "dataset.json"
    write_json(
        task_set_path,
        {
            "tasks": [
                {
                    "task_id": "task-a",
                    "scenario": "exact_symbol_lookup",
                    "difficulty": "medium",
                    "weight": 1.0,
                    "dataset_case": {
                        "query": "find SearchService",
                        "expected_paths": ["src/search/SearchService.ts"],
                    },
                    "phases": [
                        {"phase": "benchmark_probe", "command": ["python", "-c", "print('ok')"]}
                    ],
                }
            ]
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "dataset",
            "build-task-set",
            "--task-set",
            str(task_set_path),
            "--dataset-id",
            "benchmark-cases",
            "--version",
            "v2",
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["dataset_id"] == "benchmark-cases"
    assert payload["version"] == "v2"
    assert payload["case_count"] == 1
    assert payload["cases"][0]["query"] == "find SearchService"


def test_dataset_ingest_annotations_enriches_cases_and_writes_manifest(tmp_path: Path) -> None:
    dataset_path = tmp_path / "datasets" / "benchmark-cases" / "v1" / "dataset.json"
    output_path = tmp_path / "datasets" / "benchmark-cases" / "v2" / "dataset.json"
    annotations_path = tmp_path / "annotations.jsonl"
    write_json(
        dataset_path,
        {
            "dataset_id": "benchmark-cases",
            "version": "v1",
            "schema_version": "2026-04-06",
            "case_count": 1,
            "cases": [
                {
                    "case_id": "task_set:task-a",
                    "source_type": "task_set",
                    "run_id": "task-set",
                    "profile": "task-set",
                    "project": "task-set",
                    "task_id": "task-a",
                    "phase": "benchmark_probe",
                    "raw_error": "",
                    "failure_signature": "",
                }
            ],
        },
    )
    annotations_path.write_text(
        json.dumps(
            {
                "annotation_id": "ann-1",
                "target_type": "dataset_case",
                "target_ref": "task_set:task-a",
                "label": "hard_case",
                "value": True,
                "notes": "needs retry",
                "annotator": "reviewer",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "dataset",
            "ingest-annotations",
            "--dataset",
            str(dataset_path),
            "--annotations",
            str(annotations_path),
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    manifest = json.loads((output_path.parent / "manifest.json").read_text(encoding="utf-8"))
    assert payload["version"] == "v2"
    assert payload["cases"][0]["annotations"][0]["label"] == "hard_case"
    assert payload["cases"][0]["labels"] == ["hard_case"]
    assert manifest["annotation_count"] == 1
    assert manifest["source_dataset"]["version"] == "v1"


def test_dataset_derive_split_materializes_hard_case_subset(tmp_path: Path) -> None:
    dataset_path = tmp_path / "datasets" / "benchmark-cases" / "v2" / "dataset.json"
    output_path = tmp_path / "datasets" / "benchmark-cases-hard" / "v1" / "dataset.json"
    write_json(
        dataset_path,
        {
            "dataset_id": "benchmark-cases",
            "version": "v2",
            "schema_version": "2026-04-06",
            "case_count": 2,
            "cases": [
                {
                    "case_id": "task_set:task-a",
                    "source_type": "task_set",
                    "run_id": "task-set",
                    "profile": "task-set",
                    "project": "task-set",
                    "task_id": "task-a",
                    "phase": "benchmark_probe",
                    "raw_error": "",
                    "failure_signature": "",
                    "labels": ["hard_case"],
                },
                {
                    "case_id": "task_set:task-b",
                    "source_type": "task_set",
                    "run_id": "task-set",
                    "profile": "task-set",
                    "project": "task-set",
                    "task_id": "task-b",
                    "phase": "benchmark_probe",
                    "raw_error": "",
                    "failure_signature": "",
                    "labels": [],
                },
            ],
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "dataset",
            "derive-split",
            "--dataset",
            str(dataset_path),
            "--split",
            "hard_case",
            "--dataset-id",
            "benchmark-cases-hard",
            "--version",
            "v1",
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["dataset_id"] == "benchmark-cases-hard"
    assert payload["split"] == "hard_case"
    assert payload["case_count"] == 1
    assert payload["cases"][0]["task_id"] == "task-a"


def test_dataset_promote_records_current_version_and_metadata(tmp_path: Path) -> None:
    datasets_root = tmp_path / "datasets"
    dataset_path = datasets_root / "benchmark-cases" / "v2" / "dataset.json"
    write_json(
        dataset_path,
        {
            "dataset_id": "benchmark-cases",
            "version": "v2",
            "schema_version": "2026-04-06",
            "case_count": 1,
            "cases": [],
            "split": "hard_case",
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "dataset",
            "promote",
            "--datasets-root",
            str(datasets_root),
            "--dataset-id",
            "benchmark-cases",
            "--version",
            "v2",
            "--promoted-by",
            "tester",
            "--reason",
            "ready for regression",
            "--split",
            "hard_case",
        ],
    )

    assert result.exit_code == 0
    promotions = json.loads((datasets_root / "promotions.json").read_text(encoding="utf-8"))
    records = json.loads((datasets_root / "promotion_records.json").read_text(encoding="utf-8"))
    promotion_target = json.loads(
        (datasets_root / "benchmark-cases" / "v2" / "promotion_target.json").read_text(
            encoding="utf-8"
        )
    )
    assert promotions["benchmark-cases:hard_case"] == "v2"
    assert records["benchmark-cases:hard_case"]["promoted_by"] == "tester"
    assert promotion_target["dataset"]["dataset_id"] == "benchmark-cases"
    assert promotion_target["promotion_summary"]["case_count"] == 1
