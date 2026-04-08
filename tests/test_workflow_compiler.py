from __future__ import annotations

import json
from pathlib import Path

import pytest

from meta_harness.schemas import (
    ClawBindingSpec,
    EvaluationContract,
    EvaluationThresholds,
    OptimizationPolicy,
    PageProfile,
    PrimitivePack,
    WorkflowHarnessRef,
    WorkflowSpec,
    WorkflowStep,
    WorkloadProfile,
)
from meta_harness.workflow_compiler import (
    compile_workflow_spec,
    load_workflow_spec,
    write_compiled_workflow_task_set,
)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_load_workflow_spec_reads_json_payload(tmp_path: Path) -> None:
    spec_path = tmp_path / "workflows" / "news_aggregation.json"
    write_json(
        spec_path,
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

    payload = load_workflow_spec(spec_path).model_dump()

    assert payload["workflow_id"] == "news_aggregation"
    assert payload["steps"][0]["primitive_id"] == "web_scrape"


def test_compile_workflow_spec_produces_runtime_compatible_task_set() -> None:
    spec = WorkflowSpec(
        workflow_id="news_aggregation",
        evaluator_packs=["web_scrape/core"],
        page_profile=PageProfile(
            complexity="medium",
            dynamicity="lightly_dynamic",
            requires_rendering=True,
        ),
        workload_profile=WorkloadProfile(
            usage_mode="ad_hoc",
            latency_sla_ms=1500,
            budget_mode="balanced",
        ),
        optimization_policy=OptimizationPolicy(
            allowed_primitives=["web_scrape"],
            objective_weights={"latency_ms": 0.7},
        ),
        steps=[
            WorkflowStep(
                step_id="fetch_homepages",
                primitive_id="web_scrape",
                role="hot_path",
                command=["python", "scripts/fetch.py"],
                workdir="${workspace_dir}",
                page_profile=PageProfile(
                    complexity="high",
                    anti_bot_level="high",
                    requires_interaction=True,
                ),
                workload_profile=WorkloadProfile(
                    usage_mode="recurring",
                    batch_size=12,
                    freshness_requirement="high",
                ),
                evaluation=EvaluationContract(
                    artifact_requirements=["page.html", "extracted.json"],
                    required_fields=["title", "price", "contact_email"],
                    latency_budget_ms=1500,
                    quality_thresholds=EvaluationThresholds(
                        field_completeness=0.8,
                        grounded_field_rate=0.75,
                    ),
                ),
                weight=1.3,
            ),
            WorkflowStep(
                step_id="merge_results",
                primitive_id="message_aggregate",
                role="post_process",
                depends_on=["fetch_homepages"],
                command=["python", "scripts/merge.py"],
                optional=True,
            ),
        ],
    )

    payload = compile_workflow_spec(spec)

    assert payload["workflow_id"] == "news_aggregation"
    assert payload["metadata"]["evaluator_packs"] == ["web_scrape/core"]
    assert payload["metadata"]["page_profile"] == {
        "complexity": "medium",
        "dynamicity": "lightly_dynamic",
        "anti_bot_level": "low",
        "requires_rendering": True,
        "requires_interaction": False,
        "schema_stability": "stable",
        "media_dependency": "low",
    }
    assert payload["metadata"]["workload_profile"] == {
        "usage_mode": "ad_hoc",
        "batch_size": None,
        "latency_sla_ms": 1500,
        "budget_mode": "balanced",
        "freshness_requirement": "medium",
        "allowed_failure_rate": None,
    }
    assert payload["tasks"][0]["task_id"] == "fetch_homepages"
    assert payload["tasks"][0]["scenario"] == "web_scrape"
    assert payload["tasks"][0]["phases"] == [
        {
            "phase": "fetch_homepages",
            "command": ["python", "scripts/fetch.py"],
        }
    ]
    assert payload["tasks"][0]["expectations"]["page_profile"] == {
        "complexity": "high",
        "dynamicity": "lightly_dynamic",
        "anti_bot_level": "high",
        "requires_rendering": True,
        "requires_interaction": True,
        "schema_stability": "stable",
        "media_dependency": "low",
    }
    assert payload["tasks"][0]["expectations"]["workload_profile"] == {
        "usage_mode": "recurring",
        "batch_size": 12,
        "latency_sla_ms": 1500,
        "budget_mode": "balanced",
        "freshness_requirement": "high",
        "allowed_failure_rate": None,
    }
    assert payload["tasks"][0]["expectations"]["role"] == "hot_path"
    assert payload["tasks"][0]["expectations"]["artifact_requirements"] == [
        "page.html",
        "extracted.json",
    ]
    assert payload["tasks"][0]["expectations"]["required_fields"] == [
        "title",
        "price",
        "contact_email",
    ]
    assert payload["tasks"][0]["expectations"]["latency_budget_ms"] == 1500
    assert payload["tasks"][0]["expectations"]["quality_thresholds"] == {
        "field_completeness": 0.8,
        "grounded_field_rate": 0.75,
    }
    assert payload["tasks"][1]["expectations"]["depends_on"] == ["fetch_homepages"]
    assert payload["tasks"][1]["expectations"]["optional"] is True


def test_compile_workflow_spec_topologically_orders_steps() -> None:
    spec = WorkflowSpec(
        workflow_id="ordered_workflow",
        steps=[
            WorkflowStep(
                step_id="finalize",
                primitive_id="message_aggregate",
                depends_on=["extract"],
                command=["python", "scripts/finalize.py"],
            ),
            WorkflowStep(
                step_id="fetch",
                primitive_id="web_scrape",
                command=["python", "scripts/fetch.py"],
            ),
            WorkflowStep(
                step_id="extract",
                primitive_id="structured_extract",
                depends_on=["fetch"],
                command=["python", "scripts/extract.py"],
            ),
        ],
    )

    payload = compile_workflow_spec(spec)

    assert [task["task_id"] for task in payload["tasks"]] == [
        "fetch",
        "extract",
        "finalize",
    ]


def test_compile_workflow_spec_rejects_cycles() -> None:
    spec = WorkflowSpec(
        workflow_id="cyclic",
        steps=[
            WorkflowStep(
                step_id="a",
                primitive_id="web_scrape",
                depends_on=["b"],
                command=["python", "scripts/a.py"],
            ),
            WorkflowStep(
                step_id="b",
                primitive_id="structured_extract",
                depends_on=["a"],
                command=["python", "scripts/b.py"],
            ),
        ],
    )

    with pytest.raises(ValueError, match="cycle"):
        compile_workflow_spec(spec)


def test_compile_workflow_spec_inherits_primitive_evaluation_contract_defaults() -> None:
    spec = WorkflowSpec(
        workflow_id="news_aggregation",
        steps=[
            WorkflowStep(
                step_id="fetch",
                primitive_id="web_scrape",
                command=["python", "scripts/fetch.py"],
            )
        ],
    )

    payload = compile_workflow_spec(
        spec,
        primitive_packs={
            "web_scrape": PrimitivePack(
                primitive_id="web_scrape",
                kind="browser_interaction",
                evaluation_contract=EvaluationContract(
                    artifact_requirements=["page.html", "extracted.json"],
                    required_fields=["title", "price"],
                    latency_budget_ms=1200,
                    quality_thresholds=EvaluationThresholds(
                        field_completeness=0.8,
                        grounded_field_rate=0.75,
                    ),
                ),
            )
        },
    )

    assert payload["tasks"][0]["expectations"]["artifact_requirements"] == [
        "page.html",
        "extracted.json",
    ]
    assert payload["tasks"][0]["expectations"]["required_fields"] == ["title", "price"]
    assert payload["tasks"][0]["expectations"]["latency_budget_ms"] == 1200
    assert payload["tasks"][0]["expectations"]["quality_thresholds"] == {
        "field_completeness": 0.8,
        "grounded_field_rate": 0.75,
    }


def test_compile_workflow_spec_step_evaluation_overrides_primitive_defaults() -> None:
    spec = WorkflowSpec(
        workflow_id="news_aggregation",
        steps=[
            WorkflowStep(
                step_id="fetch",
                primitive_id="web_scrape",
                command=["python", "scripts/fetch.py"],
                evaluation=EvaluationContract(
                    required_fields=["title", "contact_email"],
                    latency_budget_ms=900,
                ),
            )
        ],
    )

    payload = compile_workflow_spec(
        spec,
        primitive_packs={
            "web_scrape": PrimitivePack(
                primitive_id="web_scrape",
                kind="browser_interaction",
                evaluation_contract=EvaluationContract(
                    artifact_requirements=["page.html", "extracted.json"],
                    required_fields=["title", "price"],
                    latency_budget_ms=1200,
                    quality_thresholds=EvaluationThresholds(
                        field_completeness=0.8,
                        grounded_field_rate=0.75,
                    ),
                ),
            )
        },
    )

    assert payload["tasks"][0]["expectations"]["artifact_requirements"] == [
        "page.html",
        "extracted.json",
    ]
    assert payload["tasks"][0]["expectations"]["required_fields"] == [
        "title",
        "contact_email",
    ]
    assert payload["tasks"][0]["expectations"]["latency_budget_ms"] == 900


def test_compile_workflow_spec_embeds_method_and_binding_metadata() -> None:
    spec = WorkflowSpec(
        workflow_id="binding_enabled_workflow",
        steps=[
            WorkflowStep(
                step_id="fetch",
                primitive_id="web_scrape",
                method_id="web_scrape/fast_path",
                binding_id="openclaw/codex/web_scrape",
                command=["python", "scripts/fetch.py"],
            )
        ],
    )

    payload = compile_workflow_spec(
        spec,
        binding_specs={
            "openclaw/codex/web_scrape": ClawBindingSpec(
                binding_id="openclaw/codex/web_scrape",
                claw_family="openclaw",
                primitive_id="web_scrape",
                adapter_kind="command",
                execution={
                    "command": ["python", "-c", "print('binding-run')"],
                },
            )
        },
    )

    assert payload["tasks"][0]["expectations"]["method_id"] == "web_scrape/fast_path"
    assert payload["tasks"][0]["expectations"]["binding_id"] == "openclaw/codex/web_scrape"
    assert payload["tasks"][0]["binding"] == {
        "binding_id": "openclaw/codex/web_scrape",
        "adapter_kind": "command",
        "command": ["python", "-c", "print('binding-run')"],
    }


def test_compile_workflow_spec_supports_harness_refs() -> None:
    spec = WorkflowSpec(
        workflow_id="harness_enabled_workflow",
        steps=[
            WorkflowStep(
                step_id="run_candidate_harness",
                command=["python", "scripts/run.py"],
                harness_ref=WorkflowHarnessRef(
                    harness_id="harness/demo",
                    wrapper_path="scripts/generated/demo_harness_wrapper.py",
                    source_artifacts=["runs/run-1/artifacts"],
                ),
                candidate_harness_ref=WorkflowHarnessRef(
                    harness_id="harness/demo",
                    candidate_harness_id="cand-harness-1",
                    proposal_id="proposal-1",
                    iteration_id="iter-1",
                    wrapper_path="scripts/generated/demo_harness_wrapper.py",
                    source_artifacts=["runs/run-1/artifacts"],
                    provenance={"source": "agent"},
                ),
            )
        ],
    )

    payload = compile_workflow_spec(spec)

    task = payload["tasks"][0]
    assert task["scenario"] == "cand-harness-1"
    assert task["harness_ref"]["harness_id"] == "harness/demo"
    assert task["candidate_harness_ref"]["candidate_harness_id"] == "cand-harness-1"
    assert task["execution_unit"]["kind"] == "harness"
    assert task["execution_unit"]["candidate_harness_id"] == "cand-harness-1"
    assert task["expectations"]["execution_kind"] == "harness"
    assert task["expectations"]["candidate_harness_id"] == "cand-harness-1"


def test_write_compiled_workflow_task_set_persists_json(tmp_path: Path) -> None:
    output_path = tmp_path / "compiled" / "news_aggregation.task_set.json"
    spec = WorkflowSpec(
        workflow_id="news_aggregation",
        steps=[
            WorkflowStep(
                step_id="fetch",
                primitive_id="web_scrape",
                command=["python", "scripts/fetch.py"],
            )
        ],
    )

    payload = write_compiled_workflow_task_set(spec, output_path)

    assert output_path.exists()
    assert json.loads(output_path.read_text(encoding="utf-8")) == payload
