from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class IntegrationIntent(BaseModel):
    target_project_path: str
    primitive_id: str | None = None
    workflow_files: list[str] = Field(default_factory=list)
    user_goal: str = ""
    preferred_adapter_kind: str | None = None
    allow_wrapper_generation: bool = True
    allow_code_inspection: bool = True


class ProjectObservation(BaseModel):
    detected_entrypoints: list[dict[str, Any]] = Field(default_factory=list)
    workflow_files: list[str] = Field(default_factory=list)
    output_candidates: list[dict[str, Any]] = Field(default_factory=list)
    input_candidates: list[dict[str, Any]] = Field(default_factory=list)
    environment_requirements: list[str] = Field(default_factory=list)
    logging_patterns: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class ExecutionModel(BaseModel):
    kind: Literal[
        "json_stdout_cli",
        "file_artifact_workflow",
        "http_job_api",
        "daemon_session",
        "browser_automation",
        "unknown",
    ] = "unknown"
    entry_command: list[str] = Field(default_factory=list)
    input_mode: str = ""
    output_mode: str = ""
    needs_wrapper: bool = False
    wrapper_reason: str | None = None


class HarnessSpec(BaseModel):
    spec_id: str
    target_project_path: str
    execution_model: ExecutionModel
    capability_modules: list[str] = Field(default_factory=list)
    detected_entrypoints: list[dict[str, Any]] = Field(default_factory=list)
    input_boundaries: list[str] = Field(default_factory=list)
    output_boundaries: list[str] = Field(default_factory=list)
    environment_requirements: list[str] = Field(default_factory=list)
    risk_points: list[str] = Field(default_factory=list)
    manual_checks: list[str] = Field(default_factory=list)
    candidate_primitives: list[str] = Field(default_factory=list)
    user_goal: str = ""


class ArtifactMapping(BaseModel):
    source_artifact: str
    target_artifact: str
    transform: str
    required: bool = True
    confidence: float = 0.0


class IntegrationSpec(BaseModel):
    spec_id: str
    target_project_path: str
    primitive_id: str
    execution_model: ExecutionModel
    binding_patch: dict[str, Any] = Field(default_factory=dict)
    wrapper_plan: dict[str, Any] = Field(default_factory=dict)
    artifact_mappings: list[ArtifactMapping] = Field(default_factory=list)
    missing_contracts: list[str] = Field(default_factory=list)
    risk_points: list[str] = Field(default_factory=list)
    manual_checks: list[str] = Field(default_factory=list)


class ScaffoldPlan(BaseModel):
    files_to_create: list[str] = Field(default_factory=list)
    files_to_update: list[str] = Field(default_factory=list)
    generated_binding_id: str | None = None
    generated_wrapper_path: str | None = None
    generated_test_path: str | None = None


class ReviewChecklist(BaseModel):
    spec_id: str
    summary: str = ""
    risk_points: list[str] = Field(default_factory=list)
    manual_checks: list[str] = Field(default_factory=list)


class IntegrationReviewResult(BaseModel):
    spec_id: str
    reviewer: str
    status: Literal["needs_review", "approved", "activated"] = "needs_review"
    approved_checks: list[str] = Field(default_factory=list)
    missing_checks: list[str] = Field(default_factory=list)
    notes: str = ""
    reviewed_spec_path: str | None = None
    binding_path: str | None = None
    activation_path: str | None = None


class IntegrationActivationRecord(BaseModel):
    spec_id: str
    binding_id: str
    binding_path: str
    reviewer: str
    reviewed_spec_path: str
    review_result_path: str
    status: Literal["activated"] = "activated"


class CandidateHarnessPatch(BaseModel):
    candidate_id: str
    harness_spec_id: str
    iteration_id: str
    title: str = ""
    summary: str = ""
    change_kind: Literal[
        "wrapper_patch",
        "config_patch",
        "task_patch",
        "workflow_patch",
        "code_patch",
    ] = "wrapper_patch"
    target_files: list[str] = Field(default_factory=list)
    patch: dict[str, Any] = Field(default_factory=dict)
    rationale: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    status: Literal["proposed", "benchmarked", "selected", "rejected", "promoted"] = (
        "proposed"
    )


class HarnessTaskRef(BaseModel):
    task_id: str
    phase: str
    command: list[str] = Field(default_factory=list)
    workdir: str | None = None
    expectations: dict[str, Any] = Field(default_factory=dict)


class HarnessRun(BaseModel):
    run_id: str
    candidate_id: str
    harness_spec_id: str
    iteration_id: str
    wrapper_path: str | None = None
    task_refs: list[HarnessTaskRef] = Field(default_factory=list)
    score: dict[str, Any] = Field(default_factory=dict)
    trace_refs: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    status: Literal["completed", "failed", "cancelled"] = "completed"


class IterationResult(BaseModel):
    iteration_id: str
    harness_spec_id: str
    selected_candidate_id: str | None = None
    candidate_ids: list[str] = Field(default_factory=list)
    run_ids: list[str] = Field(default_factory=list)
    score_summary: dict[str, Any] = Field(default_factory=dict)
    failure_modes: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    status: Literal["completed", "partial", "failed"] = "completed"
