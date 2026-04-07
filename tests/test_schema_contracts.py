from __future__ import annotations

from meta_harness.schemas import (
    EvaluatorPack,
    EvaluatorRun,
    GateCondition,
    GatePolicy,
    JobRecord,
    JobResultRef,
    OptimizationPolicy,
    PrimitiveMetric,
    PrimitivePack,
    ProbeSchema,
    ProposalTemplate,
    ScoreReport,
    WorkflowSpec,
    WorkflowStep,
)


def test_evaluator_run_schema_defaults() -> None:
    payload = EvaluatorRun(
        evaluator_name="basic",
        run_id="run123",
        status="completed",
        report={"composite": 1.0},
    ).model_dump()

    assert payload["evaluator_name"] == "basic"
    assert payload["run_id"] == "run123"
    assert payload["status"] == "completed"
    assert payload["report"] == {"composite": 1.0}
    assert payload["started_at"] is not None


def test_gate_policy_schema_accepts_conditions() -> None:
    policy = GatePolicy(
        policy_id="default-regression",
        policy_type="regression",
        scope={"profile": "*", "project": "*"},
        conditions=[
            GateCondition(
                kind="test_suite_passed",
                path="pytest.regression",
                value=True,
            )
        ],
    ).model_dump()

    assert policy["policy_id"] == "default-regression"
    assert policy["policy_type"] == "regression"
    assert policy["enabled"] is True
    assert policy["conditions"][0]["kind"] == "test_suite_passed"


def test_job_record_schema_supports_result_ref() -> None:
    payload = JobRecord(
        job_id="job-123",
        job_type="benchmark.run",
        result_ref=JobResultRef(
            target_type="benchmark_experiment",
            target_id="exp-1",
            path="reports/jobs/job-123.json",
        ),
    ).model_dump()

    assert payload["job_id"] == "job-123"
    assert payload["job_type"] == "benchmark.run"
    assert payload["status"] == "queued"
    assert payload["result_ref"]["target_type"] == "benchmark_experiment"


def test_primitive_pack_schema_supports_capability_definition() -> None:
    payload = PrimitivePack(
        primitive_id="web_scrape",
        kind="browser_interaction",
        description="Fetch and extract structured page data",
        metric_schema=[
            PrimitiveMetric(
                name="success_rate",
                kind="float",
                higher_is_better=True,
                required=True,
            )
        ],
        probe_schema=ProbeSchema(
            fingerprints=["scrape.mode"],
            probes=["scrape.navigation_depth"],
        ),
        default_knobs={"timeout_ms": 8000},
        default_scenarios=[{"id": "dynamic_page", "weight": 1.2}],
        proposal_templates=[
            ProposalTemplate(
                template_id="web_scrape/fast_path",
                title="Fast path",
                hypothesis="Reduce wait time on stable pages",
                knobs={"wait_strategy": "domcontentloaded"},
                expected_signals={"fingerprints": {"scrape.mode": "fast"}},
                tags=["latency"],
            )
        ],
    ).model_dump()

    assert payload["primitive_id"] == "web_scrape"
    assert payload["metric_schema"][0]["name"] == "success_rate"
    assert payload["probe_schema"]["fingerprints"] == ["scrape.mode"]
    assert payload["default_knobs"]["timeout_ms"] == 8000
    assert payload["proposal_templates"][0]["template_id"] == "web_scrape/fast_path"


def test_evaluator_pack_schema_supports_capability_binding() -> None:
    payload = EvaluatorPack(
        pack_id="web_scrape/core",
        supported_primitives=["web_scrape"],
        command=["python", "scripts/eval_web_scrape.py"],
        artifact_requirements=["page.html", "extracted.json"],
        emits_metrics=["success_rate", "latency_ms"],
        emits_probes=["scrape.navigation_depth"],
    ).model_dump()

    assert payload["pack_id"] == "web_scrape/core"
    assert payload["supported_primitives"] == ["web_scrape"]
    assert payload["command"] == ["python", "scripts/eval_web_scrape.py"]


def test_workflow_spec_schema_supports_step_composition() -> None:
    payload = WorkflowSpec(
        workflow_id="news_aggregation",
        evaluator_packs=["web_scrape/core", "workflow_recovery/core"],
        steps=[
            WorkflowStep(
                step_id="fetch_homepages",
                primitive_id="web_scrape",
                role="hot_path",
                command=["python", "scripts/fetch.py"],
                weight=1.3,
            ),
            WorkflowStep(
                step_id="merge_results",
                primitive_id="message_aggregate",
                role="post_process",
                depends_on=["fetch_homepages"],
                optional=True,
            ),
        ],
        optimization_policy=OptimizationPolicy(
            allowed_primitives=["web_scrape"],
            focus_roles=["hot_path", "fallback_path"],
            objective_weights={"latency_ms": 0.7, "success_rate": 1.0},
        ),
    ).model_dump()

    assert payload["workflow_id"] == "news_aggregation"
    assert payload["steps"][0]["primitive_id"] == "web_scrape"
    assert payload["steps"][1]["depends_on"] == ["fetch_homepages"]
    assert payload["optimization_policy"]["allowed_primitives"] == ["web_scrape"]


def test_score_report_schema_supports_capability_and_workflow_scores() -> None:
    payload = ScoreReport(
        correctness={"task_count": 2},
        cost={"trace_event_count": 5},
        maintainability={},
        architecture={},
        retrieval={},
        human_collaboration={"manual_interventions": 0},
        capability_scores={
            "web_scrape": {"success_rate": 0.92, "latency_ms": 1200}
        },
        workflow_scores={"hot_path_success_rate": 0.88},
        probes={"scrape.navigation_depth": 2},
        composite=1.5,
    ).model_dump()

    assert payload["capability_scores"]["web_scrape"]["success_rate"] == 0.92
    assert payload["workflow_scores"]["hot_path_success_rate"] == 0.88
    assert payload["probes"]["scrape.navigation_depth"] == 2
