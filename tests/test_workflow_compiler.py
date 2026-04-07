from __future__ import annotations

import json
from pathlib import Path

import pytest

from meta_harness.schemas import OptimizationPolicy, WorkflowSpec, WorkflowStep
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
    assert payload["tasks"][0]["task_id"] == "fetch_homepages"
    assert payload["tasks"][0]["scenario"] == "web_scrape"
    assert payload["tasks"][0]["phases"] == [
        {
            "phase": "fetch_homepages",
            "command": ["python", "scripts/fetch.py"],
        }
    ]
    assert payload["tasks"][0]["expectations"]["role"] == "hot_path"
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
