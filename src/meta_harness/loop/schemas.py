from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Literal, Protocol

from meta_harness.proposers.base import ProposalEnvelope, Proposer as ProposerProtocol


class TaskPluginProtocol(Protocol):
    plugin_id: str

    def assemble_objective(
        self,
        *,
        profile_name: str,
        project_name: str,
        task_set_path: Path,
        effective_config: dict[str, Any],
    ) -> dict[str, Any]: ...

    def assemble_experience(
        self,
        *,
        runs_root: Path,
        candidates_root: Path,
        selected_runs: list[dict[str, Any]],
        objective: dict[str, Any],
    ) -> dict[str, Any]: ...

    def build_evaluation_plan(
        self,
        *,
        objective: dict[str, Any],
        effective_config: dict[str, Any],
    ) -> dict[str, Any]: ...

    def summarize_iteration(
        self,
        *,
        benchmark_payload: dict[str, Any],
        selected_variant: dict[str, Any],
    ) -> dict[str, Any]: ...


@dataclass(slots=True)
class ExperienceQuery:
    max_history: int = 25
    best_k: int | None = None
    focus: str | None = None
    dedupe_failure_families: bool = False
    history_sources: list[dict[str, str]] = field(default_factory=list)

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SearchLoopRequest:
    config_root: Path
    runs_root: Path
    candidates_root: Path
    profile_name: str
    project_name: str
    task_set_path: Path
    loop_id: str | None = None
    task_plugin_id: str | None = None
    proposer_id: str | None = None
    reports_root: Path | None = None
    proposals_root: Path | None = None
    max_iterations: int = 1
    focus: str | None = None
    evaluation_mode: Literal["auto", "shadow-run", "benchmark"] = "auto"
    stop_target_score: float | None = None
    no_improvement_limit: int = 1
    experience_query: ExperienceQuery | None = None

    def model_dump(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("config_root", "runs_root", "candidates_root", "task_set_path", "reports_root", "proposals_root"):
            value = payload.get(key)
            if isinstance(value, Path):
                payload[key] = str(value)
        return payload


@dataclass(slots=True)
class SelectionResult:
    candidate_id: str
    run_id: str | None
    score: float
    variant_name: str | None = None
    reason: str = ""
    selection_kind: str = "current"
    raw_result: dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StopDecision:
    should_stop: bool
    reason: str
    iteration_index: int
    max_iterations: int
    target_score: float | None = None
    no_improvement_count: int = 0

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LoopIterationArtifact:
    iteration_id: str
    iteration_index: int
    objective: dict[str, Any]
    experience: dict[str, Any]
    proposal: dict[str, Any]
    candidate_id: str
    candidate_path: str
    proposal_id: str | None = None
    proposal_path: str | None = None
    run_id: str | None = None
    run_path: str | None = None
    selection: SelectionResult | None = None
    stop_decision: StopDecision | None = None
    evaluation: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    proposal_evaluation: dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.selection is not None:
            payload["selection"] = self.selection.model_dump()
        if self.stop_decision is not None:
            payload["stop_decision"] = self.stop_decision.model_dump()
        return payload


@dataclass(slots=True)
class LoopExperienceSummary:
    iteration_id: str
    focus: str | None
    selected_candidate_id: str | None
    selected_run_id: str | None
    score_delta: float
    best_score: float
    representative_failures: list[dict[str, Any]] = field(default_factory=list)
    representative_successes: list[dict[str, Any]] = field(default_factory=list)
    capability_gaps: list[dict[str, Any]] = field(default_factory=list)
    representative_artifacts: dict[str, Any] = field(default_factory=dict)
    next_actions: list[str] = field(default_factory=list)

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LoopSummary:
    loop_id: str
    profile_name: str
    project_name: str
    request: SearchLoopRequest
    best_candidate_id: str | None
    best_run_id: str | None
    best_score: float
    iteration_count: int
    stop_reason: str
    iterations: list[LoopIterationArtifact] = field(default_factory=list)
    objective: dict[str, Any] = field(default_factory=dict)
    experience: dict[str, Any] = field(default_factory=dict)
    loop_dir: str | None = None

    def model_dump(self) -> dict[str, Any]:
        return {
            "loop_id": self.loop_id,
            "profile_name": self.profile_name,
            "project_name": self.project_name,
            "request": self.request.model_dump(),
            "best_candidate_id": self.best_candidate_id,
            "best_run_id": self.best_run_id,
            "best_score": self.best_score,
            "iteration_count": self.iteration_count,
            "stop_reason": self.stop_reason,
            "iterations": [iteration.model_dump() for iteration in self.iterations],
            "objective": self.objective,
            "experience": self.experience,
            "loop_dir": self.loop_dir,
        }
