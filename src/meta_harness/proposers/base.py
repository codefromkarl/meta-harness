from __future__ import annotations

from typing import Any, Protocol, TypedDict


class ProposalEnvelope(TypedDict, total=False):
    proposer_kind: str
    proposal: dict[str, Any]
    config_patch: dict[str, Any] | None
    code_patch: str | None
    notes: str
    source_run_ids: list[str]
    proposal_id: str
    candidate_id: str
    proposal_score: float
    stability_score: float
    cost_score: float


class Proposer(Protocol):
    proposer_id: str

    def propose(
        self,
        *,
        objective: dict[str, Any],
        experience: dict[str, Any],
        constraints: dict[str, Any],
    ) -> ProposalEnvelope: ...
