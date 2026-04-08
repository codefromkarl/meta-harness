from __future__ import annotations

import json
from pathlib import Path

from meta_harness.datasets import write_dataset_artifact
from meta_harness.loop.iteration_store import (
    append_iteration_history,
    loop_root_path,
    write_iteration_artifact,
    write_loop_summary,
)
from meta_harness.schemas import (
    EvaluationContract,
    EvaluationThresholds,
    EvaluatorPack,
    EvaluatorRun,
    GateCondition,
    GatePolicy,
    JobRecord,
    JobResultRef,
    OptimizationPolicy,
    PageProfile,
    PrimitiveMetric,
    PrimitivePack,
    ProbeSchema,
    ProposalTemplate,
    ScoreReport,
    WorkflowSpec,
    WorkflowStep,
    WorkloadProfile,
)
from meta_harness.proposals import create_proposal_record
from meta_harness.integration_schemas import (
    CandidateHarnessPatch,
    ExecutionModel,
    HarnessRun,
    HarnessSpec,
    HarnessTaskRef,
    IterationResult,
)
from meta_harness.schemas import WorkflowHarnessRef
from meta_harness.loop.schemas import (
    ExperienceQuery,
    LoopIterationArtifact,
    LoopExperienceSummary,
    LoopSummary,
    SearchLoopRequest,
    SelectionResult,
    StopDecision,
)
from meta_harness.artifact_contracts import (
    validate_artifact_contract,
    validate_artifact_contracts,
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
    assert payload["profiling"] == {}
    assert payload["trace_artifact"] is None
    assert payload["started_at"] is not None


def test_loop_summary_schema_supports_loop_artifact_contract(tmp_path: Path) -> None:
    payload = LoopSummary(
        loop_id="loop-1",
        profile_name="base",
        project_name="demo",
        request=SearchLoopRequest(
            config_root=tmp_path / "configs",
            runs_root=tmp_path / "runs",
            candidates_root=tmp_path / "candidates",
            profile_name="base",
            project_name="demo",
            task_set_path=tmp_path / "task_set.json",
            experience_query=ExperienceQuery(
                focus="retrieval",
                best_k=3,
            ),
        ),
        best_candidate_id="cand-1",
        best_run_id="run-1",
        best_score=1.2,
        iteration_count=2,
        stop_reason="instability threshold reached",
        loop_dir=str(tmp_path / "reports" / "loops" / "loop-1"),
    ).model_dump()

    assert payload["loop_id"] == "loop-1"
    assert payload["request"]["profile_name"] == "base"
    assert payload["loop_dir"].endswith("reports/loops/loop-1")
    assert payload["request"]["experience_query"]["focus"] == "retrieval"


def test_loop_experience_summary_schema_supports_next_round_artifact() -> None:
    payload = LoopExperienceSummary(
        iteration_id="loop-1-0001",
        focus="retrieval",
        selected_candidate_id="cand-1",
        selected_run_id="run-1",
        score_delta=0.4,
        best_score=1.2,
        representative_failures=[{"run_id": "run-old", "family": "retrieval timeout"}],
        representative_successes=[{"run_id": "run-best", "score": {"composite": 1.2}}],
        capability_gaps=[{"focus": "retrieval", "metric": "grounded_field_rate", "gap": 0.5}],
        representative_artifacts={"trace_refs": ["runs/run-old/tasks/task-a/steps.jsonl"]},
        next_actions=["prefer retrieval-focused history"],
    ).model_dump()

    assert payload["iteration_id"] == "loop-1-0001"
    assert payload["focus"] == "retrieval"
    assert payload["selected_candidate_id"] == "cand-1"
    assert payload["capability_gaps"][0]["metric"] == "grounded_field_rate"


def test_proposal_record_schema_supports_evaluation_artifact() -> None:
    from meta_harness.schemas import ProposalRecord

    payload = ProposalRecord(
        proposal_id="proposal-1",
        profile="base",
        project="demo",
        proposer_kind="heuristic",
        strategy="increase_budget_on_repeated_failures",
        evaluation_artifact="proposal_evaluation.json",
    ).model_dump(mode="json")

    assert payload["proposal_id"] == "proposal-1"
    assert payload["evaluation_artifact"] == "proposal_evaluation.json"


def test_candidate_harness_patch_schema_supports_outer_loop_metadata() -> None:
    payload = CandidateHarnessPatch(
        candidate_id="cand-1",
        harness_spec_id="harness-demo",
        iteration_id="iter-1",
        title="Proxy stdout normalization",
        summary="Capture compact stdout and preserve stderr preview",
        change_kind="wrapper_patch",
        target_files=["scripts/generated/demo_harness_wrapper.py"],
        patch={"runtime": {"binding": {"command": ["python", "wrapper.py"]}}},
        rationale=["Need stable stdout envelope for harness benchmark"],
        provenance={"source": "agent"},
    ).model_dump()

    assert payload["candidate_id"] == "cand-1"
    assert payload["harness_spec_id"] == "harness-demo"
    assert payload["change_kind"] == "wrapper_patch"
    assert payload["target_files"] == ["scripts/generated/demo_harness_wrapper.py"]
    assert payload["status"] == "proposed"


def test_harness_task_ref_schema_supports_runtime_task_binding() -> None:
    payload = HarnessTaskRef(
        task_id="task-a",
        phase="exec",
        command=["git", "status", "--short"],
        workdir="${workspace_dir}",
        expectations={"role": "proxy"},
    ).model_dump()

    assert payload["task_id"] == "task-a"
    assert payload["phase"] == "exec"
    assert payload["command"] == ["git", "status", "--short"]
    assert payload["workdir"] == "${workspace_dir}"


def test_harness_run_schema_tracks_candidate_execution_context() -> None:
    payload = HarnessRun(
        run_id="run-1",
        candidate_id="cand-1",
        harness_spec_id="harness-demo",
        iteration_id="iter-1",
        wrapper_path="scripts/generated/demo_harness_wrapper.py",
        task_refs=[
            HarnessTaskRef(
                task_id="task-a",
                phase="exec",
                command=["git", "status"],
            )
        ],
        score={"composite": 1.0},
        trace_refs=["runs/run-1/tasks/task-a/steps.jsonl"],
    ).model_dump()

    assert payload["run_id"] == "run-1"
    assert payload["candidate_id"] == "cand-1"
    assert payload["task_refs"][0]["task_id"] == "task-a"
    assert payload["status"] == "completed"


def test_iteration_result_schema_summarizes_candidate_outcomes() -> None:
    payload = IterationResult(
        iteration_id="iter-1",
        harness_spec_id="harness-demo",
        selected_candidate_id="cand-2",
        candidate_ids=["cand-1", "cand-2"],
        run_ids=["run-1", "run-2"],
        score_summary={"best_composite": 1.2},
        failure_modes=["stderr instability"],
        next_actions=["propose another wrapper refinement"],
    ).model_dump()

    assert payload["iteration_id"] == "iter-1"
    assert payload["selected_candidate_id"] == "cand-2"
    assert payload["candidate_ids"] == ["cand-1", "cand-2"]
    assert payload["status"] == "completed"


def test_harness_spec_schema_coexists_with_outer_loop_models() -> None:
    payload = HarnessSpec(
        spec_id="harness-demo",
        target_project_path="/tmp/demo",
        execution_model=ExecutionModel(kind="json_stdout_cli"),
        capability_modules=["command_proxy", "output_filter"],
        manual_checks=["入口命令是否正确"],
    ).model_dump()

    assert payload["spec_id"] == "harness-demo"
    assert payload["execution_model"]["kind"] == "json_stdout_cli"
    assert payload["manual_checks"] == ["入口命令是否正确"]


def test_workflow_step_schema_supports_harness_refs_without_primitive_binding() -> None:
    payload = WorkflowStep(
        step_id="run_harness",
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
    ).model_dump()

    assert payload["primitive_id"] is None
    assert payload["harness_ref"]["harness_id"] == "harness/demo"
    assert payload["candidate_harness_ref"]["candidate_harness_id"] == "cand-harness-1"


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
        evaluation_contract=EvaluationContract(
            artifact_requirements=["page.html", "extracted.json"],
            quality_thresholds=EvaluationThresholds(
                field_completeness=0.8,
                grounded_field_rate=0.75,
            ),
        ),
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
    assert payload["evaluation_contract"]["artifact_requirements"] == [
        "page.html",
        "extracted.json",
    ]
    assert payload["default_knobs"]["timeout_ms"] == 8000
    assert payload["proposal_templates"][0]["template_id"] == "web_scrape/fast_path"


def test_page_and_workload_profile_schema_support_web_scrape_context() -> None:
    payload = WorkflowSpec(
        workflow_id="web_scrape_benchmark",
        page_profile=PageProfile(
            complexity="high",
            dynamicity="heavily_dynamic",
            anti_bot_level="high",
            requires_rendering=True,
            requires_interaction=True,
            schema_stability="volatile",
            media_dependency="medium",
        ),
        workload_profile=WorkloadProfile(
            usage_mode="recurring",
            batch_size=64,
            latency_sla_ms=2500,
            budget_mode="high_success",
            freshness_requirement="high",
            allowed_failure_rate=0.05,
        ),
    ).model_dump()

    assert payload["page_profile"] == {
        "complexity": "high",
        "dynamicity": "heavily_dynamic",
        "anti_bot_level": "high",
        "requires_rendering": True,
        "requires_interaction": True,
        "schema_stability": "volatile",
        "media_dependency": "medium",
    }
    assert payload["workload_profile"] == {
        "usage_mode": "recurring",
        "batch_size": 64,
        "latency_sla_ms": 2500,
        "budget_mode": "high_success",
        "freshness_requirement": "high",
        "allowed_failure_rate": 0.05,
    }


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


def test_data_analysis_primitive_and_pack_assets_exist() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    primitive = json.loads(
        (repo_root / "configs" / "primitives" / "data_analysis.json").read_text(
            encoding="utf-8"
        )
    )
    pack = json.loads(
        (repo_root / "configs" / "evaluator_packs" / "data_analysis_core.json").read_text(
            encoding="utf-8"
        )
    )

    assert primitive["primitive_id"] == "data_analysis"
    assert primitive["evaluation_contract"]["artifact_requirements"] == [
        "analysis_summary.json",
        "analysis_report.md",
    ]
    assert primitive["probe_schema"]["fingerprints"] == ["analysis.mode"]
    assert pack["pack_id"] == "data_analysis/core"
    assert pack["supported_primitives"] == ["data_analysis"]
    assert pack["command"] == ["python", "scripts/eval_data_analysis.py"]


def test_primitive_bridge_output_contract_assets_exist() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    web_scrape = json.loads(
        (repo_root / "configs" / "primitives" / "web_scrape.json").read_text(
            encoding="utf-8"
        )
    )
    data_analysis = json.loads(
        (repo_root / "configs" / "primitives" / "data_analysis.json").read_text(
            encoding="utf-8"
        )
    )

    assert web_scrape["output_contract"]["bridge"]["prompt_mode"] == "json_schema"
    assert web_scrape["output_contract"]["bridge"]["artifact_writes"] == [
        {"path": "page.html", "payload_path": "page_html", "format": "text"},
        {"path": "extracted.json", "payload_path": "extracted", "format": "json"},
    ]
    assert data_analysis["output_contract"]["bridge"]["prompt_mode"] == "json_schema"
    assert data_analysis["output_contract"]["bridge"]["artifact_writes"] == [
        {
            "path": "analysis_summary.json",
            "payload_path": "analysis_summary",
            "format": "json",
        },
        {
            "path": "analysis_report.md",
            "payload_path": "analysis_report",
            "format": "text",
        },
    ]


def test_workflow_spec_schema_supports_step_composition() -> None:
    payload = WorkflowSpec(
        workflow_id="news_aggregation",
        evaluator_packs=["web_scrape/core", "workflow_recovery/core"],
        page_profile=PageProfile(
            complexity="medium",
            dynamicity="lightly_dynamic",
            anti_bot_level="medium",
            requires_rendering=True,
        ),
        workload_profile=WorkloadProfile(
            usage_mode="ad_hoc",
            latency_sla_ms=1500,
            budget_mode="balanced",
        ),
        steps=[
            WorkflowStep(
                step_id="fetch_homepages",
                primitive_id="web_scrape",
                role="hot_path",
                command=["python", "scripts/fetch.py"],
                page_profile=PageProfile(
                    complexity="high",
                    requires_interaction=True,
                ),
                workload_profile=WorkloadProfile(
                    usage_mode="recurring",
                    batch_size=10,
                    freshness_requirement="high",
                ),
                evaluation=EvaluationContract(
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
    assert payload["page_profile"]["complexity"] == "medium"
    assert payload["workload_profile"]["usage_mode"] == "ad_hoc"
    assert payload["steps"][0]["primitive_id"] == "web_scrape"
    assert payload["steps"][0]["page_profile"]["complexity"] == "high"
    assert payload["steps"][0]["page_profile"]["requires_interaction"] is True
    assert payload["steps"][0]["workload_profile"]["usage_mode"] == "recurring"
    assert payload["steps"][0]["workload_profile"]["batch_size"] == 10
    assert payload["steps"][0]["evaluation"]["required_fields"] == [
        "title",
        "price",
        "contact_email",
    ]
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


def test_artifact_contract_validator_accepts_real_loop_proposal_dataset_and_evaluator_artifacts(
    tmp_path: Path,
) -> None:
    proposals_root = tmp_path / "proposals"
    proposal_id = create_proposal_record(
        proposals_root=proposals_root,
        profile_name="demo_public",
        project_name="demo_public",
        proposer_kind="heuristic",
        proposal={"strategy": "increase_budget_on_repeated_failures"},
        proposal_evaluation={"selected": True},
    )
    proposal_dir = proposals_root / proposal_id

    dataset_path = tmp_path / "datasets" / "demo-public-cases" / "v1" / "dataset.json"
    write_dataset_artifact(
        dataset_path,
        {
            "dataset_id": "demo-public-cases",
            "version": "v1",
            "schema_version": "2026-04-06",
            "case_count": 0,
            "cases": [],
            "source_summary": {"operation": "task_set_build"},
            "created_at": "2026-04-08T00:00:00Z",
            "frozen": True,
        },
    )

    loop_dir = loop_root_path(tmp_path / "reports", "loop-1")
    request = SearchLoopRequest(
        config_root=tmp_path / "configs",
        runs_root=tmp_path / "runs",
        candidates_root=tmp_path / "candidates",
        profile_name="demo_public",
        project_name="demo_public",
        task_set_path=tmp_path / "task_set.json",
    )
    iteration = LoopIterationArtifact(
        iteration_id="loop-1-0001",
        iteration_index=1,
        objective={"focus": "budget"},
        experience={"matching_runs": [{"run_id": "run-1"}]},
        proposal={"strategy": "increase_budget_on_repeated_failures"},
        proposal_id=proposal_id,
        proposal_path=str(proposal_dir),
        candidate_id="cand-1",
        candidate_path=str(tmp_path / "candidates" / "cand-1"),
        run_id="run-1",
        run_path=str(tmp_path / "runs" / "run-1"),
        selection=SelectionResult(candidate_id="cand-1", run_id="run-1", score=0.8),
        stop_decision=StopDecision(
            should_stop=True,
            reason="target score reached",
            iteration_index=1,
            max_iterations=1,
        ),
        evaluation={"variants": [{"name": "budget_plus_two", "score": {"composite": 0.8}}]},
        summary={"score": 0.8, "next_actions": ["promote candidate"]},
        artifacts={
            "proposer_context": str(
                loop_dir / "iterations" / "loop-1-0001" / "proposer_context"
            )
        },
        proposal_evaluation={"selected": True, "proposal_rank": 1},
    )
    write_iteration_artifact(loop_dir, iteration)
    proposer_context_dir = loop_dir / "iterations" / "loop-1-0001" / "proposer_context"
    proposer_context_dir.mkdir(parents=True, exist_ok=True)
    (proposer_context_dir / "manifest.json").write_text("{}", encoding="utf-8")
    append_iteration_history(loop_dir, iteration)
    write_loop_summary(
        loop_dir,
        LoopSummary(
            loop_id="loop-1",
            profile_name="demo_public",
            project_name="demo_public",
            request=request,
            best_candidate_id="cand-1",
            best_run_id="run-1",
            best_score=0.8,
            iteration_count=1,
            stop_reason="target score reached",
            iterations=[iteration],
            loop_dir=str(loop_dir),
        ),
    )

    evaluator_path = tmp_path / "runs" / "run-1" / "evaluators" / "basic.json"
    evaluator_path.parent.mkdir(parents=True, exist_ok=True)
    evaluator_path.write_text(
        EvaluatorRun(
            evaluator_name="basic",
            run_id="run-1",
            status="completed",
            report={"composite": 0.8},
            artifact_refs=["runs/run-1/score_report.json"],
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )

    summary = validate_artifact_contracts(
        [
            {"artifact_kind": "proposal", "path": proposal_dir},
            {"artifact_kind": "dataset", "path": dataset_path.parent},
            {"artifact_kind": "loop", "path": loop_dir},
            {"artifact_kind": "evaluator", "path": evaluator_path},
        ]
    )

    assert summary["ok"] is True
    assert [item["artifact_kind"] for item in summary["items"]] == [
        "proposal",
        "dataset",
        "loop",
        "evaluator",
    ]
    assert all(not item["missing"] for item in summary["items"])


def test_artifact_contract_validator_reports_missing_required_files(tmp_path: Path) -> None:
    proposal_dir = tmp_path / "proposals" / "proposal-1"
    proposal_dir.mkdir(parents=True, exist_ok=True)
    (proposal_dir / "proposal.json").write_text("{}", encoding="utf-8")

    result = validate_artifact_contract(
        artifact_kind="proposal",
        path=proposal_dir,
    )

    assert result["ok"] is False
    assert result["artifact_kind"] == "proposal"
    assert result["missing"] == ["proposal_evaluation.json"]


def test_loop_contract_validator_requires_validation_payload_when_benchmark_is_skipped(
    tmp_path: Path,
) -> None:
    loop_dir = loop_root_path(tmp_path / "reports", "loop-validation")
    iteration_dir = loop_dir / "iterations" / "loop-validation-0001"
    iteration_dir.mkdir(parents=True, exist_ok=True)

    (loop_dir / "loop.json").write_text(
        json.dumps(
            {
                "loop_id": "loop-validation",
                "profile_name": "demo",
                "project_name": "demo",
                "request": {},
                "iteration_count": 1,
                "stop_reason": "validation failed",
                "iterations": [{"iteration_id": "loop-validation-0001"}],
            }
        ),
        encoding="utf-8",
    )
    (loop_dir / "iteration_history.jsonl").write_text(
        json.dumps({"iteration_id": "loop-validation-0001"}) + "\n",
        encoding="utf-8",
    )
    for name, payload in {
        "iteration.json": {"iteration_id": "loop-validation-0001"},
        "proposal_input.json": {"objective": {}, "experience": {}},
        "proposal_output.json": {"proposal": {}},
        "selected_candidate.json": {"candidate_id": "cand-1"},
        "benchmark_summary.json": {
            "evaluation": {
                "executor": {"kind": "benchmark", "status": "validation_failed"},
                "benchmark_skipped": True,
            }
        },
        "experience_summary.json": {"iteration_id": "loop-validation-0001"},
        "next_round_context.json": {"experience_summary_path": "experience_summary.json"},
    }.items():
        (iteration_dir / name).write_text(json.dumps(payload), encoding="utf-8")
    proposer_context_dir = iteration_dir / "proposer_context"
    proposer_context_dir.mkdir(parents=True, exist_ok=True)
    (proposer_context_dir / "manifest.json").write_text("{}", encoding="utf-8")

    result = validate_artifact_contract(
        artifact_kind="loop",
        path=loop_dir,
    )

    assert result["ok"] is False
    assert any(
        "benchmark_summary.json missing validation payload" in error
        for error in result["errors"]
    )


def test_loop_contract_validator_requires_validation_summary_artifact(
    tmp_path: Path,
) -> None:
    loop_dir = loop_root_path(tmp_path / "reports", "loop-validation-summary")
    iteration_dir = loop_dir / "iterations" / "loop-validation-summary-0001"
    iteration_dir.mkdir(parents=True, exist_ok=True)

    (loop_dir / "loop.json").write_text(
        json.dumps(
            {
                "loop_id": "loop-validation-summary",
                "profile_name": "demo",
                "project_name": "demo",
                "request": {},
                "iteration_count": 1,
                "stop_reason": "done",
                "iterations": [{"iteration_id": "loop-validation-summary-0001"}],
            }
        ),
        encoding="utf-8",
    )
    (loop_dir / "iteration_history.jsonl").write_text(
        json.dumps({"iteration_id": "loop-validation-summary-0001"}) + "\n",
        encoding="utf-8",
    )
    for name, payload in {
        "iteration.json": {"iteration_id": "loop-validation-summary-0001"},
        "proposal_input.json": {"objective": {}, "experience": {}},
        "proposal_output.json": {"proposal": {}},
        "selected_candidate.json": {"candidate_id": "cand-1"},
        "benchmark_summary.json": {"evaluation": {"validation": {"status": "passed"}}},
        "experience_summary.json": {"iteration_id": "loop-validation-summary-0001"},
        "next_round_context.json": {"experience_summary_path": "experience_summary.json"},
    }.items():
        (iteration_dir / name).write_text(json.dumps(payload), encoding="utf-8")
    proposer_context_dir = iteration_dir / "proposer_context"
    proposer_context_dir.mkdir(parents=True, exist_ok=True)
    (proposer_context_dir / "manifest.json").write_text("{}", encoding="utf-8")

    result = validate_artifact_contract(
        artifact_kind="loop",
        path=loop_dir,
    )

    assert result["ok"] is False
    assert "iterations/loop-validation-summary-0001/validation_summary.json" in result["missing"]


def test_loop_contract_validator_requires_validation_summary_path_in_next_round_context(
    tmp_path: Path,
) -> None:
    loop_dir = loop_root_path(tmp_path / "reports", "loop-next-round-validation")
    iteration_dir = loop_dir / "iterations" / "loop-next-round-validation-0001"
    iteration_dir.mkdir(parents=True, exist_ok=True)

    (loop_dir / "loop.json").write_text(
        json.dumps(
            {
                "loop_id": "loop-next-round-validation",
                "profile_name": "demo",
                "project_name": "demo",
                "request": {},
                "iteration_count": 1,
                "stop_reason": "done",
                "iterations": [{"iteration_id": "loop-next-round-validation-0001"}],
            }
        ),
        encoding="utf-8",
    )
    (loop_dir / "iteration_history.jsonl").write_text(
        json.dumps({"iteration_id": "loop-next-round-validation-0001"}) + "\n",
        encoding="utf-8",
    )
    for name, payload in {
        "iteration.json": {"iteration_id": "loop-next-round-validation-0001"},
        "proposal_input.json": {"objective": {}, "experience": {}},
        "proposal_output.json": {"proposal": {}},
        "selected_candidate.json": {"candidate_id": "cand-1"},
        "benchmark_summary.json": {"evaluation": {"validation": {"status": "passed"}}},
        "validation_summary.json": {"status": "passed"},
        "experience_summary.json": {"iteration_id": "loop-next-round-validation-0001"},
        "next_round_context.json": {"experience_summary_path": "experience_summary.json"},
    }.items():
        (iteration_dir / name).write_text(json.dumps(payload), encoding="utf-8")
    proposer_context_dir = iteration_dir / "proposer_context"
    proposer_context_dir.mkdir(parents=True, exist_ok=True)
    (proposer_context_dir / "manifest.json").write_text("{}", encoding="utf-8")

    result = validate_artifact_contract(
        artifact_kind="loop",
        path=loop_dir,
    )

    assert result["ok"] is False
    assert any(
        "next_round_context.json missing validation_summary_path" in error
        for error in result["errors"]
    )


def test_loop_contract_validator_requires_validation_summary_to_match_benchmark_evaluation(
    tmp_path: Path,
) -> None:
    loop_dir = loop_root_path(tmp_path / "reports", "loop-validation-match")
    iteration_dir = loop_dir / "iterations" / "loop-validation-match-0001"
    iteration_dir.mkdir(parents=True, exist_ok=True)

    (loop_dir / "loop.json").write_text(
        json.dumps(
            {
                "loop_id": "loop-validation-match",
                "profile_name": "demo",
                "project_name": "demo",
                "request": {},
                "iteration_count": 1,
                "stop_reason": "done",
                "iterations": [{"iteration_id": "loop-validation-match-0001"}],
            }
        ),
        encoding="utf-8",
    )
    (loop_dir / "iteration_history.jsonl").write_text(
        json.dumps({"iteration_id": "loop-validation-match-0001"}) + "\n",
        encoding="utf-8",
    )
    for name, payload in {
        "iteration.json": {"iteration_id": "loop-validation-match-0001"},
        "proposal_input.json": {"objective": {}, "experience": {}},
        "proposal_output.json": {"proposal": {}},
        "selected_candidate.json": {"candidate_id": "cand-1"},
        "benchmark_summary.json": {
            "evaluation": {"validation": {"status": "passed", "reason": ""}}
        },
        "validation_summary.json": {"status": "failed", "reason": "mismatch"},
        "experience_summary.json": {"iteration_id": "loop-validation-match-0001"},
        "next_round_context.json": {
            "experience_summary_path": "experience_summary.json",
            "validation_summary_path": "validation_summary.json",
        },
    }.items():
        (iteration_dir / name).write_text(json.dumps(payload), encoding="utf-8")
    proposer_context_dir = iteration_dir / "proposer_context"
    proposer_context_dir.mkdir(parents=True, exist_ok=True)
    (proposer_context_dir / "manifest.json").write_text("{}", encoding="utf-8")

    result = validate_artifact_contract(
        artifact_kind="loop",
        path=loop_dir,
    )

    assert result["ok"] is False
    assert any(
        "validation_summary.json does not match benchmark_summary.json evaluation.validation"
        in error
        for error in result["errors"]
    )


def test_loop_contract_validator_requires_validation_summary_path_to_match_artifact(
    tmp_path: Path,
) -> None:
    loop_dir = loop_root_path(tmp_path / "reports", "loop-validation-path-match")
    iteration_dir = loop_dir / "iterations" / "loop-validation-path-match-0001"
    iteration_dir.mkdir(parents=True, exist_ok=True)

    (loop_dir / "loop.json").write_text(
        json.dumps(
            {
                "loop_id": "loop-validation-path-match",
                "profile_name": "demo",
                "project_name": "demo",
                "request": {},
                "iteration_count": 1,
                "stop_reason": "done",
                "iterations": [{"iteration_id": "loop-validation-path-match-0001"}],
            }
        ),
        encoding="utf-8",
    )
    (loop_dir / "iteration_history.jsonl").write_text(
        json.dumps({"iteration_id": "loop-validation-path-match-0001"}) + "\n",
        encoding="utf-8",
    )
    for name, payload in {
        "iteration.json": {"iteration_id": "loop-validation-path-match-0001"},
        "proposal_input.json": {"objective": {}, "experience": {}},
        "proposal_output.json": {"proposal": {}},
        "selected_candidate.json": {"candidate_id": "cand-1"},
        "benchmark_summary.json": {
            "evaluation": {"validation": {"status": "passed", "reason": ""}}
        },
        "validation_summary.json": {"status": "passed", "reason": ""},
        "experience_summary.json": {"iteration_id": "loop-validation-path-match-0001"},
        "next_round_context.json": {
            "experience_summary_path": "experience_summary.json",
            "validation_summary_path": "wrong-validation-summary.json",
        },
    }.items():
        (iteration_dir / name).write_text(json.dumps(payload), encoding="utf-8")
    proposer_context_dir = iteration_dir / "proposer_context"
    proposer_context_dir.mkdir(parents=True, exist_ok=True)
    (proposer_context_dir / "manifest.json").write_text("{}", encoding="utf-8")

    result = validate_artifact_contract(
        artifact_kind="loop",
        path=loop_dir,
    )

    assert result["ok"] is False
    assert any(
        "next_round_context.json validation_summary_path does not point to validation_summary.json"
        in error
        for error in result["errors"]
    )


def test_loop_contract_validator_accepts_absolute_validation_summary_path(
    tmp_path: Path,
) -> None:
    loop_dir = loop_root_path(tmp_path / "reports", "loop-validation-abs-path")
    iteration_dir = loop_dir / "iterations" / "loop-validation-abs-path-0001"
    iteration_dir.mkdir(parents=True, exist_ok=True)
    validation_summary_path = iteration_dir / "validation_summary.json"

    (loop_dir / "loop.json").write_text(
        json.dumps(
            {
                "loop_id": "loop-validation-abs-path",
                "profile_name": "demo",
                "project_name": "demo",
                "request": {},
                "iteration_count": 1,
                "stop_reason": "done",
                "iterations": [{"iteration_id": "loop-validation-abs-path-0001"}],
            }
        ),
        encoding="utf-8",
    )
    (loop_dir / "iteration_history.jsonl").write_text(
        json.dumps({"iteration_id": "loop-validation-abs-path-0001"}) + "\n",
        encoding="utf-8",
    )
    for name, payload in {
        "iteration.json": {"iteration_id": "loop-validation-abs-path-0001"},
        "proposal_input.json": {"objective": {}, "experience": {}},
        "proposal_output.json": {"proposal": {}},
        "selected_candidate.json": {"candidate_id": "cand-1"},
        "benchmark_summary.json": {
            "evaluation": {"validation": {"status": "passed", "reason": ""}}
        },
        "validation_summary.json": {"status": "passed", "reason": ""},
        "experience_summary.json": {"iteration_id": "loop-validation-abs-path-0001"},
        "next_round_context.json": {
            "experience_summary_path": "experience_summary.json",
            "validation_summary_path": str(validation_summary_path.resolve()),
            "artifacts": {
                "proposer_context": "proposer_context",
                "experience_summary_json": "experience_summary.json",
                "validation_summary_json": "validation_summary.json",
            },
        },
    }.items():
        (iteration_dir / name).write_text(json.dumps(payload), encoding="utf-8")
    proposer_context_dir = iteration_dir / "proposer_context"
    proposer_context_dir.mkdir(parents=True, exist_ok=True)
    (proposer_context_dir / "manifest.json").write_text("{}", encoding="utf-8")

    result = validate_artifact_contract(
        artifact_kind="loop",
        path=loop_dir,
    )

    assert result["ok"] is True


def test_loop_contract_validator_accepts_relative_validation_summary_path(
    tmp_path: Path,
) -> None:
    loop_dir = loop_root_path(tmp_path / "reports", "loop-validation-rel-path")
    iteration_dir = loop_dir / "iterations" / "loop-validation-rel-path-0001"
    iteration_dir.mkdir(parents=True, exist_ok=True)

    (loop_dir / "loop.json").write_text(
        json.dumps(
            {
                "loop_id": "loop-validation-rel-path",
                "profile_name": "demo",
                "project_name": "demo",
                "request": {},
                "iteration_count": 1,
                "stop_reason": "done",
                "iterations": [{"iteration_id": "loop-validation-rel-path-0001"}],
            }
        ),
        encoding="utf-8",
    )
    (loop_dir / "iteration_history.jsonl").write_text(
        json.dumps({"iteration_id": "loop-validation-rel-path-0001"}) + "\n",
        encoding="utf-8",
    )
    for name, payload in {
        "iteration.json": {"iteration_id": "loop-validation-rel-path-0001"},
        "proposal_input.json": {"objective": {}, "experience": {}},
        "proposal_output.json": {"proposal": {}},
        "selected_candidate.json": {"candidate_id": "cand-1"},
        "benchmark_summary.json": {
            "evaluation": {"validation": {"status": "passed", "reason": ""}}
        },
        "validation_summary.json": {"status": "passed", "reason": ""},
        "experience_summary.json": {"iteration_id": "loop-validation-rel-path-0001"},
        "next_round_context.json": {
            "experience_summary_path": "experience_summary.json",
            "validation_summary_path": "validation_summary.json",
            "artifacts": {
                "proposer_context": "proposer_context",
                "experience_summary_json": "experience_summary.json",
                "validation_summary_json": "validation_summary.json",
            },
        },
    }.items():
        (iteration_dir / name).write_text(json.dumps(payload), encoding="utf-8")
    proposer_context_dir = iteration_dir / "proposer_context"
    proposer_context_dir.mkdir(parents=True, exist_ok=True)
    (proposer_context_dir / "manifest.json").write_text("{}", encoding="utf-8")

    result = validate_artifact_contract(
        artifact_kind="loop",
        path=loop_dir,
    )

    assert result["ok"] is True


def test_loop_contract_validator_requires_experience_summary_path_to_match_artifact(
    tmp_path: Path,
) -> None:
    loop_dir = loop_root_path(tmp_path / "reports", "loop-experience-path-match")
    iteration_dir = loop_dir / "iterations" / "loop-experience-path-match-0001"
    iteration_dir.mkdir(parents=True, exist_ok=True)

    (loop_dir / "loop.json").write_text(
        json.dumps(
            {
                "loop_id": "loop-experience-path-match",
                "profile_name": "demo",
                "project_name": "demo",
                "request": {},
                "iteration_count": 1,
                "stop_reason": "done",
                "iterations": [{"iteration_id": "loop-experience-path-match-0001"}],
            }
        ),
        encoding="utf-8",
    )
    (loop_dir / "iteration_history.jsonl").write_text(
        json.dumps({"iteration_id": "loop-experience-path-match-0001"}) + "\n",
        encoding="utf-8",
    )
    for name, payload in {
        "iteration.json": {"iteration_id": "loop-experience-path-match-0001"},
        "proposal_input.json": {"objective": {}, "experience": {}},
        "proposal_output.json": {"proposal": {}},
        "selected_candidate.json": {"candidate_id": "cand-1"},
        "benchmark_summary.json": {"evaluation": {"validation": {"status": "passed"}}},
        "validation_summary.json": {"status": "passed"},
        "experience_summary.json": {"iteration_id": "loop-experience-path-match-0001"},
        "next_round_context.json": {
            "experience_summary_path": "wrong-experience-summary.json",
            "validation_summary_path": "validation_summary.json",
        },
    }.items():
        (iteration_dir / name).write_text(json.dumps(payload), encoding="utf-8")
    proposer_context_dir = iteration_dir / "proposer_context"
    proposer_context_dir.mkdir(parents=True, exist_ok=True)
    (proposer_context_dir / "manifest.json").write_text("{}", encoding="utf-8")

    result = validate_artifact_contract(
        artifact_kind="loop",
        path=loop_dir,
    )

    assert result["ok"] is False
    assert any(
        "next_round_context.json experience_summary_path does not point to experience_summary.json"
        in error
        for error in result["errors"]
    )


def test_loop_contract_validator_accepts_relative_experience_summary_path(
    tmp_path: Path,
) -> None:
    loop_dir = loop_root_path(tmp_path / "reports", "loop-experience-rel-path")
    iteration_dir = loop_dir / "iterations" / "loop-experience-rel-path-0001"
    iteration_dir.mkdir(parents=True, exist_ok=True)

    (loop_dir / "loop.json").write_text(
        json.dumps(
            {
                "loop_id": "loop-experience-rel-path",
                "profile_name": "demo",
                "project_name": "demo",
                "request": {},
                "iteration_count": 1,
                "stop_reason": "done",
                "iterations": [{"iteration_id": "loop-experience-rel-path-0001"}],
            }
        ),
        encoding="utf-8",
    )
    (loop_dir / "iteration_history.jsonl").write_text(
        json.dumps({"iteration_id": "loop-experience-rel-path-0001"}) + "\n",
        encoding="utf-8",
    )
    for name, payload in {
        "iteration.json": {"iteration_id": "loop-experience-rel-path-0001"},
        "proposal_input.json": {"objective": {}, "experience": {}},
        "proposal_output.json": {"proposal": {}},
        "selected_candidate.json": {"candidate_id": "cand-1"},
        "benchmark_summary.json": {"evaluation": {"validation": {"status": "passed"}}},
        "validation_summary.json": {"status": "passed"},
        "experience_summary.json": {"iteration_id": "loop-experience-rel-path-0001"},
        "next_round_context.json": {
            "experience_summary_path": "experience_summary.json",
            "validation_summary_path": "validation_summary.json",
            "artifacts": {
                "proposer_context": "proposer_context",
                "experience_summary_json": "experience_summary.json",
                "validation_summary_json": "validation_summary.json",
            },
        },
    }.items():
        (iteration_dir / name).write_text(json.dumps(payload), encoding="utf-8")
    proposer_context_dir = iteration_dir / "proposer_context"
    proposer_context_dir.mkdir(parents=True, exist_ok=True)
    (proposer_context_dir / "manifest.json").write_text("{}", encoding="utf-8")

    result = validate_artifact_contract(
        artifact_kind="loop",
        path=loop_dir,
    )

    assert result["ok"] is True


def test_loop_contract_validator_accepts_absolute_experience_summary_path(
    tmp_path: Path,
) -> None:
    loop_dir = loop_root_path(tmp_path / "reports", "loop-experience-abs-path")
    iteration_dir = loop_dir / "iterations" / "loop-experience-abs-path-0001"
    iteration_dir.mkdir(parents=True, exist_ok=True)
    experience_summary_path = iteration_dir / "experience_summary.json"

    (loop_dir / "loop.json").write_text(
        json.dumps(
            {
                "loop_id": "loop-experience-abs-path",
                "profile_name": "demo",
                "project_name": "demo",
                "request": {},
                "iteration_count": 1,
                "stop_reason": "done",
                "iterations": [{"iteration_id": "loop-experience-abs-path-0001"}],
            }
        ),
        encoding="utf-8",
    )
    (loop_dir / "iteration_history.jsonl").write_text(
        json.dumps({"iteration_id": "loop-experience-abs-path-0001"}) + "\n",
        encoding="utf-8",
    )
    for name, payload in {
        "iteration.json": {"iteration_id": "loop-experience-abs-path-0001"},
        "proposal_input.json": {"objective": {}, "experience": {}},
        "proposal_output.json": {"proposal": {}},
        "selected_candidate.json": {"candidate_id": "cand-1"},
        "benchmark_summary.json": {"evaluation": {"validation": {"status": "passed"}}},
        "validation_summary.json": {"status": "passed"},
        "experience_summary.json": {"iteration_id": "loop-experience-abs-path-0001"},
        "next_round_context.json": {
            "experience_summary_path": str(experience_summary_path.resolve()),
            "validation_summary_path": "validation_summary.json",
            "artifacts": {
                "proposer_context": "proposer_context",
                "experience_summary_json": "experience_summary.json",
                "validation_summary_json": "validation_summary.json",
            },
        },
    }.items():
        (iteration_dir / name).write_text(json.dumps(payload), encoding="utf-8")
    proposer_context_dir = iteration_dir / "proposer_context"
    proposer_context_dir.mkdir(parents=True, exist_ok=True)
    (proposer_context_dir / "manifest.json").write_text("{}", encoding="utf-8")

    result = validate_artifact_contract(
        artifact_kind="loop",
        path=loop_dir,
    )

    assert result["ok"] is True


def test_loop_contract_validator_requires_preserved_proposer_context_link(
    tmp_path: Path,
) -> None:
    loop_dir = loop_root_path(tmp_path / "reports", "loop-proposer-artifacts")
    iteration_dir = loop_dir / "iterations" / "loop-proposer-artifacts-0001"
    iteration_dir.mkdir(parents=True, exist_ok=True)

    (loop_dir / "loop.json").write_text(
        json.dumps(
            {
                "loop_id": "loop-proposer-artifacts",
                "profile_name": "demo",
                "project_name": "demo",
                "request": {},
                "iteration_count": 1,
                "stop_reason": "done",
                "iterations": [{"iteration_id": "loop-proposer-artifacts-0001"}],
            }
        ),
        encoding="utf-8",
    )
    (loop_dir / "iteration_history.jsonl").write_text(
        json.dumps({"iteration_id": "loop-proposer-artifacts-0001"}) + "\n",
        encoding="utf-8",
    )
    proposer_context_dir = iteration_dir / "proposer_context"
    proposer_context_dir.mkdir(parents=True, exist_ok=True)
    (proposer_context_dir / "manifest.json").write_text("{}", encoding="utf-8")
    for name, payload in {
        "iteration.json": {"iteration_id": "loop-proposer-artifacts-0001"},
        "proposal_input.json": {"objective": {}, "experience": {}},
        "proposal_output.json": {"proposal": {}},
        "selected_candidate.json": {"candidate_id": "cand-1"},
        "benchmark_summary.json": {"evaluation": {"validation": {"status": "passed"}}},
        "validation_summary.json": {"status": "passed"},
        "experience_summary.json": {"iteration_id": "loop-proposer-artifacts-0001"},
        "next_round_context.json": {
            "experience_summary_path": "experience_summary.json",
            "validation_summary_path": "validation_summary.json",
            "artifacts": {},
        },
    }.items():
        (iteration_dir / name).write_text(json.dumps(payload), encoding="utf-8")

    result = validate_artifact_contract(
        artifact_kind="loop",
        path=loop_dir,
    )

    assert result["ok"] is False
    assert any(
        "next_round_context.json missing artifacts.proposer_context" in error
        for error in result["errors"]
    )


def test_loop_contract_validator_requires_next_round_artifacts_object(
    tmp_path: Path,
) -> None:
    loop_dir = loop_root_path(tmp_path / "reports", "loop-missing-artifacts-object")
    iteration_dir = loop_dir / "iterations" / "loop-missing-artifacts-object-0001"
    iteration_dir.mkdir(parents=True, exist_ok=True)
    proposer_context_dir = iteration_dir / "proposer_context"
    proposer_context_dir.mkdir(parents=True, exist_ok=True)
    (proposer_context_dir / "manifest.json").write_text("{}", encoding="utf-8")

    (loop_dir / "loop.json").write_text(
        json.dumps(
            {
                "loop_id": "loop-missing-artifacts-object",
                "profile_name": "demo",
                "project_name": "demo",
                "request": {},
                "iteration_count": 1,
                "stop_reason": "done",
                "iterations": [{"iteration_id": "loop-missing-artifacts-object-0001"}],
            }
        ),
        encoding="utf-8",
    )
    (loop_dir / "iteration_history.jsonl").write_text(
        json.dumps({"iteration_id": "loop-missing-artifacts-object-0001"}) + "\n",
        encoding="utf-8",
    )
    for name, payload in {
        "iteration.json": {"iteration_id": "loop-missing-artifacts-object-0001"},
        "proposal_input.json": {"objective": {}, "experience": {}},
        "proposal_output.json": {"proposal": {}},
        "selected_candidate.json": {"candidate_id": "cand-1"},
        "benchmark_summary.json": {"evaluation": {"validation": {"status": "passed"}}},
        "validation_summary.json": {"status": "passed"},
        "experience_summary.json": {"iteration_id": "loop-missing-artifacts-object-0001"},
        "next_round_context.json": {
            "experience_summary_path": "experience_summary.json",
            "validation_summary_path": "validation_summary.json",
        },
    }.items():
        (iteration_dir / name).write_text(json.dumps(payload), encoding="utf-8")

    result = validate_artifact_contract(
        artifact_kind="loop",
        path=loop_dir,
    )

    assert result["ok"] is False
    assert any(
        "next_round_context.json missing artifacts object" in error
        for error in result["errors"]
    )


def test_loop_contract_validator_requires_validation_summary_artifact_link(
    tmp_path: Path,
) -> None:
    loop_dir = loop_root_path(tmp_path / "reports", "loop-missing-validation-artifact-link")
    iteration_dir = loop_dir / "iterations" / "loop-missing-validation-artifact-link-0001"
    iteration_dir.mkdir(parents=True, exist_ok=True)
    proposer_context_dir = iteration_dir / "proposer_context"
    proposer_context_dir.mkdir(parents=True, exist_ok=True)
    (proposer_context_dir / "manifest.json").write_text("{}", encoding="utf-8")

    (loop_dir / "loop.json").write_text(
        json.dumps(
            {
                "loop_id": "loop-missing-validation-artifact-link",
                "profile_name": "demo",
                "project_name": "demo",
                "request": {},
                "iteration_count": 1,
                "stop_reason": "done",
                "iterations": [{"iteration_id": "loop-missing-validation-artifact-link-0001"}],
            }
        ),
        encoding="utf-8",
    )
    (loop_dir / "iteration_history.jsonl").write_text(
        json.dumps({"iteration_id": "loop-missing-validation-artifact-link-0001"}) + "\n",
        encoding="utf-8",
    )
    for name, payload in {
        "iteration.json": {"iteration_id": "loop-missing-validation-artifact-link-0001"},
        "proposal_input.json": {"objective": {}, "experience": {}},
        "proposal_output.json": {"proposal": {}},
        "selected_candidate.json": {"candidate_id": "cand-1"},
        "benchmark_summary.json": {"evaluation": {"validation": {"status": "passed"}}},
        "validation_summary.json": {"status": "passed"},
        "experience_summary.json": {"iteration_id": "loop-missing-validation-artifact-link-0001"},
        "next_round_context.json": {
            "experience_summary_path": "experience_summary.json",
            "validation_summary_path": "validation_summary.json",
            "artifacts": {"proposer_context": "proposer_context"},
        },
    }.items():
        (iteration_dir / name).write_text(json.dumps(payload), encoding="utf-8")

    result = validate_artifact_contract(
        artifact_kind="loop",
        path=loop_dir,
    )

    assert result["ok"] is False
    assert any(
        "next_round_context.json missing artifacts.validation_summary_json" in error
        for error in result["errors"]
    )


def test_loop_contract_validator_requires_experience_summary_artifact_link(
    tmp_path: Path,
) -> None:
    loop_dir = loop_root_path(tmp_path / "reports", "loop-missing-experience-artifact-link")
    iteration_dir = loop_dir / "iterations" / "loop-missing-experience-artifact-link-0001"
    iteration_dir.mkdir(parents=True, exist_ok=True)
    proposer_context_dir = iteration_dir / "proposer_context"
    proposer_context_dir.mkdir(parents=True, exist_ok=True)
    (proposer_context_dir / "manifest.json").write_text("{}", encoding="utf-8")

    (loop_dir / "loop.json").write_text(
        json.dumps(
            {
                "loop_id": "loop-missing-experience-artifact-link",
                "profile_name": "demo",
                "project_name": "demo",
                "request": {},
                "iteration_count": 1,
                "stop_reason": "done",
                "iterations": [{"iteration_id": "loop-missing-experience-artifact-link-0001"}],
            }
        ),
        encoding="utf-8",
    )
    (loop_dir / "iteration_history.jsonl").write_text(
        json.dumps({"iteration_id": "loop-missing-experience-artifact-link-0001"}) + "\n",
        encoding="utf-8",
    )
    for name, payload in {
        "iteration.json": {"iteration_id": "loop-missing-experience-artifact-link-0001"},
        "proposal_input.json": {"objective": {}, "experience": {}},
        "proposal_output.json": {"proposal": {}},
        "selected_candidate.json": {"candidate_id": "cand-1"},
        "benchmark_summary.json": {"evaluation": {"validation": {"status": "passed"}}},
        "validation_summary.json": {"status": "passed"},
        "experience_summary.json": {"iteration_id": "loop-missing-experience-artifact-link-0001"},
        "next_round_context.json": {
            "experience_summary_path": "experience_summary.json",
            "validation_summary_path": "validation_summary.json",
            "artifacts": {
                "proposer_context": "proposer_context",
                "validation_summary_json": "validation_summary.json",
            },
        },
    }.items():
        (iteration_dir / name).write_text(json.dumps(payload), encoding="utf-8")

    result = validate_artifact_contract(
        artifact_kind="loop",
        path=loop_dir,
    )

    assert result["ok"] is False
    assert any(
        "next_round_context.json missing artifacts.experience_summary_json" in error
        for error in result["errors"]
    )


def test_loop_contract_validator_accepts_relative_proposer_context_link(
    tmp_path: Path,
) -> None:
    loop_dir = loop_root_path(tmp_path / "reports", "loop-proposer-rel-link")
    iteration_dir = loop_dir / "iterations" / "loop-proposer-rel-link-0001"
    iteration_dir.mkdir(parents=True, exist_ok=True)
    proposer_context_dir = iteration_dir / "proposer_context"
    proposer_context_dir.mkdir(parents=True, exist_ok=True)
    (proposer_context_dir / "manifest.json").write_text("{}", encoding="utf-8")

    (loop_dir / "loop.json").write_text(
        json.dumps(
            {
                "loop_id": "loop-proposer-rel-link",
                "profile_name": "demo",
                "project_name": "demo",
                "request": {},
                "iteration_count": 1,
                "stop_reason": "done",
                "iterations": [{"iteration_id": "loop-proposer-rel-link-0001"}],
            }
        ),
        encoding="utf-8",
    )
    (loop_dir / "iteration_history.jsonl").write_text(
        json.dumps({"iteration_id": "loop-proposer-rel-link-0001"}) + "\n",
        encoding="utf-8",
    )
    for name, payload in {
        "iteration.json": {"iteration_id": "loop-proposer-rel-link-0001"},
        "proposal_input.json": {"objective": {}, "experience": {}},
        "proposal_output.json": {"proposal": {}},
        "selected_candidate.json": {"candidate_id": "cand-1"},
        "benchmark_summary.json": {"evaluation": {"validation": {"status": "passed"}}},
        "validation_summary.json": {"status": "passed"},
        "experience_summary.json": {"iteration_id": "loop-proposer-rel-link-0001"},
        "next_round_context.json": {
            "experience_summary_path": "experience_summary.json",
            "validation_summary_path": "validation_summary.json",
            "artifacts": {
                "proposer_context": "proposer_context",
                "experience_summary_json": "experience_summary.json",
                "validation_summary_json": "validation_summary.json",
            },
        },
    }.items():
        (iteration_dir / name).write_text(json.dumps(payload), encoding="utf-8")

    result = validate_artifact_contract(
        artifact_kind="loop",
        path=loop_dir,
    )

    assert result["ok"] is True


def test_loop_contract_validator_accepts_absolute_proposer_context_link(
    tmp_path: Path,
) -> None:
    loop_dir = loop_root_path(tmp_path / "reports", "loop-proposer-abs-link")
    iteration_dir = loop_dir / "iterations" / "loop-proposer-abs-link-0001"
    iteration_dir.mkdir(parents=True, exist_ok=True)
    proposer_context_dir = iteration_dir / "proposer_context"
    proposer_context_dir.mkdir(parents=True, exist_ok=True)
    (proposer_context_dir / "manifest.json").write_text("{}", encoding="utf-8")

    (loop_dir / "loop.json").write_text(
        json.dumps(
            {
                "loop_id": "loop-proposer-abs-link",
                "profile_name": "demo",
                "project_name": "demo",
                "request": {},
                "iteration_count": 1,
                "stop_reason": "done",
                "iterations": [{"iteration_id": "loop-proposer-abs-link-0001"}],
            }
        ),
        encoding="utf-8",
    )
    (loop_dir / "iteration_history.jsonl").write_text(
        json.dumps({"iteration_id": "loop-proposer-abs-link-0001"}) + "\n",
        encoding="utf-8",
    )
    for name, payload in {
        "iteration.json": {"iteration_id": "loop-proposer-abs-link-0001"},
        "proposal_input.json": {"objective": {}, "experience": {}},
        "proposal_output.json": {"proposal": {}},
        "selected_candidate.json": {"candidate_id": "cand-1"},
        "benchmark_summary.json": {"evaluation": {"validation": {"status": "passed"}}},
        "validation_summary.json": {"status": "passed"},
        "experience_summary.json": {"iteration_id": "loop-proposer-abs-link-0001"},
        "next_round_context.json": {
            "experience_summary_path": "experience_summary.json",
            "validation_summary_path": "validation_summary.json",
            "artifacts": {
                "proposer_context": str(proposer_context_dir.resolve()),
                "experience_summary_json": "experience_summary.json",
                "validation_summary_json": "validation_summary.json",
            },
        },
    }.items():
        (iteration_dir / name).write_text(json.dumps(payload), encoding="utf-8")

    result = validate_artifact_contract(
        artifact_kind="loop",
        path=loop_dir,
    )

    assert result["ok"] is True


def test_loop_contract_validator_rejects_wrong_proposer_context_link(
    tmp_path: Path,
) -> None:
    loop_dir = loop_root_path(tmp_path / "reports", "loop-proposer-wrong-link")
    iteration_dir = loop_dir / "iterations" / "loop-proposer-wrong-link-0001"
    iteration_dir.mkdir(parents=True, exist_ok=True)
    proposer_context_dir = iteration_dir / "proposer_context"
    proposer_context_dir.mkdir(parents=True, exist_ok=True)
    (proposer_context_dir / "manifest.json").write_text("{}", encoding="utf-8")

    (loop_dir / "loop.json").write_text(
        json.dumps(
            {
                "loop_id": "loop-proposer-wrong-link",
                "profile_name": "demo",
                "project_name": "demo",
                "request": {},
                "iteration_count": 1,
                "stop_reason": "done",
                "iterations": [{"iteration_id": "loop-proposer-wrong-link-0001"}],
            }
        ),
        encoding="utf-8",
    )
    (loop_dir / "iteration_history.jsonl").write_text(
        json.dumps({"iteration_id": "loop-proposer-wrong-link-0001"}) + "\n",
        encoding="utf-8",
    )
    for name, payload in {
        "iteration.json": {"iteration_id": "loop-proposer-wrong-link-0001"},
        "proposal_input.json": {"objective": {}, "experience": {}},
        "proposal_output.json": {"proposal": {}},
        "selected_candidate.json": {"candidate_id": "cand-1"},
        "benchmark_summary.json": {"evaluation": {"validation": {"status": "passed"}}},
        "validation_summary.json": {"status": "passed"},
        "experience_summary.json": {"iteration_id": "loop-proposer-wrong-link-0001"},
        "next_round_context.json": {
            "experience_summary_path": "experience_summary.json",
            "validation_summary_path": "validation_summary.json",
            "artifacts": {"proposer_context": "wrong-proposer-context"},
        },
    }.items():
        (iteration_dir / name).write_text(json.dumps(payload), encoding="utf-8")

    result = validate_artifact_contract(
        artifact_kind="loop",
        path=loop_dir,
    )

    assert result["ok"] is False
    assert any(
        "next_round_context.json artifacts.proposer_context does not point to proposer_context"
        in error
        for error in result["errors"]
    )


def test_loop_contract_validator_requires_benchmark_validation_when_validation_summary_is_non_empty(
    tmp_path: Path,
) -> None:
    loop_dir = loop_root_path(tmp_path / "reports", "loop-validation-nonempty")
    iteration_dir = loop_dir / "iterations" / "loop-validation-nonempty-0001"
    iteration_dir.mkdir(parents=True, exist_ok=True)

    (loop_dir / "loop.json").write_text(
        json.dumps(
            {
                "loop_id": "loop-validation-nonempty",
                "profile_name": "demo",
                "project_name": "demo",
                "request": {},
                "iteration_count": 1,
                "stop_reason": "done",
                "iterations": [{"iteration_id": "loop-validation-nonempty-0001"}],
            }
        ),
        encoding="utf-8",
    )
    (loop_dir / "iteration_history.jsonl").write_text(
        json.dumps({"iteration_id": "loop-validation-nonempty-0001"}) + "\n",
        encoding="utf-8",
    )
    for name, payload in {
        "iteration.json": {"iteration_id": "loop-validation-nonempty-0001"},
        "proposal_input.json": {"objective": {}, "experience": {}},
        "proposal_output.json": {"proposal": {}},
        "selected_candidate.json": {"candidate_id": "cand-1"},
        "benchmark_summary.json": {"evaluation": {}},
        "validation_summary.json": {"status": "passed"},
        "experience_summary.json": {"iteration_id": "loop-validation-nonempty-0001"},
        "next_round_context.json": {
            "experience_summary_path": "experience_summary.json",
            "validation_summary_path": str(iteration_dir / "validation_summary.json"),
        },
    }.items():
        (iteration_dir / name).write_text(json.dumps(payload), encoding="utf-8")
    proposer_context_dir = iteration_dir / "proposer_context"
    proposer_context_dir.mkdir(parents=True, exist_ok=True)
    (proposer_context_dir / "manifest.json").write_text("{}", encoding="utf-8")

    result = validate_artifact_contract(
        artifact_kind="loop",
        path=loop_dir,
    )

    assert result["ok"] is False
    assert any(
        "benchmark_summary.json missing evaluation.validation for non-empty validation_summary.json"
        in error
        for error in result["errors"]
    )
