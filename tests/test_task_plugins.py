from __future__ import annotations

import json
from pathlib import Path

from meta_harness.task_plugins.classification import ClassificationTaskPlugin
from meta_harness.task_plugins.code_repair import CodeRepairTaskPlugin
from meta_harness.task_plugins.extraction import ExtractionTaskPlugin
from meta_harness.task_plugins.web_scrape import WebScrapeTaskPlugin


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_extraction_task_plugin_surfaces_required_fields_and_schema_hints(
    tmp_path: Path,
) -> None:
    task_set_path = tmp_path / "task_set.json"
    write_json(
        task_set_path,
        {
            "tasks": [
                {
                    "task_id": "extract-company",
                    "scenario": "structured_extract",
                    "expectations": {
                        "required_fields": ["name", "price", "contact_email"],
                        "artifact_requirements": ["page.html", "extracted.json"],
                        "page_profile": {"schema_stability": "volatile"},
                    },
                    "phases": [{"phase": "extract", "command": ["python", "-c", "print('ok')"]}],
                },
                {
                    "task_id": "extract-summary",
                    "scenario": "structured_extract",
                    "expectations": {
                        "required_fields": ["name", "summary"],
                        "artifact_requirements": ["extracted.json"],
                        "page_profile": {"schema_stability": "stable"},
                    },
                    "phases": [{"phase": "extract", "command": ["python", "-c", "print('ok')"]}],
                },
            ]
        },
    )

    plugin = ExtractionTaskPlugin()
    objective = plugin.assemble_objective(
        profile_name="base",
        project_name="demo",
        task_set_path=task_set_path,
        effective_config={"evaluation": {"evaluators": ["basic"]}},
    )
    experience = plugin.assemble_experience(
        runs_root=tmp_path / "runs",
        candidates_root=tmp_path / "candidates",
        selected_runs=[
            {"run_id": "run-a", "score_report": {"composite": 0.8}},
            {"run_id": "run-b", "score_report": {"composite": 1.1}},
        ],
        objective=objective,
    )
    plan = plugin.build_evaluation_plan(
        objective=objective,
        effective_config={"evaluation": {"evaluators": ["basic"]}},
    )

    extraction = objective["extraction"]
    assert extraction["task_count"] == 2
    assert extraction["required_fields"] == [
        "contact_email",
        "name",
        "price",
        "summary",
    ]
    assert extraction["artifact_requirements"] == ["extracted.json", "page.html"]
    assert extraction["schema_stability_counts"] == {"stable": 1, "volatile": 1}
    assert experience["extraction"]["best_references"][0]["run_id"] == "run-b"
    assert "field completeness" in " ".join(plan["notes"]).lower()


def test_base_task_plugin_build_evaluation_plan_preserves_validation_gate_config(
    tmp_path: Path,
) -> None:
    task_set_path = tmp_path / "task_set.json"
    write_json(task_set_path, {"tasks": []})

    plugin = ExtractionTaskPlugin()
    objective = plugin.assemble_objective(
        profile_name="base",
        project_name="demo",
        task_set_path=task_set_path,
        effective_config={
            "evaluation": {
                "evaluators": ["basic"],
                "validation_command": ["python", "-m", "pytest", "-q", "tests/test_smoke.py"],
                "validation_workdir": ".",
            }
        },
    )
    plan = plugin.build_evaluation_plan(
        objective=objective,
        effective_config={
            "evaluation": {
                "evaluators": ["basic"],
                "validation_command": ["python", "-m", "pytest", "-q", "tests/test_smoke.py"],
                "validation_workdir": ".",
            }
        },
    )

    assert plan["validation_command"] == [
        "python",
        "-m",
        "pytest",
        "-q",
        "tests/test_smoke.py",
    ]
    assert plan["validation_workdir"] == "."


