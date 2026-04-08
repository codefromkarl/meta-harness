from __future__ import annotations

from pydantic import BaseModel


class RunScoreRequest(BaseModel):
    reports_root: str
    runs_root: str
    requested_by: str | None = None
    evaluators: list[str] | None = None


class RunExportTraceRequest(BaseModel):
    reports_root: str
    runs_root: str
    output_path: str | None = None
    format: str = "otel-json"
    destination: str = "download"
    config_root: str = "configs"
    integration_name: str | None = None
    requested_by: str | None = None


class DatasetExtractFailuresRequest(BaseModel):
    reports_root: str
    runs_root: str
    output_path: str
    requested_by: str | None = None
    profile: str | None = None
    project: str | None = None


class DatasetBuildTaskSetRequest(BaseModel):
    task_set_path: str
    output_path: str
    dataset_id: str
    version: str = "v1"


class DatasetIngestAnnotationsRequest(BaseModel):
    dataset_path: str
    annotations_path: str
    output_path: str


class DatasetDeriveSplitRequest(BaseModel):
    dataset_path: str
    output_path: str
    split: str
    dataset_id: str
    version: str


class DatasetPromoteRequest(BaseModel):
    datasets_root: str
    dataset_id: str
    version: str
    split: str | None = None
    promoted_by: str | None = None
    reason: str | None = None


class PromoteCandidateRequest(BaseModel):
    candidates_root: str
    runs_root: str | None = None
    reason: str | None = None
    promoted_by: str | None = None
    evidence_run_ids: list[str] = []


class GateEvaluateRequest(BaseModel):
    policy_path: str
    target_path: str
    target_type: str
    target_ref: str
    evidence_refs: list[str] = []


class GateEvaluateByPolicyRequest(BaseModel):
    config_root: str = "configs"
    target_path: str
    target_type: str
    target_ref: str
    evidence_refs: list[str] = []


class OptimizeProposeRequest(BaseModel):
    reports_root: str
    config_root: str
    runs_root: str
    candidates_root: str
    proposals_root: str = "proposals"
    profile: str
    project: str
    proposal_only: bool = False
    requested_by: str | None = None


class OptimizeLoopRequest(BaseModel):
    reports_root: str
    config_root: str
    runs_root: str
    candidates_root: str
    task_set_path: str
    profile: str
    project: str
    proposals_root: str = "proposals"
    loop_id: str | None = None
    plugin_id: str = "default"
    proposer_id: str = "heuristic"
    max_iterations: int = 8
    focus: str | None = None
    requested_by: str | None = None


class OptimizeMaterializeProposalRequest(BaseModel):
    config_root: str
    candidates_root: str
    proposals_root: str = "proposals"


class WorkflowCompileRequest(BaseModel):
    workflow_path: str
    output_path: str
    config_root: str = "configs"


class WorkflowRunRequest(BaseModel):
    reports_root: str
    workflow_path: str
    profile: str
    project: str
    config_root: str = "configs"
    runs_root: str = "runs"
    requested_by: str | None = None


class WorkflowBenchmarkRequest(BaseModel):
    reports_root: str
    workflow_path: str
    profile: str
    project: str
    spec_path: str
    config_root: str = "configs"
    runs_root: str = "runs"
    candidates_root: str = "candidates"
    focus: str | None = None
    requested_by: str | None = None


class WorkflowBenchmarkSuiteRequest(BaseModel):
    reports_root: str
    workflow_path: str
    profile: str
    project: str
    suite_path: str
    config_root: str = "configs"
    runs_root: str = "runs"
    candidates_root: str = "candidates"
    requested_by: str | None = None


class ObservationBenchmarkRequest(BaseModel):
    reports_root: str
    config_root: str
    runs_root: str
    candidates_root: str
    profile: str
    project: str
    task_set_path: str
    spec_path: str
    focus: str | None = None
    auto_compact_runs: bool = True
    requested_by: str | None = None


class StrategyCreateCandidateRequest(BaseModel):
    strategy_card_path: str
    config_root: str
    candidates_root: str
    profile: str
    project: str


class StrategyRecommendWebScrapeRequest(BaseModel):
    page_profile: dict[str, object]
    workload_profile: dict[str, object]
    config_root: str = "configs"
    strategy_card_paths: list[str] | None = None
    limit: int = 4


class StrategyAuditWebScrapeRequest(BaseModel):
    page_profile: dict[str, object]
    workload_profile: dict[str, object]
    config_root: str = "configs"
    strategy_card_paths: list[str] | None = None
    benchmark_report_path: str | None = None
    limit: int = 4


class StrategyBuildWebScrapeAuditSpecRequest(BaseModel):
    page_profile: dict[str, object]
    workload_profile: dict[str, object]
    output_path: str
    config_root: str = "configs"
    strategy_card_paths: list[str] | None = None
    baseline: str = "current_strategy"
    experiment: str = "web_scrape_audit"
    limit: int = 4
    repeats: int = 1


class StrategyBenchmarkRequest(BaseModel):
    reports_root: str
    strategy_card_paths: list[str]
    config_root: str
    runs_root: str
    candidates_root: str
    profile: str
    project: str
    task_set_path: str
    experiment: str
    baseline: str
    focus: str | None = None
    template: str = "generic"
    requested_by: str | None = None


class AnnotationCreateRequest(BaseModel):
    annotations_root: str
    target_type: str
    target_ref: str
    label: str
    value: str
    notes: str | None = None
    annotator: str | None = None


class IntegrationAnalyzeRequest(BaseModel):
    config_root: str = "configs"
    reports_root: str = "reports"
    intent_text: str | None = None
    target_project_path: str | None = None
    primitive_id: str | None = None
    workflow_paths: list[str] | None = None
    user_goal: str = ""


class IntegrationScaffoldRequest(BaseModel):
    config_root: str = "configs"
    spec_path: str | None = None
    harness_spec_path: str | None = None


class IntegrationReviewRequest(BaseModel):
    config_root: str = "configs"
    spec_path: str | None = None
    harness_spec_path: str | None = None
    reviewer: str
    approve_checks: list[str] = []
    approve_all_checks: bool = False
    overrides_path: str | None = None
    notes: str = ""
    activate_binding: bool = False


class IntegrationBenchmarkRequest(BaseModel):
    config_root: str = "configs"
    reports_root: str = "reports"
    runs_root: str = "runs"
    candidates_root: str = "candidates"
    spec_path: str
    profile: str
    project: str
    task_set_path: str
    focus: str | None = None


class IntegrationOuterLoopRequest(BaseModel):
    config_root: str = "configs"
    reports_root: str = "reports"
    runs_root: str = "runs"
    candidates_root: str = "candidates"
    harness_spec_path: str
    profile: str
    project: str
    task_set_path: str
    proposal_paths: list[str] = []
    iteration_id: str | None = None
    focus: str | None = None
