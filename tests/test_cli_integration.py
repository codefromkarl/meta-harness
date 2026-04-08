from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from typer.testing import CliRunner

import meta_harness.cli as cli_module
from meta_harness.cli import app
from meta_harness.adapter_scaffolder import materialize_scaffold
from meta_harness.execution_model_inferer import infer_execution_model
from meta_harness.integration_intake import build_integration_intent
from meta_harness.integration_schemas import (
    ExecutionModel,
    HarnessSpec,
    IntegrationSpec,
    ScaffoldPlan,
)
from meta_harness.target_project_inspector import inspect_target_project
from meta_harness.services.integration_service import (
    analyze_integration_payload,
    benchmark_integration_payload,
    benchmark_harness_payload,
    review_harness_payload,
    review_integration_payload,
    scaffold_harness_payload,
    scaffold_integration_payload,
)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_web_scrape_primitive(config_root: Path) -> None:
    write_json(
        config_root / "primitives" / "web_scrape.json",
        {
            "primitive_id": "web_scrape",
            "kind": "browser_interaction",
            "output_contract": {
                "bridge": {
                    "response_fields": [
                        {"name": "page_html", "type": "string"},
                        {"name": "extracted", "type": "object"},
                    ],
                    "artifact_writes": [
                        {"path": "page.html", "payload_path": "page_html", "format": "text"},
                        {
                            "path": "extracted.json",
                            "payload_path": "extracted",
                            "format": "json",
                        },
                    ],
                }
            },
            "evaluation_contract": {
                "artifact_requirements": ["page.html", "extracted.json"],
            },
        },
    )


def build_target_project(project_root: Path) -> Path:
    write_text(
        project_root / "README.md",
        "# Demo scraper\n\nRun the workflow and collect `result.json` under `outputs/`.\n",
    )
    write_text(
        project_root / "pyproject.toml",
        "[project]\nname='demo-scraper'\nversion='0.1.0'\n[project.scripts]\ndemo-scrape='scripts.run:main'\n",
    )
    write_text(
        project_root / "scripts" / "run.py",
        "import json\nfrom pathlib import Path\n\n"
        "def main():\n"
        "    Path('outputs').mkdir(exist_ok=True)\n"
        "    Path('outputs/result.json').write_text(json.dumps({'title': 'Example'}), encoding='utf-8')\n"
        "    print('done')\n",
    )
    workflow_path = project_root / "workflow.yaml"
    write_text(
        workflow_path,
        "steps:\n"
        "  - id: scrape\n"
        "    run: python scripts/run.py\n"
        "outputs:\n"
        "  result: outputs/result.json\n",
    )
    return workflow_path


def build_cli_proxy_project(project_root: Path) -> None:
    write_text(
        project_root / "README.md",
        "# CLI Proxy\n\nA Rust CLI that filters command output and writes tracking data to SQLite.\n",
    )
    write_text(
        project_root / "Cargo.toml",
        "[package]\nname='proxy-cli'\nversion='0.1.0'\n"
        "description='High-performance CLI proxy'\n",
    )
    write_text(
        project_root / "src" / "main.rs",
        "use std::process::Command;\n\n"
        "fn main() {\n"
        "    let _ = Command::new(\"git\").arg(\"status\").output();\n"
        "    println!(\"proxy complete\");\n"
        "}\n",
    )
    write_text(
        project_root / "src" / "core" / "tracking.rs",
        "pub fn save_tracking() { let _path = \"artifacts/tracking.db\"; }\n",
    )