def test_classification_task_plugin_surfaces_label_space_and_ambiguity(
    tmp_path: Path,
) -> None:
    task_set_path = tmp_path / "task_set.json"
    write_json(
        task_set_path,
        {
            "tasks": [
                {
                    "task_id": "classify-ticket",
                    "scenario": "classification",
                    "expectations": {
                        "label_space": ["bug", "question", "feature_request"],
                    },
                    "phases": [{"phase": "classify", "command": ["python", "-c", "print('ok')"]}],
                },
                {
                    "task_id": "triage-escalation",
                    "scenario": "ambiguous_classification",
                    "expectations": {
                        "allowed_labels": ["escalate", "defer"],
                        "decision_mode": "ambiguous_review",
                    },
                    "phases": [{"phase": "classify", "command": ["python", "-c", "print('ok')"]}],
                },
            ]
        },
    )

    plugin = ClassificationTaskPlugin()
    objective = plugin.assemble_objective(
        profile_name="base",
        project_name="demo",
        task_set_path=task_set_path,
        effective_config={"evaluation": {"evaluators": ["basic"]}},
    )
    experience = plugin.assemble_experience(
        runs_root=tmp_path / "runs",
        candidates_root=tmp_path / "candidates",
        selected_runs=[
            {"run_id": "run-a", "score_report": {"composite": 0.2}, "candidate_id": "cand-a"},
            {"run_id": "run-b", "score_report": {"composite": 1.0}, "candidate_id": "cand-b"},
        ],
        objective=objective,
    )
    plan = plugin.build_evaluation_plan(
        objective=objective,
        effective_config={"evaluation": {"evaluators": ["basic"]}},
    )

    classification = objective["classification"]
    assert classification["task_count"] == 2
    assert classification["labels"] == [
        "bug",
        "defer",
        "escalate",
        "feature_request",
        "question",
    ]
    assert classification["label_count"] == 5
    assert classification["ambiguous_task_count"] == 1
    assert experience["classification"]["low_confidence_runs"][0]["run_id"] == "run-a"
    assert experience["classification"]["candidate_ids"] == ["cand-a", "cand-b"]
    assert "decision consistency" in " ".join(plan["notes"]).lower()


def test_web_scrape_task_plugin_exposes_query_constraints_and_stopping_policy(
    tmp_path: Path,
) -> None:
    task_set_path = tmp_path / "task_set.json"
    write_json(
        task_set_path,
        {
            "tasks": [
                {
                    "task_id": "scrape-a",
                    "scenario": "web_scrape",
                    "expectations": {"requires_rendering": True},
                    "phases": [{"phase": "scrape", "command": ["python", "-c", "print('ok')"]}],
                }
            ]
        },
    )
    plugin = WebScrapeTaskPlugin()
    objective = plugin.assemble_objective(
        profile_name="base",
        project_name="demo",
        task_set_path=task_set_path,
        effective_config={"page_profile": {"anti_bot_level": "high"}},
    )
    query = plugin.build_experience_query(
        objective=objective,
        effective_config={"page_profile": {"anti_bot_level": "high"}},
    )
    constraints = plugin.build_proposal_constraints(
        objective=objective,
        effective_config={"page_profile": {"anti_bot_level": "high"}},
        experience={"representative_failures": [{"family": "render timeout"}]},
        evaluation_plan={},
    )
    stopping = plugin.build_stopping_policy(
        objective=objective,
        effective_config={},
        evaluation_plan={},
    )

    assert query["focus"] == "web_scrape"
    assert query["dedupe_failure_families"] is True
    assert constraints["rendering_required"] is True
    assert constraints["anti_bot_level"] == "high"
    assert stopping["no_improvement_limit"] == 1


def test_code_repair_task_plugin_exposes_query_constraints_and_stopping_policy(
    tmp_path: Path,
) -> None:
    task_set_path = tmp_path / "task_set.json"
    write_json(
        task_set_path,
        {
            "tasks": [
                {
                    "task_id": "repair-a",
                    "scenario": "code_repair",
                    "expectations": {"requires_patch": True},
                    "phases": [{"phase": "repair", "command": ["python", "-c", "print('ok')"]}],
                }
            ]
        },
    )
    plugin = CodeRepairTaskPlugin()
    objective = plugin.assemble_objective(
        profile_name="base",
        project_name="demo",
        task_set_path=task_set_path,
        effective_config={"optimization": {"patch_strategy": "minimal_diff"}},
    )
    query = plugin.build_experience_query(
        objective=objective,
        effective_config={"optimization": {"patch_strategy": "minimal_diff"}},
    )
    constraints = plugin.build_proposal_constraints(
        objective=objective,
        effective_config={"optimization": {"patch_strategy": "minimal_diff"}},
        experience={"code_repair": {"repair_candidates": ["cand-a", "cand-b"]}},
        evaluation_plan={},
    )
    stopping = plugin.build_stopping_policy(
        objective=objective,
        effective_config={},
        evaluation_plan={},
    )

    assert query["focus"] == "code_repair"
    assert query["best_k"] == 4
    assert constraints["patch_strategy_hint"] == "minimal_diff"
    assert constraints["repair_candidates"] == ["cand-a", "cand-b"]
    assert stopping["regression_tolerance"] == 0.2
