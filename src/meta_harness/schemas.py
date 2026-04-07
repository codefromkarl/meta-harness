from __future__ import annotations

from datetime import datetime, UTC
from typing import Any, Literal

from pydantic import BaseModel, Field


class CandidateMetadata(BaseModel):
    candidate_id: str
    profile: str
    project: str
    notes: str = ""
    parent_candidate_id: str | None = None
    code_patch_artifact: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


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
    candidate_id: str | None = None
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
    metric_schema: list[PrimitiveMetric] = Field(default_factory=list)
    probe_schema: ProbeSchema = Field(default_factory=ProbeSchema)
    default_knobs: dict[str, Any] = Field(default_factory=dict)
    default_scenarios: list[dict[str, Any]] = Field(default_factory=list)
    proposal_templates: list[ProposalTemplate] = Field(default_factory=list)


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
    primitive_id: str
    title: str | None = None
    role: Literal["hot_path", "fallback_path", "warmup", "post_process"] = "hot_path"
    depends_on: list[str] = Field(default_factory=list)
    workdir: str | None = None
    command: list[str] | None = None
    knobs: dict[str, Any] = Field(default_factory=dict)
    expectations: dict[str, Any] = Field(default_factory=dict)
    weight: float = 1.0
    optional: bool = False


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
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"] = "queued"
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


class DatasetCase(BaseModel):
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


class DatasetVersion(BaseModel):
    dataset_id: str
    version: str
    schema_version: str
    case_count: int
    cases: list[DatasetCase]
