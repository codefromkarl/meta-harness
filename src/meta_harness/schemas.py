from __future__ import annotations

from datetime import datetime, UTC
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


def _normalize_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _string_list(values: list[str] | None) -> list[str]:
    return [str(item) for item in values or []]


class CandidateLineage(BaseModel):
    parent_candidate_id: str | None = None
    proposal_id: str | None = None
    source_proposal_ids: list[str] = Field(default_factory=list)
    iteration_id: str | None = None
    source_iteration_ids: list[str] = Field(default_factory=list)
    source_run_ids: list[str] = Field(default_factory=list)
    source_artifacts: list[str] = Field(default_factory=list)


class CandidateMetadata(BaseModel):
    candidate_id: str
    profile: str
    project: str
    notes: str = ""
    parent_candidate_id: str | None = None
    proposal_id: str | None = None
    source_proposal_ids: list[str] = Field(default_factory=list)
    iteration_id: str | None = None
    source_iteration_ids: list[str] = Field(default_factory=list)
    source_run_ids: list[str] = Field(default_factory=list)
    source_artifacts: list[str] = Field(default_factory=list)
    lineage: CandidateLineage = Field(default_factory=CandidateLineage)
    code_patch_artifact: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def sync_lineage(self) -> "CandidateMetadata":
        field_set = self.model_fields_set
        parent_candidate_id = _normalize_optional_string(self.parent_candidate_id)
        if parent_candidate_id is None and "lineage" in field_set:
            parent_candidate_id = _normalize_optional_string(self.lineage.parent_candidate_id)

        proposal_id = _normalize_optional_string(self.proposal_id)
        if proposal_id is None and "lineage" in field_set:
            proposal_id = _normalize_optional_string(self.lineage.proposal_id)

        iteration_id = _normalize_optional_string(self.iteration_id)
        if iteration_id is None and "lineage" in field_set:
            iteration_id = _normalize_optional_string(self.lineage.iteration_id)

        source_proposal_ids = _string_list(self.source_proposal_ids)
        if not source_proposal_ids and "source_proposal_ids" not in field_set and "lineage" in field_set:
            source_proposal_ids = _string_list(self.lineage.source_proposal_ids)

        source_iteration_ids = _string_list(self.source_iteration_ids)
        if not source_iteration_ids and "source_iteration_ids" not in field_set and "lineage" in field_set:
            source_iteration_ids = _string_list(self.lineage.source_iteration_ids)

        source_run_ids = _string_list(self.source_run_ids)
        if not source_run_ids and "source_run_ids" not in field_set and "lineage" in field_set:
            source_run_ids = _string_list(self.lineage.source_run_ids)

        source_artifacts = _string_list(self.source_artifacts)
        if not source_artifacts and "source_artifacts" not in field_set and "lineage" in field_set:
            source_artifacts = _string_list(self.lineage.source_artifacts)

        self.parent_candidate_id = parent_candidate_id
        self.proposal_id = proposal_id
        self.source_proposal_ids = source_proposal_ids
        self.iteration_id = iteration_id
        self.source_iteration_ids = source_iteration_ids
        self.source_run_ids = source_run_ids
        self.source_artifacts = source_artifacts
        self.lineage = CandidateLineage(
            parent_candidate_id=parent_candidate_id,
            proposal_id=proposal_id,
            source_proposal_ids=source_proposal_ids,
            iteration_id=iteration_id,
            source_iteration_ids=source_iteration_ids,
            source_run_ids=source_run_ids,
            source_artifacts=source_artifacts,
        )
        return self


class RunMetadata(BaseModel):
    run_id: str
    profile: str
    project: str
    candidate_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkspaceArtifact(BaseModel):
    source_repo: str
    workspace_dir: str
    patch_applied: bool = False
    patch_already_present: bool = False
    code_patch_artifact: str | None = None


