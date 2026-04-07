from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

import meta_harness.cli as cli_module
from meta_harness.cli import app


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_base_config(config_root: Path, repo_root: Path) -> None:
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


def write_web_scrape_pack_assets(config_root: Path) -> None:
    write_json(
        config_root / "evaluator_packs" / "web_scrape_core.json",
        {
            "pack_id": "web_scrape/core",
            "supported_primitives": ["web_scrape"],
            "command": ["python", "scripts/eval_web_scrape.py"],
        },
    )


def test_workflow_inspect_reports_summary(tmp_path: Path) -> None:
    workflow_path = tmp_path / "workflows" / "news_aggregation.json"
    write_json(
        workflow_path,
        {
            "workflow_id": "news_aggregation",
            "evaluator_packs": ["web_scrape/core"],
            "steps": [
                {
                    "step_id": "fetch_homepages",
                    "primitive_id": "web_scrape",
                    "command": ["python", "scripts/fetch.py"],
                },
                {
                    "step_id": "merge_results",
                    "primitive_id": "message_aggregate",
                    "depends_on": ["fetch_homepages"],
                    "command": ["python", "scripts/merge.py"],
                },
            ],
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "workflow",
            "inspect",
            "--workflow",
            str(workflow_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload == {
        "workflow_id": "news_aggregation",
        "step_count": 2,
        "primitive_ids": ["message_aggregate", "web_scrape"],
        "evaluator_packs": ["web_scrape/core"],
    }


def test_workflow_compile_writes_runtime_task_set(tmp_path: Path) -> None:
    workflow_path = tmp_path / "workflows" / "news_aggregation.json"
    output_path = tmp_path / "compiled" / "news_aggregation.task_set.json"
    write_json(
        workflow_path,
        {
            "workflow_id": "news_aggregation",
            "steps": [
                {
                    "step_id": "fetch_homepages",
                    "primitive_id": "web_scrape",
                    "command": ["python", "scripts/fetch.py"],
                }
            ],
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "workflow",
            "compile",
            "--workflow",
            str(workflow_path),
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["workflow_id"] == "news_aggregation"
    assert payload["tasks"][0]["task_id"] == "fetch_homepages"
    assert Path(result.stdout.strip()) == output_path


def test_workflow_run_compiles_then_executes_managed_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    candidates_root = tmp_path / "candidates"
    workflow_path = tmp_path / "workflows" / "news_aggregation.json"
    repo_root.mkdir(parents=True, exist_ok=True)
    write_base_config(config_root, repo_root)
    write_json(
        workflow_path,
        {
            "workflow_id": "news_aggregation",
            "steps": [
                {
                    "step_id": "fetch_homepages",
                    "primitive_id": "web_scrape",
                    "command": ["python", "scripts/fetch.py"],
                }
            ],
        },
    )

    captured: dict[str, object] = {}

    def fake_execute_managed_run(**kwargs):
        captured.update(kwargs)
        task_set_path = Path(str(kwargs["task_set_path"]))
        payload = json.loads(task_set_path.read_text(encoding="utf-8"))
        captured["compiled_payload"] = payload
        return {
            "run_id": "run-workflow",
            "task_summary": {"succeeded": 1, "total": 1},
            "score": {"composite": 1.0},
        }

    monkeypatch.setattr(cli_module, "execute_managed_run", fake_execute_managed_run)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "workflow",
            "run",
            "--workflow",
            str(workflow_path),
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
    payload = json.loads(result.stdout)
    assert payload["run_id"] == "run-workflow"
    assert captured["profile_name"] == "base"
    assert captured["project_name"] == "demo"
    assert captured["compiled_payload"]["tasks"][0]["scenario"] == "web_scrape"


def test_workflow_run_binds_declared_evaluator_packs_into_effective_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    candidates_root = tmp_path / "candidates"
    workflow_path = tmp_path / "workflows" / "news_aggregation.json"
    repo_root.mkdir(parents=True, exist_ok=True)
    write_base_config(config_root, repo_root)
    write_web_scrape_pack_assets(config_root)
    write_json(
        workflow_path,
        {
            "workflow_id": "news_aggregation",
            "evaluator_packs": ["web_scrape/core"],
            "steps": [
                {
                    "step_id": "fetch_homepages",
                    "primitive_id": "web_scrape",
                    "command": ["python", "scripts/fetch.py"],
                }
            ],
        },
    )

    captured: dict[str, object] = {}

    def fake_execute_managed_run(**kwargs):
        captured.update(kwargs)
        return {
            "run_id": "run-workflow",
            "task_summary": {"succeeded": 1, "total": 1},
            "score": {"composite": 1.0},
        }

    monkeypatch.setattr(cli_module, "execute_managed_run", fake_execute_managed_run)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "workflow",
            "run",
            "--workflow",
            str(workflow_path),
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
    evaluation = captured["effective_config"]["evaluation"]
    assert evaluation["evaluators"] == ["basic", "command"]
    assert evaluation["command_evaluators"] == [
        {
            "name": "web_scrape/core",
            "command": ["python", "scripts/eval_web_scrape.py"],
        }
    ]


def test_workflow_benchmark_compiles_then_runs_benchmark(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    candidates_root = tmp_path / "candidates"
    workflow_path = tmp_path / "workflows" / "news_aggregation.json"
    benchmark_spec = tmp_path / "benchmark.json"
    repo_root.mkdir(parents=True, exist_ok=True)
    write_base_config(config_root, repo_root)
    write_json(
        benchmark_spec,
        {
            "experiment": "workflow-ab",
            "baseline": "baseline",
            "variants": [{"name": "baseline"}],
        },
    )
    write_json(
        workflow_path,
        {
            "workflow_id": "news_aggregation",
            "steps": [
                {
                    "step_id": "fetch_homepages",
                    "primitive_id": "web_scrape",
                    "command": ["python", "scripts/fetch.py"],
                }
            ],
        },
    )

    captured: dict[str, object] = {}

    def fake_run_benchmark(**kwargs):
        captured.update(kwargs)
        task_set_path = Path(str(kwargs["task_set_path"]))
        captured["compiled_payload"] = json.loads(task_set_path.read_text(encoding="utf-8"))
        return {"experiment": "workflow-ab", "best_variant": "baseline", "variants": []}

    monkeypatch.setattr(cli_module, "run_benchmark", fake_run_benchmark)
    monkeypatch.setattr(
        cli_module,
        "compact_runs",
        lambda *args, **kwargs: {"compacted_runs": []},
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "workflow",
            "benchmark",
            "--workflow",
            str(workflow_path),
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
            "--spec",
            str(benchmark_spec),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["experiment"] == "workflow-ab"
    assert captured["profile_name"] == "base"
    assert captured["compiled_payload"]["tasks"][0]["task_id"] == "fetch_homepages"


def test_workflow_benchmark_infers_evaluator_packs_from_primitives(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    candidates_root = tmp_path / "candidates"
    workflow_path = tmp_path / "workflows" / "news_aggregation.json"
    benchmark_spec = tmp_path / "benchmark.json"
    repo_root.mkdir(parents=True, exist_ok=True)
    write_base_config(config_root, repo_root)
    write_web_scrape_pack_assets(config_root)
    write_json(
        benchmark_spec,
        {
            "experiment": "workflow-ab",
            "baseline": "baseline",
            "variants": [{"name": "baseline"}],
        },
    )
    write_json(
        workflow_path,
        {
            "workflow_id": "news_aggregation",
            "steps": [
                {
                    "step_id": "fetch_homepages",
                    "primitive_id": "web_scrape",
                    "command": ["python", "scripts/fetch.py"],
                }
            ],
        },
    )

    captured: dict[str, object] = {}

    def fake_run_benchmark(**kwargs):
        captured.update(kwargs)
        return {"experiment": "workflow-ab", "best_variant": "baseline", "variants": []}

    monkeypatch.setattr(cli_module, "run_benchmark", fake_run_benchmark)
    monkeypatch.setattr(
        cli_module,
        "compact_runs",
        lambda *args, **kwargs: {"compacted_runs": []},
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "workflow",
            "benchmark",
            "--workflow",
            str(workflow_path),
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
            "--spec",
            str(benchmark_spec),
        ],
    )

    assert result.exit_code == 0
    evaluation = captured["effective_config_override"]["evaluation"]
    assert evaluation["evaluators"] == ["basic", "command"]
    assert evaluation["command_evaluators"] == [
        {
            "name": "web_scrape/core",
            "command": ["python", "scripts/eval_web_scrape.py"],
        }
    ]