def test_analyze_integration_payload_writes_reports(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    reports_root = tmp_path / "reports"
    project_root = tmp_path / "target_project"
    write_web_scrape_primitive(config_root)
    workflow_path = build_target_project(project_root)

    payload = analyze_integration_payload(
        config_root=config_root,
        reports_root=reports_root,
        target_project_path=project_root,
        primitive_id="web_scrape",
        workflow_paths=[workflow_path],
        user_goal="分析并生成 integration spec",
    )

    assert payload["primitive_id"] == "web_scrape"
    assert Path(payload["observation_path"]).exists()
    assert Path(payload["integration_spec_path"]).exists()
    assert Path(payload["review_checklist_path"]).exists()

    observation = json.loads(Path(payload["observation_path"]).read_text(encoding="utf-8"))
    spec = json.loads(Path(payload["integration_spec_path"]).read_text(encoding="utf-8"))
    checklist = Path(payload["review_checklist_path"]).read_text(encoding="utf-8")

    assert observation["workflow_files"] == [str(workflow_path)]
    assert observation["detected_entrypoints"]
    assert any(item["path"].endswith("result.json") for item in observation["output_candidates"])
    assert spec["execution_model"]["kind"] == "file_artifact_workflow"
    assert any(item["target_artifact"] == "extracted.json" for item in spec["artifact_mappings"])
    assert "入口命令是否正确" in spec["manual_checks"]
    assert "Integration Review Checklist" in checklist


def test_analyze_integration_payload_without_primitive_emits_harness_spec(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    reports_root = tmp_path / "reports"
    project_root = tmp_path / "proxy_project"
    build_cli_proxy_project(project_root)

    payload = analyze_integration_payload(
        config_root=config_root,
        reports_root=reports_root,
        target_project_path=project_root,
        user_goal="分析通用 CLI 项目的 harness 能力",
    )

    assert payload["primitive_id"] is None
    assert payload["integration_spec_path"] is None
    assert Path(payload["harness_spec_path"]).exists()

    harness_spec = HarnessSpec.model_validate_json(
        Path(payload["harness_spec_path"]).read_text(encoding="utf-8")
    )
    assert harness_spec.execution_model.kind == "json_stdout_cli"
    assert "command_proxy" in harness_spec.capability_modules
    assert "output_filter" in harness_spec.capability_modules
    assert harness_spec.candidate_primitives == []


def test_cli_integration_analyze_accepts_intent_text(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    reports_root = tmp_path / "reports"
    project_root = tmp_path / "target_project"
    write_web_scrape_primitive(config_root)
    workflow_path = build_target_project(project_root)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "integration",
            "analyze",
            "--intent",
            f"把 {project_root} 适配到 web_scrape",
            "--workflow",
            str(workflow_path),
            "--config-root",
            str(config_root),
            "--reports-root",
            str(reports_root),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["primitive_id"] == "web_scrape"
    assert Path(payload["integration_spec_path"]).exists()


def test_cli_integration_analyze_accepts_project_without_primitive(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    reports_root = tmp_path / "reports"
    project_root = tmp_path / "proxy_project"
    build_cli_proxy_project(project_root)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "integration",
            "analyze",
            "--target-project",
            str(project_root),
            "--config-root",
            str(config_root),
            "--reports-root",
            str(reports_root),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["primitive_id"] is None
    assert payload["integration_spec_path"] is None
    assert Path(payload["harness_spec_path"]).exists()


def test_scaffold_harness_payload_writes_generic_wrapper_and_test(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    reports_root = tmp_path / "reports"
    project_root = tmp_path / "proxy_project"
    build_cli_proxy_project(project_root)

    analysis = analyze_integration_payload(
        config_root=config_root,
        reports_root=reports_root,
        target_project_path=project_root,
        user_goal="分析通用 CLI 项目的 harness 能力",
    )

    payload = scaffold_harness_payload(
        config_root=config_root,
        harness_spec_path=Path(analysis["harness_spec_path"]),
    )

    wrapper_path = Path(payload["wrapper_path"])
    test_path = Path(payload["test_path"])
    scaffold_report_path = Path(payload["scaffold_result_path"])

    assert wrapper_path.exists()
    assert test_path.exists()
    assert scaffold_report_path.exists()
    wrapper = wrapper_path.read_text(encoding="utf-8")
    test_draft = test_path.read_text(encoding="utf-8")
    assert "cargo" in wrapper
    assert "command_proxy" in wrapper
    assert "pytest.mark.skip" in test_draft


def test_cli_integration_scaffold_accepts_harness_spec(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    reports_root = tmp_path / "reports"
    project_root = tmp_path / "proxy_project"
    build_cli_proxy_project(project_root)

    analysis = analyze_integration_payload(
        config_root=config_root,
        reports_root=reports_root,
        target_project_path=project_root,
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "integration",
            "scaffold",
            "--harness-spec",
            analysis["harness_spec_path"],
            "--config-root",
            str(config_root),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert Path(payload["wrapper_path"]).exists()


def test_build_integration_intent_can_infer_project_from_workflow_path(tmp_path: Path) -> None:
    project_root = tmp_path / "target_project"
    workflow_path = build_target_project(project_root)

    intent = build_integration_intent(
        workflow_paths=[workflow_path],
        primitive_id="web_scrape",
    )

    assert intent.target_project_path == str(project_root.resolve())
    assert intent.workflow_files == [str(workflow_path.resolve())]


def test_scaffold_integration_payload_writes_binding_wrapper_and_test_drafts(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    reports_root = tmp_path / "reports"
    project_root = tmp_path / "target_project"
    write_web_scrape_primitive(config_root)
    workflow_path = build_target_project(project_root)
    analysis = analyze_integration_payload(
        config_root=config_root,
        reports_root=reports_root,
        target_project_path=project_root,
        primitive_id="web_scrape",
        workflow_paths=[workflow_path],
        user_goal="分析并生成 integration spec",
    )

    payload = scaffold_integration_payload(
        config_root=config_root,
        spec_path=Path(analysis["integration_spec_path"]),
    )

    binding_path = Path(payload["binding_path"])
    wrapper_path = Path(payload["wrapper_path"])
    test_path = Path(payload["test_path"])
    report_path = Path(payload["scaffold_result_path"])

    assert binding_path.exists()
    assert wrapper_path.exists()
    assert test_path.exists()
    assert report_path.exists()

    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    wrapper = wrapper_path.read_text(encoding="utf-8")
    test_draft = test_path.read_text(encoding="utf-8")

    assert binding["binding_id"].startswith("generated/")
    assert binding["adapter_kind"] == "command"
    assert binding["execution"]["parse_json_output"] is True
    assert binding["execution"]["bridge_contract"] == "primitive_output"
    assert binding["execution"]["command"][0] == "python"
    assert "outputs/result.json" in wrapper
    assert '"missing_contracts"' in wrapper
    assert '"normalize_from"' in wrapper
    assert "pytest.mark.skip" in test_draft


def test_cli_integration_scaffold_generates_draft_files(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    reports_root = tmp_path / "reports"
    project_root = tmp_path / "target_project"
    write_web_scrape_primitive(config_root)
    workflow_path = build_target_project(project_root)
    analysis = analyze_integration_payload(
        config_root=config_root,
        reports_root=reports_root,
        target_project_path=project_root,
        primitive_id="web_scrape",
        workflow_paths=[workflow_path],
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "integration",
            "scaffold",
            "--spec",
            analysis["integration_spec_path"],
            "--config-root",
            str(config_root),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert Path(payload["binding_path"]).exists()


def test_review_integration_payload_applies_overrides_and_activates_binding(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    reports_root = tmp_path / "reports"
    project_root = tmp_path / "target_project"
    write_web_scrape_primitive(config_root)
    workflow_path = build_target_project(project_root)
    analysis = analyze_integration_payload(
        config_root=config_root,
        reports_root=reports_root,
        target_project_path=project_root,
        primitive_id="web_scrape",
        workflow_paths=[workflow_path],
    )
    scaffold = scaffold_integration_payload(
        config_root=config_root,
        spec_path=Path(analysis["integration_spec_path"]),
    )
    overrides_path = tmp_path / "review_overrides.json"
    write_json(
        overrides_path,
        {
            "binding_patch": {
                "execution": {
                    "env": {
                        "REVIEW_APPROVED": "1",
                    }
                }
            }
        },
    )

    payload = review_integration_payload(
        config_root=config_root,
        spec_path=Path(analysis["integration_spec_path"]),
        reviewer="reviewer-a",
        approve_all_checks=True,
        overrides_path=overrides_path,
        activate_binding=True,
    )

    reviewed_spec_path = Path(payload["reviewed_spec_path"])
    review_result_path = Path(payload["review_result_path"])
    activation_path = Path(payload["activation_path"])
    binding_path = Path(payload["binding_path"])

    assert payload["status"] == "activated"
    assert reviewed_spec_path.exists()
    assert review_result_path.exists()
    assert activation_path.exists()
    reviewed_spec = json.loads(reviewed_spec_path.read_text(encoding="utf-8"))
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    activation = json.loads(activation_path.read_text(encoding="utf-8"))

    assert reviewed_spec["binding_patch"]["execution"]["env"]["REVIEW_APPROVED"] == "1"
    assert binding["review"]["status"] == "activated"
    assert binding["review"]["reviewer"] == "reviewer-a"
    assert activation["binding_id"] == payload["binding_id"]
    assert activation["status"] == "activated"


def test_review_harness_payload_records_review_without_activation(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    reports_root = tmp_path / "reports"
    project_root = tmp_path / "proxy_project"
    build_cli_proxy_project(project_root)

    analysis = analyze_integration_payload(
        config_root=config_root,
        reports_root=reports_root,
        target_project_path=project_root,
    )
    scaffold_harness_payload(
        config_root=config_root,
        harness_spec_path=Path(analysis["harness_spec_path"]),
    )

    payload = review_harness_payload(
        harness_spec_path=Path(analysis["harness_spec_path"]),
        reviewer="reviewer-a",
        approve_all_checks=True,
        notes="harness-first review",
    )

    assert payload["status"] == "approved"
    assert Path(payload["review_result_path"]).exists()
    assert Path(payload["review_history_path"]).exists()
    assert payload["activation_path"] is None


def test_cli_integration_review_accepts_harness_spec(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    reports_root = tmp_path / "reports"
    project_root = tmp_path / "proxy_project"
    build_cli_proxy_project(project_root)

    analysis = analyze_integration_payload(
        config_root=config_root,
        reports_root=reports_root,
        target_project_path=project_root,
    )
    scaffold_harness_payload(
        config_root=config_root,
        harness_spec_path=Path(analysis["harness_spec_path"]),
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "integration",
            "review",
            "--harness-spec",
            analysis["harness_spec_path"],
            "--reviewer",
            "reviewer-a",
            "--approve-all-checks",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "approved"


def test_review_integration_payload_blocks_activation_until_manual_checks_are_approved(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    reports_root = tmp_path / "reports"
    project_root = tmp_path / "target_project"
    write_web_scrape_primitive(config_root)
    workflow_path = build_target_project(project_root)
    analysis = analyze_integration_payload(
        config_root=config_root,
        reports_root=reports_root,
        target_project_path=project_root,
        primitive_id="web_scrape",
        workflow_paths=[workflow_path],
    )
    scaffold_integration_payload(
        config_root=config_root,
        spec_path=Path(analysis["integration_spec_path"]),
    )

    try:
        review_integration_payload(
            config_root=config_root,
            spec_path=Path(analysis["integration_spec_path"]),
            reviewer="reviewer-a",
            approve_checks=["入口命令是否正确"],
            activate_binding=True,
        )
    except ValueError as exc:
        assert "manual checks" in str(exc)
    else:
        raise AssertionError("expected review activation to require all manual checks")


def test_cli_integration_review_approves_and_activates_binding(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    reports_root = tmp_path / "reports"
    project_root = tmp_path / "target_project"
    write_web_scrape_primitive(config_root)
    workflow_path = build_target_project(project_root)
    analysis = analyze_integration_payload(
        config_root=config_root,
        reports_root=reports_root,
        target_project_path=project_root,
        primitive_id="web_scrape",
        workflow_paths=[workflow_path],
    )
    scaffold_integration_payload(
        config_root=config_root,
        spec_path=Path(analysis["integration_spec_path"]),
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "integration",
            "review",
            "--spec",
            analysis["integration_spec_path"],
            "--reviewer",
            "reviewer-a",
            "--approve-all-checks",
            "--activate-binding",
            "--config-root",
            str(config_root),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "activated"
    assert Path(payload["activation_path"]).exists()


def test_review_integration_payload_appends_review_history(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    reports_root = tmp_path / "reports"
    project_root = tmp_path / "target_project"
    write_web_scrape_primitive(config_root)
    workflow_path = build_target_project(project_root)
    analysis = analyze_integration_payload(
        config_root=config_root,
        reports_root=reports_root,
        target_project_path=project_root,
        primitive_id="web_scrape",
        workflow_paths=[workflow_path],
    )
    scaffold_integration_payload(
        config_root=config_root,
        spec_path=Path(analysis["integration_spec_path"]),
    )

    review_integration_payload(
        config_root=config_root,
        spec_path=Path(analysis["integration_spec_path"]),
        reviewer="reviewer-a",
        approve_checks=["入口命令是否正确"],
        notes="first pass",
    )
    payload = review_integration_payload(
        config_root=config_root,
        spec_path=Path(analysis["integration_spec_path"]),
        reviewer="reviewer-b",
        approve_all_checks=True,
        notes="second pass",
    )

    history_path = Path(payload["review_history_path"])
    lines = history_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["reviewer"] == "reviewer-a"
    assert second["reviewer"] == "reviewer-b"


def test_benchmark_integration_payload_generates_and_runs_spec(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    reports_root = tmp_path / "reports"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    project_root = tmp_path / "target_project"
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
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
            "overrides": {"runtime": {"workspace": {"source_repo": str(repo_root)}}},
        },
    )
    write_web_scrape_primitive(config_root)
    workflow_path = build_target_project(project_root)
    analysis = analyze_integration_payload(
        config_root=config_root,
        reports_root=reports_root,
        target_project_path=project_root,
        primitive_id="web_scrape",
        workflow_paths=[workflow_path],
    )
    scaffold = scaffold_integration_payload(
        config_root=config_root,
        spec_path=Path(analysis["integration_spec_path"]),
    )
    review_integration_payload(
        config_root=config_root,
        spec_path=Path(analysis["integration_spec_path"]),
        reviewer="reviewer-a",
        approve_all_checks=True,
        activate_binding=True,
    )

    task_set_path = tmp_path / "task_set.json"
    write_json(
        task_set_path,
        {
            "tasks": [
                {
                    "task_id": "task-a",
                    "scenario": "web_scrape",
                    "workdir": "${workspace_dir}",
                    "expectations": {"primitive_id": "web_scrape", "required_fields": ["title"]},
                    "phases": [{"phase": "fetch", "command": ["python", "-c", "raise SystemExit(9)"]}],
                }
            ]
        },
    )

    captured: dict[str, object] = {}

    def fake_run_benchmark(**kwargs):
        captured.update(kwargs)
        spec_payload = json.loads(Path(str(kwargs["spec_path"])).read_text(encoding="utf-8"))
        captured["benchmark_spec_payload"] = spec_payload
        return {
            "experiment": spec_payload["experiment"],
            "best_variant": "activated_binding",
            "variants": [{"name": "activated_binding", "binding_id": "generated/target_project_web_scrape"}],
        }

    payload = benchmark_integration_payload(
        config_root=config_root,
        reports_root=reports_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        spec_path=Path(analysis["integration_spec_path"]),
        profile_name="base",
        project_name="demo",
        task_set_path=task_set_path,
        run_benchmark_fn=fake_run_benchmark,
    )

    assert payload["best_variant"] == "activated_binding"
    assert payload["artifact_path"] == "reports/benchmarks/integration-target_project-web_scrape.json"
    assert captured["benchmark_spec_payload"] == {
        "experiment": "integration-target_project-web_scrape",
        "baseline": "baseline",
        "variants": [
            {"name": "baseline"},
            {
                "name": "activated_binding",
                "config_patch": json.loads(Path(scaffold["binding_path"]).read_text(encoding="utf-8"))["binding_patch"],
            },
        ],
    }
    assert (reports_root / "benchmarks" / "integration-target_project-web_scrape.json").exists()


def test_benchmark_harness_payload_generates_candidate_harness_variant(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    reports_root = tmp_path / "reports"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    project_root = tmp_path / "proxy_project"
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
    build_cli_proxy_project(project_root)
    analysis = analyze_integration_payload(
        config_root=config_root,
        reports_root=reports_root,
        target_project_path=project_root,
    )
    scaffold = scaffold_harness_payload(
        config_root=config_root,
        harness_spec_path=Path(analysis["harness_spec_path"]),
    )
    review_harness_payload(
        harness_spec_path=Path(analysis["harness_spec_path"]),
        reviewer="reviewer-a",
        approve_all_checks=True,
    )

    task_set_path = tmp_path / "task_set.json"
    write_json(
        task_set_path,
        {
            "tasks": [
                {
                    "task_id": "task-a",
                    "workdir": "${workspace_dir}",
                    "phases": [{"phase": "exec", "command": ["echo", "hi"]}],
                }
            ]
        },
    )

    captured: dict[str, object] = {}

    def fake_run_benchmark(**kwargs):
        captured.update(kwargs)
        spec_payload = json.loads(Path(str(kwargs["spec_path"])).read_text(encoding="utf-8"))
        captured["benchmark_spec_payload"] = spec_payload
        return {
            "experiment": spec_payload["experiment"],
            "best_variant": "candidate_harness",
            "variants": [{"name": "candidate_harness"}],
        }

    payload = benchmark_harness_payload(
        config_root=config_root,
        reports_root=reports_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        harness_spec_path=Path(analysis["harness_spec_path"]),
        profile_name="base",
        project_name="demo",
        task_set_path=task_set_path,
        run_benchmark_fn=fake_run_benchmark,
    )

    assert payload["best_variant"] == "candidate_harness"
    spec_payload = captured["benchmark_spec_payload"]
    assert captured["effective_config_override"]["runtime"]["workspace"]["source_repo"] == str(
        project_root
    )
    assert captured["effective_config_override"]["evaluation"]["evaluators"] == ["basic"]
    assert spec_payload["variants"][1]["variant_type"] == "harness"
    assert spec_payload["variants"][1]["name"] == "candidate_harness"
    candidate_harness = spec_payload["variants"][1]["candidate_harness"]
    runtime_binding = candidate_harness["runtime"]["binding"]
    assert candidate_harness["wrapper_path"] == scaffold["wrapper_path"]
    assert candidate_harness["iteration_id"]
    assert candidate_harness["proposal_id"]
    assert candidate_harness["source_artifacts"]
    assert candidate_harness["provenance"]["review_result_path"].endswith(
        "harness_review_result.json"
    )
    assert runtime_binding["command"][1] == scaffold["wrapper_path"]


def test_cli_integration_outer_loop_reads_proposal_files(tmp_path: Path, monkeypatch) -> None:
    config_root = tmp_path / "configs"
    reports_root = tmp_path / "reports"
    runs_root = tmp_path / "runs"
    candidates_root = tmp_path / "candidates"
    harness_spec_path = tmp_path / "harness_spec.json"
    task_set_path = tmp_path / "task_set.json"
    proposal_one = tmp_path / "proposal-1.json"
    proposal_two = tmp_path / "proposal-2.json"
    write_json(
        harness_spec_path,
        {
            "spec_id": "harness-demo",
            "target_project_path": str(tmp_path / "project"),
            "execution_model": {"kind": "json_stdout_cli"},
        },
    )
    write_json(task_set_path, {"tasks": []})
    write_json(
        proposal_one,
        {
            "candidate_id": "cand-1",
            "harness_spec_id": "harness-demo",
            "iteration_id": "iter-1",
            "title": "Patch 1",
            "summary": "First proposal",
            "change_kind": "wrapper_patch",
            "target_files": ["scripts/generated/harness_wrapper.py"],
            "patch": {},
            "rationale": ["baseline refinement"],
            "provenance": {"source": "test"},
        },
    )
    write_json(
        proposal_two,
        {
            "candidate_id": "cand-2",
            "harness_spec_id": "harness-demo",
            "iteration_id": "iter-1",
            "title": "Patch 2",
            "summary": "Second proposal",
            "change_kind": "wrapper_patch",
            "target_files": ["scripts/generated/harness_wrapper.py"],
            "patch": {},
            "rationale": ["stronger refinement"],
            "provenance": {"source": "test"},
        },
    )

    captured: dict[str, object] = {}

    def fake_harness_outer_loop_payload(**kwargs):
        captured.update(kwargs)
        return {"iteration_id": "iter-1", "selected_candidate_id": "cand-2"}

    monkeypatch.setattr(cli_module, "harness_outer_loop_payload", fake_harness_outer_loop_payload)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "integration",
            "outer-loop",
            "--harness-spec",
            str(harness_spec_path),
            "--proposal",
            str(proposal_one),
            "--proposal",
            str(proposal_two),
            "--profile",
            "base",
            "--project",
            "demo",
            "--task-set",
            str(task_set_path),
            "--config-root",
            str(config_root),
            "--reports-root",
            str(reports_root),
            "--runs-root",
            str(runs_root),
            "--candidates-root",
            str(candidates_root),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["selected_candidate_id"] == "cand-2"
    assert captured["candidate_harness_patches"][0]["candidate_id"] == "cand-1"
    assert captured["candidate_harness_patches"][1]["candidate_id"] == "cand-2"


def test_cli_integration_benchmark_accepts_harness_spec(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_benchmark_harness_payload(**kwargs):
        captured.update(kwargs)
        return {"experiment": "harness-demo", "artifact_path": "reports/benchmarks/harness-demo.json"}

    monkeypatch.setattr(cli_module, "benchmark_harness_payload", fake_benchmark_harness_payload)
    harness_spec_path = tmp_path / "harness_spec.json"
    task_set_path = tmp_path / "task_set.json"
    write_json(
        harness_spec_path,
        {
            "spec_id": "harness-demo",
            "target_project_path": "/tmp/project",
            "execution_model": {"kind": "json_stdout_cli"},
            "capability_modules": ["command_proxy"],
            "manual_checks": [],
        },
    )
    write_json(task_set_path, {"tasks": []})

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "integration",
            "benchmark",
            "--harness-spec",
            str(harness_spec_path),
            "--profile",
            "base",
            "--project",
            "demo",
            "--task-set",
            str(task_set_path),
        ],
    )

    assert result.exit_code == 0
    assert captured["profile_name"] == "base"
    assert json.loads(result.stdout)["experiment"] == "harness-demo"


def test_cli_integration_benchmark_invokes_service(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_benchmark_integration_payload(**kwargs):
        captured.update(kwargs)
        return {"experiment": "integration-demo", "artifact_path": "reports/benchmarks/integration-demo.json"}

    monkeypatch.setattr(cli_module, "benchmark_integration_payload", fake_benchmark_integration_payload)
    spec_path = tmp_path / "integration_spec.json"
    task_set_path = tmp_path / "task_set.json"
    write_json(spec_path, {"spec_id": "demo", "target_project_path": "/tmp/project", "primitive_id": "web_scrape", "execution_model": {"kind": "unknown"}})
    write_json(task_set_path, {"tasks": []})

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "integration",
            "benchmark",
            "--spec",
            str(spec_path),
            "--profile",
            "base",
            "--project",
            "demo",
            "--task-set",
            str(task_set_path),
        ],
    )

    assert result.exit_code == 0
    assert captured["profile_name"] == "base"
    assert json.loads(result.stdout)["experiment"] == "integration-demo"


def test_materialize_scaffold_uses_execution_model_specific_wrapper_templates(
    tmp_path: Path,
) -> None:
    http_spec = IntegrationSpec(
        spec_id="http-spec",
        target_project_path=str(tmp_path / "http-project"),
        primitive_id="web_scrape",
        execution_model=ExecutionModel(
            kind="http_job_api",
            entry_command=["python", "serve.py"],
            input_mode="http_request",
            output_mode="json_response",
            needs_wrapper=True,
        ),
    )
    browser_spec = IntegrationSpec(
        spec_id="browser-spec",
        target_project_path=str(tmp_path / "browser-project"),
        primitive_id="web_scrape",
        execution_model=ExecutionModel(
            kind="browser_automation",
            entry_command=["python", "browse.py"],
            input_mode="workflow_file",
            output_mode="artifacts",
            needs_wrapper=True,
        ),
    )

    http_plan = ScaffoldPlan(
        files_to_create=["configs/claw_bindings/generated/http.json"],
        generated_binding_id="generated/http",
        generated_wrapper_path="scripts/generated/http_wrapper.py",
        generated_test_path="tests/generated/test_http.py",
    )
    browser_plan = ScaffoldPlan(
        files_to_create=["configs/claw_bindings/generated/browser.json"],
        generated_binding_id="generated/browser",
        generated_wrapper_path="scripts/generated/browser_wrapper.py",
        generated_test_path="tests/generated/test_browser.py",
    )

    http_paths = materialize_scaffold(spec=http_spec, plan=http_plan, repo_root=tmp_path)
    browser_paths = materialize_scaffold(spec=browser_spec, plan=browser_plan, repo_root=tmp_path)

    http_wrapper = Path(http_paths["wrapper_path"]).read_text(encoding="utf-8")
    browser_wrapper = Path(browser_paths["wrapper_path"]).read_text(encoding="utf-8")

    assert "META_HARNESS_HTTP_SUBMIT_URL" in http_wrapper
    assert '"next_steps"' in http_wrapper
    assert '"entry_command"' in http_wrapper
    assert "META_HARNESS_BROWSER_ARTIFACT_DIR" in browser_wrapper
    assert '"next_steps"' in browser_wrapper
    assert '"entry_command"' in browser_wrapper


class _HttpJobWrapperHandler(BaseHTTPRequestHandler):
    submitted_payloads: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        payload = json.loads(body) if body else {}
        self.__class__.submitted_payloads.append(payload)
        response = json.dumps({"job_id": "job-123"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/jobs/job-123":
            payload = {"status": "succeeded", "result_url": "/results/job-123"}
        elif self.path == "/results/job-123":
            payload = {
                "page_html": "<html>ok</html>",
                "extracted": {"title": "Example"},
            }
        else:
            payload = {"status": "unknown"}
        response = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def test_http_job_api_wrapper_can_submit_and_poll_minimal_job(
    tmp_path: Path,
) -> None:
    _HttpJobWrapperHandler.submitted_payloads = []
    server = HTTPServer(("127.0.0.1", 0), _HttpJobWrapperHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        spec = IntegrationSpec(
            spec_id="http-spec",
            target_project_path=str(tmp_path / "http-project"),
            primitive_id="web_scrape",
            execution_model=ExecutionModel(
                kind="http_job_api",
                entry_command=["python", "serve.py"],
                input_mode="http_request",
                output_mode="json_response",
                needs_wrapper=True,
            ),
        )
        plan = ScaffoldPlan(
            files_to_create=["configs/claw_bindings/generated/http.json"],
            generated_binding_id="generated/http",
            generated_wrapper_path="scripts/generated/http_wrapper.py",
            generated_test_path="tests/generated/test_http.py",
        )

        paths = materialize_scaffold(spec=spec, plan=plan, repo_root=tmp_path)
        wrapper_path = Path(paths["wrapper_path"])
        completed = subprocess.run(
            ["python", str(wrapper_path)],
            cwd=tmp_path,
            env={
                **os.environ,
                "META_HARNESS_HTTP_SUBMIT_URL": f"{base_url}/jobs",
                "META_HARNESS_HTTP_POLL_URL_TEMPLATE": f"{base_url}/jobs/{{job_id}}",
                "META_HARNESS_HTTP_RESULT_URL_TEMPLATE": f"{base_url}/results/{{job_id}}",
                "META_HARNESS_HTTP_POLL_ATTEMPTS": "2",
                "META_HARNESS_HTTP_POLL_INTERVAL_SEC": "0.01",
            },
            capture_output=True,
            text=True,
            check=False,
        )

        assert completed.returncode == 0, completed.stderr
        payload = json.loads(completed.stdout)
        assert payload["reply"]["page_html"] == "<html>ok</html>"
        assert payload["reply"]["extracted"] == {"title": "Example"}
        assert _HttpJobWrapperHandler.submitted_payloads[0]["entry_command"] == [
            "python",
            "serve.py",
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_inspect_and_infer_http_job_api_project(tmp_path: Path) -> None:
    project_root = tmp_path / "http_project"
    write_text(
        project_root / "README.md",
        "Submit jobs to http://127.0.0.1:8080/jobs and poll /jobs/<id> for result.json\n",
    )
    write_text(
        project_root / "worker.py",
        "import requests\nrequests.post('http://127.0.0.1:8080/jobs', json={'task': 'x'})\n",
    )
    intent = build_integration_intent(
        target_project_path=project_root,
        primitive_id="web_scrape",
    )

    observation = inspect_target_project(intent)
    model = infer_execution_model(observation)

    assert "service_port" in observation.environment_requirements
    assert model.kind == "http_job_api"