class TraceEvent(BaseModel):
    step_id: str
    phase: str
    status: str
    run_id: str | None = None
    task_id: str | None = None
    session_ref: str | None = None
    candidate_id: str | None = None
    candidate_harness_id: str | None = None
    proposal_id: str | None = None
    iteration_id: str | None = None
    wrapper_path: str | None = None
    source_artifacts: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None
    prompt_ref: str | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    retrieval_refs: list[str] | None = None
    artifact_refs: list[str] | None = None
    token_usage: dict[str, int] | None = None
    latency_ms: int | None = None
    error: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ScoreReport(BaseModel):
    correctness: dict
    cost: dict
    maintainability: dict
    architecture: dict
    retrieval: dict
    human_collaboration: dict
    capability_scores: dict[str, dict[str, Any]] = Field(default_factory=dict)
    workflow_scores: dict[str, Any] = Field(default_factory=dict)
    probes: dict[str, Any] = Field(default_factory=dict)
    composite: float


class EvaluatorRun(BaseModel):
    evaluator_name: str
    run_id: str
    status: Literal["queued", "running", "completed", "failed"]
    report: dict[str, Any] = Field(default_factory=dict)
    trace_grade: dict[str, Any] = Field(default_factory=dict)
    profiling: dict[str, Any] = Field(default_factory=dict)
    trace_artifact: str | None = None
    duration_ms: int | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class GateCondition(BaseModel):
    kind: str
    path: str
    value: Any


class GatePolicy(BaseModel):
    policy_id: str
    policy_type: Literal["smoke", "regression", "benchmark", "promotion"]
    scope: dict[str, str] = Field(default_factory=dict)
    conditions: list[GateCondition] = Field(default_factory=list)
    waiver_rules: list[dict[str, Any]] = Field(default_factory=list)
    notification_rules: list[dict[str, Any]] = Field(default_factory=list)
    enabled: bool = True


class PrimitiveMetric(BaseModel):
    name: str
    kind: Literal["float", "int", "bool", "string"]
    higher_is_better: bool | None = None
    required: bool = False


class ProbeSchema(BaseModel):
    fingerprints: list[str] = Field(default_factory=list)
    probes: list[str] = Field(default_factory=list)


class EvaluationThresholds(BaseModel):
    field_completeness: float | None = None
    grounded_field_rate: float | None = None


class EvaluationContract(BaseModel):
    artifact_requirements: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    latency_budget_ms: int | None = None
    quality_thresholds: EvaluationThresholds = Field(default_factory=EvaluationThresholds)


class WorkflowHarnessRef(BaseModel):
    harness_id: str
    candidate_harness_id: str | None = None
    proposal_id: str | None = None
    iteration_id: str | None = None
    wrapper_path: str | None = None
    source_artifacts: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


class PageProfile(BaseModel):
    complexity: Literal["low", "medium", "high"] = "medium"
    dynamicity: Literal["static", "lightly_dynamic", "heavily_dynamic"] = "static"
    anti_bot_level: Literal["low", "medium", "high"] = "low"
    requires_rendering: bool = False
    requires_interaction: bool = False
    schema_stability: Literal["stable", "moderate", "volatile"] = "stable"
    media_dependency: Literal["low", "medium", "high"] = "low"


class WorkloadProfile(BaseModel):
    usage_mode: Literal["ad_hoc", "recurring"] = "ad_hoc"
    batch_size: int | None = None
    latency_sla_ms: int | None = None
    budget_mode: Literal["low_cost", "balanced", "high_success"] = "balanced"
    freshness_requirement: Literal["low", "medium", "high"] = "medium"
    allowed_failure_rate: float | None = None


