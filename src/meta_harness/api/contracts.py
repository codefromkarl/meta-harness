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
    output_path: str
    format: str = "otel-json"
    requested_by: str | None = None


class DatasetExtractFailuresRequest(BaseModel):
    reports_root: str
    runs_root: str
    output_path: str
    requested_by: str | None = None
    profile: str | None = None
    project: str | None = None


class PromoteCandidateRequest(BaseModel):
    candidates_root: str


class OptimizeProposeRequest(BaseModel):
    reports_root: str
    config_root: str
    runs_root: str
    candidates_root: str
    profile: str
    project: str
    requested_by: str | None = None


class WorkflowCompileRequest(BaseModel):
    workflow_path: str
    output_path: str


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
