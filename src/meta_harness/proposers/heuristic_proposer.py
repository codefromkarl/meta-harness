from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from meta_harness.proposers.base import ProposalEnvelope


@dataclass(slots=True)
class HeuristicProposer:
    proposer_id: str = "heuristic_failure_family"

    def propose(
        self,
        *,
        objective: dict[str, Any],
        experience: dict[str, Any],
        constraints: dict[str, Any],
    ) -> ProposalEnvelope:
        failure_records = experience.get("failure_records", [])
        matching_runs = experience.get("matching_runs", [])
        best_family = self._best_family(failure_records)
        source_run_ids = [
            str(record.get("run_id"))
            for record in matching_runs
            if str(record.get("run_id") or "")
        ]
        effective_config = dict(constraints.get("effective_config") or {})
        current_budget = effective_config.get("budget", {})
        max_turns = int(current_budget.get("max_turns", 12)) if isinstance(current_budget, dict) else 12
        config_patch = {"budget": {"max_turns": max_turns + 2}}
        proposal = {
            "strategy": "increase_budget_on_repeated_failures",
            "query": best_family,
            "failure_count": len(failure_records),
            "source_runs": source_run_ids,
            "config_patch": config_patch,
            "objective": objective,
        }
        return {
            "proposer_kind": "failure_family_search",
            "proposal": proposal,
            "config_patch": config_patch,
            "code_patch": None,
            "notes": f"heuristic proposal from failures: {best_family}".strip(),
            "source_run_ids": source_run_ids,
        }

    @staticmethod
    def _best_family(failure_records: list[dict[str, Any]]) -> str:
        family_counts: dict[str, int] = {}
        for failure in failure_records:
            family = str(failure.get("family") or failure.get("signature") or "").strip()
            if not family:
                continue
            family_counts[family] = family_counts.get(family, 0) + 1
        if not family_counts:
            return ""
        return max(family_counts.items(), key=lambda item: (item[1], item[0]))[0]
