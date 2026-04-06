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
    composite: float


class StrategyCard(BaseModel):
    strategy_id: str
    title: str
    source: str
    category: str = "indexing"
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