class ProposalTemplate(BaseModel):
    template_id: str
    title: str
    hypothesis: str
    knobs: dict[str, Any] = Field(default_factory=dict)
    expected_signals: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class PrimitivePack(BaseModel):
    primitive_id: str
    version: str = "v1"
    kind: str
    description: str = ""
    input_contract: dict[str, Any] = Field(default_factory=dict)
    output_contract: dict[str, Any] = Field(default_factory=dict)
    evaluation_contract: EvaluationContract = Field(default_factory=EvaluationContract)
    metric_schema: list[PrimitiveMetric] = Field(default_factory=list)
    probe_schema: ProbeSchema = Field(default_factory=ProbeSchema)
    default_knobs: dict[str, Any] = Field(default_factory=dict)
    default_scenarios: list[dict[str, Any]] = Field(default_factory=list)
    proposal_templates: list[ProposalTemplate] = Field(default_factory=list)


class TaskMethodSpec(BaseModel):
    method_id: str
    primitive_id: str
    description: str = ""
    portable_knobs: list[str] = Field(default_factory=list)
    default_patch: dict[str, Any] = Field(default_factory=dict)
    expected_signals: dict[str, Any] = Field(default_factory=dict)
    success_metrics: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class ClawBindingSpec(BaseModel):
    binding_id: str
    claw_family: str
    primitive_id: str
    adapter_kind: str
    method_mapping: dict[str, str] = Field(default_factory=dict)
    binding_patch: dict[str, Any] = Field(default_factory=dict)
    execution: dict[str, Any] = Field(default_factory=dict)
    artifact_contract: dict[str, Any] = Field(default_factory=dict)
    trace_mapping: dict[str, Any] = Field(default_factory=dict)
    review: dict[str, Any] = Field(default_factory=dict)


class TransferPolicy(BaseModel):
    scope: Literal["portable_only", "portable_first", "binding_specific"] = (
        "portable_first"
    )
    frozen_keys: list[str] = Field(default_factory=list)
    blocked_keys: list[str] = Field(default_factory=list)
    source_binding: str | None = None
    validated_targets: list[str] = Field(default_factory=list)


class EvaluatorPack(BaseModel):
    pack_id: str
    version: str = "v1"
    supported_primitives: list[str] = Field(default_factory=list)
    command: list[str] = Field(default_factory=list)
    artifact_requirements: list[str] = Field(default_factory=list)
    emits_metrics: list[str] = Field(default_factory=list)
    emits_probes: list[str] = Field(default_factory=list)


class WorkflowStep(BaseModel):
    step_id: str
    primitive_id: str | None = None
    harness_ref: WorkflowHarnessRef | None = None
    candidate_harness_ref: WorkflowHarnessRef | None = None
    method_id: str | None = None
    binding_id: str | None = None
    title: str | None = None
    role: Literal["hot_path", "fallback_path", "warmup", "post_process"] = "hot_path"
    depends_on: list[str] = Field(default_factory=list)
    workdir: str | None = None
    command: list[str] | None = None
    knobs: dict[str, Any] = Field(default_factory=dict)
    page_profile: PageProfile | None = None
    workload_profile: WorkloadProfile | None = None
    evaluation: EvaluationContract = Field(default_factory=EvaluationContract)
    expectations: dict[str, Any] = Field(default_factory=dict)
    weight: float = 1.0
    optional: bool = False

    @model_validator(mode="after")
    def _validate_execution_target(self) -> "WorkflowStep":
        if (
            self.primitive_id is None
            and self.harness_ref is None
            and self.candidate_harness_ref is None
        ):
            raise ValueError(
                "workflow step must define primitive_id, harness_ref, or candidate_harness_ref"
            )
        return self


class OptimizationPolicy(BaseModel):
    enabled: bool = True
    allowed_primitives: list[str] = Field(default_factory=list)
    focus_roles: list[str] = Field(
        default_factory=lambda: ["hot_path", "fallback_path"]
    )
    objective_weights: dict[str, float] = Field(default_factory=dict)
    frozen_knobs: list[str] = Field(default_factory=list)


