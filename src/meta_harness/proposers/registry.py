from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from meta_harness.proposers.command_proposer import CommandProposer
from meta_harness.proposers.heuristic_proposer import HeuristicProposer
from meta_harness.proposers.llm_harness_proposer import LLMHarnessProposer


class BaseRegistryProposer:
    proposer_id: str = ""

    def propose(
        self,
        *,
        objective: dict[str, Any],
        experience: dict[str, Any],
        constraints: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(slots=True)
class _RegistryEntry:
    proposer: BaseRegistryProposer


_PROPOSER_REGISTRY: dict[str, _RegistryEntry] = {}


def register_proposer(proposer: BaseRegistryProposer) -> BaseRegistryProposer:
    _PROPOSER_REGISTRY[str(proposer.proposer_id)] = _RegistryEntry(proposer=proposer)
    return proposer


def get_proposer(proposer_id: str) -> BaseRegistryProposer:
    ensure_default_proposers()
    entry = _PROPOSER_REGISTRY.get(str(proposer_id))
    if entry is None:
        available = ", ".join(list_proposers())
        raise KeyError(
            f"unknown proposer '{proposer_id}'"
            + (f"; available: {available}" if available else "")
        )
    return entry.proposer


def list_proposers() -> list[str]:
    ensure_default_proposers()
    return sorted(_PROPOSER_REGISTRY)


def build_proposer(
    proposer_id: str,
    *,
    effective_config: dict[str, Any] | None = None,
):
    if "," in proposer_id:
        return [
            build_proposer(part.strip(), effective_config=effective_config)
            for part in proposer_id.split(",")
            if part.strip()
        ]
    if proposer_id == "command":
        get_proposer(proposer_id)
        command = (
            (effective_config or {}).get("optimization", {}).get("proposal_command")
            if isinstance((effective_config or {}).get("optimization"), dict)
            else None
        )
        return CommandProposer(command=command if isinstance(command, list) else None)
    if proposer_id == "llm_harness":
        get_proposer(proposer_id)
        optimization = (effective_config or {}).get("optimization")
        llm_config = (
            optimization.get("llm_harness")
            if isinstance(optimization, dict) and isinstance(optimization.get("llm_harness"), dict)
            else {}
        )
        command = llm_config.get("command")
        model_name = llm_config.get("model") or llm_config.get("model_name")
        system_prompt = llm_config.get("system_prompt")
        prompt_template = llm_config.get("prompt_template")
        return LLMHarnessProposer(
            command=[str(item) for item in command] if isinstance(command, list) else None,
            model_name=str(model_name) if model_name is not None else None,
            system_prompt=str(system_prompt) if system_prompt is not None else None,
            prompt_template=str(prompt_template) if prompt_template is not None else None,
        )
    if proposer_id == "heuristic":
        get_proposer(proposer_id)
        return HeuristicProposer()
    resolved = get_proposer(proposer_id)
    return resolved


def rank_proposals(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = []
    for item in (dict(entry) for entry in proposals if isinstance(entry, dict)):
        proposal_score = float(item.get("proposal_score", 0.0))
        stability_score = float(item.get("stability_score", 0.0))
        cost_score = float(item.get("cost_score", 0.0))
        weighted_total = proposal_score * 0.6 + stability_score * 0.25 + cost_score * 0.15
        item["ranking_basis"] = {
            "proposal_score": proposal_score,
            "stability_score": stability_score,
            "cost_score": cost_score,
            "weighted_total": weighted_total,
        }
        ranked.append(item)
    ranked.sort(
        key=lambda item: (
            float((item.get("ranking_basis") or {}).get("weighted_total", 0.0)),
            float(item.get("stability_score", 0.0)),
            float(item.get("cost_score", 0.0)),
            str(item.get("proposal_id", "")),
        ),
        reverse=True,
    )
    for index, item in enumerate(ranked, start=1):
        item["proposal_rank"] = index
    return ranked


def ensure_default_proposers() -> None:
    defaults = {
        "heuristic_failure_family": HeuristicProposer(),
        "command": CommandProposer(),
        "llm_harness": LLMHarnessProposer(),
        "heuristic": HeuristicProposer(),
    }
    for key, proposer in defaults.items():
        _PROPOSER_REGISTRY.setdefault(key, _RegistryEntry(proposer=proposer))