class WorkflowSpec(BaseModel):
    workflow_id: str
    version: str = "v1"
    profile: str | None = None
    project: str | None = None
    evaluator_packs: list[str] = Field(default_factory=list)
    page_profile: PageProfile = Field(default_factory=PageProfile)
    workload_profile: WorkloadProfile = Field(default_factory=WorkloadProfile)
    steps: list[WorkflowStep] = Field(default_factory=list)
    optimization_policy: OptimizationPolicy = Field(default_factory=OptimizationPolicy)
    metadata: dict[str, Any] = Field(default_factory=dict)


class JobResultRef(BaseModel):
    target_type: str
    target_id: str
    path: str | None = None


class JobRecord(BaseModel):
    job_id: str
    job_type: str
    execution_mode: Literal["inline", "queued"] = "inline"
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"] = "queued"
    parent_job_id: str | None = None
    attempt: int = 1
    requested_by: str | None = None
    job_input: dict[str, Any] = Field(default_factory=dict)
    result_ref: JobResultRef | None = None
    error: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ServiceError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ServiceWarning(BaseModel):
    code: str
    message: str


class ServiceEnvelope(BaseModel):
    ok: bool
    data: Any = None
    job: JobRecord | None = None
    error: ServiceError | None = None
    warnings: list[ServiceWarning] = Field(default_factory=list)


class StrategyCard(BaseModel):
    strategy_id: str
    title: str
    source: str
    category: str = "indexing"
    primitive_id: str | None = None
    capability_metadata: dict[str, Any] = Field(default_factory=dict)
    group: str | None = None
    priority: int = 100
    change_type: Literal["config_only", "patch_based", "not_yet_executable"]
    variant_name: str | None = None
    hypothesis: str | None = None
    implementation_id: str | None = None
    variant_type: (
        Literal["parameter", "feature_toggle", "implementation_patch", "method_family", "composite"]
        | None
    ) = None
    compatibility: dict[str, Any] = Field(default_factory=dict)
    expected_benefits: list[str] = Field(default_factory=list)
    expected_costs: list[str] = Field(default_factory=list)
    config_patch: dict[str, Any] | None = None
    code_patch: str | None = None
    expected_signals: dict[str, Any] | None = None
    risk_notes: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class ProposalRecord(BaseModel):
    proposal_id: str
    profile: str
    project: str
    proposer_kind: str
    strategy: str
    notes: str = ""
    source_run_ids: list[str] = Field(default_factory=list)
    proposal: dict[str, Any] = Field(default_factory=dict)
    config_patch: dict[str, Any] | None = None
    candidate_id: str | None = None
    status: Literal["proposed", "materialized"] = "proposed"
    code_patch_artifact: str | None = None
    evaluation_artifact: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    materialized_at: datetime | None = None


class AnnotationRecord(BaseModel):
    annotation_id: str
    target_type: str
    target_ref: str
    label: str
    value: Any = None
    notes: str = ""
    annotator: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DatasetCase(BaseModel):
    case_id: str | None = None
    source_type: str = "failure_signature"
    run_id: str
    profile: str
    project: str
    task_id: str
    phase: str
    step_id: str | None = None
    raw_error: str
    failure_signature: str
    scenario: str | None = None
    difficulty: str | None = None
    weight: float | None = None
    expectations: dict[str, Any] | None = None
    phase_names: list[str] | None = None
    query: str | None = None
    expected_paths: list[str] | None = None
    expected_rank_max: int | None = None
    expected_grounding_refs: list[str] | None = None
    expected_answer_contains: list[str] | None = None
    labels: list[str] | None = None
    annotations: list[AnnotationRecord] | None = None


class DatasetVersion(BaseModel):
    dataset_id: str
    version: str
    schema_version: str
    case_count: int
    cases: list[DatasetCase]
    source_summary: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_by: str | None = None
    frozen: bool = True
    split: str | None = None
    source_dataset: dict[str, Any] | None = None
    annotation_count: int = 0
