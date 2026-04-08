from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from meta_harness.archive import list_run_records
from meta_harness.candidates import create_candidate, load_candidate_record
from meta_harness.config_loader import load_effective_config
from meta_harness.optimizer_context import _collect_failure_context
from meta_harness.primitive_registry import load_registered_primitive_pack
from meta_harness.template_utils import (
    _build_template_context,
    _normalize_template_paths,
    _resolve_template,
)
from meta_harness.transfer import create_transfer_candidate


def _run_proposal_command(
    command: list[str],
    payload: dict[str, Any],
    effective_config: dict[str, Any],
) -> dict[str, Any]:
    from meta_harness.proposers.command_proposer import run_proposal_command

    return run_proposal_command(
        command=command,
        payload=payload,
        effective_config=effective_config,
    )

def propose_candidate_from_architecture_recommendation(
    *,
    config_root: Path,
    candidates_root: Path,
    profile_name: str,
    project_name: str,
    source_run_ids: list[str],
    architecture_recommendation: dict[str, Any],
    runs_root: Path | None = None,
    method_id: str | None = None,
    source_binding_id: str | None = None,
    target_binding_id: str | None = None,
) -> str:
    focus = str(architecture_recommendation.get("focus", "retrieval"))
    primitive_id = architecture_recommendation.get("primitive_id")
    primitive_id = str(primitive_id) if primitive_id else None
    effective_config = load_effective_config(
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
    )
    proposal_strategy = str(
        architecture_recommendation.get(
            "proposal_strategy", f"explore_{focus}_method_family"
        )
    )
    hypothesis = str(architecture_recommendation.get("hypothesis", "")).strip()
    selected_pack_template = _select_pack_driven_proposal_template(
        config_root=config_root,
        architecture_recommendation=architecture_recommendation,
    )

    expected_signals = architecture_recommendation.get("expected_signals")
    if not isinstance(expected_signals, dict):
        if selected_pack_template is not None and selected_pack_template.expected_signals:
            expected_signals = dict(selected_pack_template.expected_signals)
        elif focus == "binding":
            expected_signals = {
                "probes": {
                    "web_scrape.binding_payload_present_rate": {"min": 1},
                    "web_scrape.assistant_reply_rate": {"min": 1},
                }
            }
        elif focus == "retrieval":
            expected_signals = {"probes": {"retrieval.retrieval_budget": {"min": 1}}}
        elif focus == "memory":
            expected_signals = {
                "probes": {"memory.routing_confidence": {"min": 0.5}}
            }
        else:
            expected_signals = {"probes": {"indexing.chunk_profile": {"min": 1}}}

    tags = architecture_recommendation.get("tags")
    if not isinstance(tags, list):
        tags = ["auto-propose", "method-family", focus]
        if primitive_id:
            tags.append(primitive_id)
        if selected_pack_template is not None:
            tags.extend(selected_pack_template.tags)

    config_patch = _default_architecture_config_patch(
        config_root=config_root,
        focus=focus,
        architecture_recommendation=architecture_recommendation,
        effective_config=effective_config,
        reference_config=_best_reference_config(
            runs_root=runs_root,
            profile_name=profile_name,
            project_name=project_name,
            source_run_ids=source_run_ids,
        ),
        history_configs=_historical_reference_configs(
            runs_root=runs_root,
            profile_name=profile_name,
            project_name=project_name,
            source_run_ids=source_run_ids,
            focus=focus,
        ),
    )
    proposal = {
        "strategy": proposal_strategy,
        "variant_type": str(
            architecture_recommendation.get("variant_type", "method_family")
        ),
        "hypothesis": hypothesis,
        "source_runs": source_run_ids,
        "architecture_recommendation": architecture_recommendation,
        "expected_signals": expected_signals,
        "tags": tags,
    }
    if selected_pack_template is not None:
        proposal["selected_template_id"] = selected_pack_template.template_id

    if target_binding_id is not None:
        if not method_id:
            raise ValueError("target binding transfer requires method_id")
        if not source_binding_id:
            raise ValueError("target binding transfer requires source_binding_id")
        return create_transfer_candidate(
            config_root=config_root,
            candidates_root=candidates_root,
            profile_name=profile_name,
            project_name=project_name,
            method_id=method_id,
            source_binding_id=source_binding_id,
            target_binding_id=target_binding_id,
            local_patch=config_patch,
            proposal_overrides=proposal,
            notes=f"architecture recommendation transfer: {proposal_strategy}",
            reuse_existing=True,
        )

    return create_candidate(
        candidates_root=candidates_root,
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
        config_patch=config_patch,
        notes=f"architecture recommendation proposal: {proposal_strategy}",
        proposal=proposal,
        reuse_existing=True,
    )

def _default_architecture_config_patch(
    *,
    config_root: Path,
    focus: str,
    architecture_recommendation: dict[str, Any],
    effective_config: dict[str, Any],
    reference_config: dict[str, Any] | None = None,
    history_configs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    gap_signals = architecture_recommendation.get("gap_signals")
    gap_signals = gap_signals if isinstance(gap_signals, list) else []
    metric_thresholds = architecture_recommendation.get("metric_thresholds")
    metric_thresholds = metric_thresholds if isinstance(metric_thresholds, dict) else {}

    config_patch: dict[str, Any] = {
        "optimization": {
            "focus": focus,
            "architecture_recommendation": architecture_recommendation,
        }
    }

    pack_template = _select_pack_driven_proposal_template(
        config_root=config_root,
        architecture_recommendation=architecture_recommendation,
    )
    if pack_template is not None:
        primitive_id = str(architecture_recommendation["primitive_id"])
        config_patch["workflow"] = {
            "primitives": {
                primitive_id: dict(pack_template.knobs),
            }
        }
        return config_patch

    if focus == "retrieval":
        is_strong_gap = len(gap_signals) >= 3 or (
            float(metric_thresholds.get("retrieval_hit_rate", 0.7)) >= 0.8
            and float(metric_thresholds.get("retrieval_mrr", 0.5)) >= 0.6
        )
        retrieval_candidates = [
            {"top_k": 12, "rerank_k": 24},
            {"top_k": 16, "rerank_k": 32},
            {"top_k": 20, "rerank_k": 40},
        ]
        candidate_index = 1 if is_strong_gap else 0
        selected, avoided_existing_band = _select_exploration_candidate(
            retrieval_candidates,
            candidate_index,
            current_config=effective_config.get("retrieval"),
            reference_config=(reference_config or {}).get("retrieval"),
        )
        config_patch["retrieval"] = (
            selected
            if avoided_existing_band
            else _nearest_historical_candidate(
                selected,
                current_config=effective_config.get("retrieval"),
                history_configs=history_configs,
            )
            or selected
        )
        return config_patch

    if focus == "memory":
        is_strong_gap = len(gap_signals) >= 3 or (
            float(metric_thresholds.get("memory_completeness", 0.8)) >= 0.85
            and float(metric_thresholds.get("memory_freshness", 0.85)) >= 0.9
        )
        memory_candidates = [
            {
                "enabled": True,
                "routing_mode": "freshness-biased",
                "freshness_bias": 0.8,
                "stale_prune_threshold": 0.12,
            },
            {
                "enabled": True,
                "routing_mode": "freshness-biased",
                "freshness_bias": 0.9,
                "stale_prune_threshold": 0.08,
            },
            {
                "enabled": True,
                "routing_mode": "strict-pruning",
                "freshness_bias": 0.95,
                "stale_prune_threshold": 0.05,
            },
        ]
        candidate_index = 1 if is_strong_gap else 0
        selected, avoided_existing_band = _select_exploration_candidate(
            memory_candidates,
            candidate_index,
            current_config=effective_config.get("memory"),
            reference_config=(reference_config or {}).get("memory"),
        )
        config_patch["memory"] = (
            selected
            if avoided_existing_band
            else _nearest_historical_candidate(
                selected,
                current_config=effective_config.get("memory"),
                history_configs=history_configs,
            )
            or selected
        )
        return config_patch

    if focus == "indexing":
        is_strong_gap = len(gap_signals) >= 2 or (
            float(metric_thresholds.get("vector_coverage_ratio", 0.9)) >= 0.95
            and float(metric_thresholds.get("index_freshness_ratio", 0.85)) >= 0.9
        )
        indexing_candidates = [
            {"chunk_size": 1200, "chunk_overlap": 160},
            {"chunk_size": 1400, "chunk_overlap": 200},
            {"chunk_size": 1600, "chunk_overlap": 240},
        ]
        candidate_index = 1 if is_strong_gap else 0
        selected, avoided_existing_band = _select_exploration_candidate(
            indexing_candidates,
            candidate_index,
            current_config=effective_config.get("indexing"),
            reference_config=(reference_config or {}).get("indexing"),
        )
        config_patch["indexing"] = (
            selected
            if avoided_existing_band
            else _nearest_historical_candidate(
                selected,
                current_config=effective_config.get("indexing"),
                history_configs=history_configs,
            )
            or selected
        )
        return config_patch

    if focus == "binding":
        runtime_binding = (
            effective_config.get("runtime", {}).get("binding", {})
            if isinstance(effective_config.get("runtime"), dict)
            else {}
        )
        timeout = runtime_binding.get("timeout")
        timeout_value = int(timeout) if isinstance(timeout, (int, float)) else 600
        binding_patch = {
            "json": True,
            "local": True,
            "timeout": max(timeout_value, 900),
            "verbose": "on",
        }
        config_patch["runtime"] = {
            "binding": {
                **binding_patch,
            }
        }
        return config_patch

    return config_patch

def _select_pack_driven_proposal_template(
    *,
    config_root: Path,
    architecture_recommendation: dict[str, Any],
):
    primitive_id = architecture_recommendation.get("primitive_id")
    if not isinstance(primitive_id, str) or not primitive_id:
        return None

    try:
        pack = load_registered_primitive_pack(config_root, primitive_id)
    except FileNotFoundError:
        return None

    templates = list(pack.proposal_templates)
    if not templates:
        return None

    gap_signals = architecture_recommendation.get("gap_signals")
    gap_signals = gap_signals if isinstance(gap_signals, list) else []
    candidate_index = 1 if len(gap_signals) >= 2 and len(templates) > 1 else 0
    return templates[candidate_index]

def _select_exploration_candidate(
    candidates: list[dict[str, Any]],
    candidate_index: int,
    *,
    current_config: Any,
    reference_config: Any,
) -> tuple[dict[str, Any], bool]:
    candidate_index = max(0, min(candidate_index, len(candidates) - 1))
    selected = candidates[candidate_index]
    normalized_current = current_config if isinstance(current_config, dict) else {}
    normalized_reference = reference_config if isinstance(reference_config, dict) else {}
    avoided_existing_band = False

    while (
        candidate_index < len(candidates) - 1
        and (
            _is_same_candidate(selected, normalized_current)
            or _is_same_candidate(selected, normalized_reference)
        )
    ):
        avoided_existing_band = True
        candidate_index += 1
        selected = candidates[candidate_index]
    return selected, avoided_existing_band

def _is_same_candidate(candidate: dict[str, Any], config: dict[str, Any]) -> bool:
    if not config:
        return False
    for key, value in candidate.items():
        if config.get(key) != value:
            return False
    return True

def _nearest_historical_candidate(
    default_candidate: dict[str, Any],
    *,
    current_config: Any,
    history_configs: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if not history_configs:
        return None
    normalized_current = current_config if isinstance(current_config, dict) else {}
    available = [
        config
        for config in history_configs
        if isinstance(config, dict) and not _is_same_candidate(config, normalized_current)
    ]
    if not available:
        return None
    ranked = sorted(
        available,
        key=lambda config: (
            _candidate_distance(config, normalized_current),
            0 if not _is_same_candidate(config, default_candidate) else 1,
        ),
    )
    selected = ranked[0]
    if _is_same_candidate(selected, default_candidate):
        return None
    return selected

def _candidate_distance(candidate: dict[str, Any], config: dict[str, Any]) -> float:
    keys = sorted(set(candidate) | set(config))
    distance = 0.0
    for key in keys:
        left = candidate.get(key)
        right = config.get(key)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            distance += abs(float(left) - float(right))
        elif left != right:
            distance += 1.0
    return distance

def _best_reference_config(
    *,
    runs_root: Path | None,
    profile_name: str,
    project_name: str,
    source_run_ids: list[str],
) -> dict[str, Any] | None:
    if runs_root is None or not runs_root.exists():
        return None
    source_ids = set(source_run_ids)
    matching_runs = [
        record
        for record in list_run_records(runs_root)
        if record.get("profile") == profile_name
        and record.get("project") == project_name
        and record.get("run_id") in source_ids
        and isinstance(record.get("score"), dict)
    ]
    if not matching_runs:
        return None
    best = max(
        matching_runs,
        key=lambda record: float((record.get("score") or {}).get("composite", 0.0)),
    )
    config = best.get("config")
    return config if isinstance(config, dict) else None

def _historical_reference_configs(
    *,
    runs_root: Path | None,
    profile_name: str,
    project_name: str,
    source_run_ids: list[str],
    focus: str,
) -> list[dict[str, Any]]:
    if runs_root is None or not runs_root.exists():
        return []
    source_ids = set(source_run_ids)
    records = [
        record
        for record in list_run_records(runs_root)
        if record.get("profile") == profile_name
        and record.get("project") == project_name
        and record.get("run_id") in source_ids
    ]
    history: list[dict[str, Any]] = []
    for record in records:
        config = record.get("config")
        if not isinstance(config, dict):
            continue
        if focus == "retrieval":
            section = config.get("retrieval")
        elif focus == "indexing":
            section = config.get("indexing")
        else:
            section = config.get("memory")
        if isinstance(section, dict):
            history.append(section)
    return history

def propose_candidate_from_failures(
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    profile_name: str,
    project_name: str,
) -> str:
    generated = build_proposal_from_failures(
        config_root=config_root,
        runs_root=runs_root,
        profile_name=profile_name,
        project_name=project_name,
    )
    return create_candidate(
        candidates_root=candidates_root,
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
        config_patch=generated.get("config_patch"),
        code_patch_content=generated.get("code_patch"),
        notes=generated.get("notes", "optimizer proposal"),
        proposal=generated.get("proposal"),
        reuse_existing=True,
    )

def build_proposal_from_failures(
    *,
    config_root: Path,
    runs_root: Path,
    profile_name: str,
    project_name: str,
) -> dict[str, Any]:
    from meta_harness.proposers import build_proposer

    effective_config = load_effective_config(
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
    )
    matching_runs, failure_records = _collect_failure_context(
        runs_root=runs_root,
        profile_name=profile_name,
        project_name=project_name,
        history_sources=effective_config.get("optimization", {}).get("history_sources"),
    )

    objective = {
        "profile_name": profile_name,
        "project_name": project_name,
        "focus": str(effective_config.get("optimization", {}).get("focus", "all")),
        "strategy": "failure_history_search",
        "history_sources": effective_config.get("optimization", {}).get("history_sources")
        or [{"profile": profile_name, "project": project_name}],
    }
    experience = {
        "matching_runs": matching_runs,
        "failure_records": failure_records,
        "source_run_ids": [
            str(record["run_id"])
            for record in matching_runs
            if record.get("run_id") is not None
        ],
    }
    constraints = {
        "profile_name": profile_name,
        "project_name": project_name,
        "effective_config": effective_config,
        "proposal_command": effective_config.get("optimization", {}).get(
            "proposal_command"
        ),
    }

    proposal_command = constraints["proposal_command"]
    proposer_id = _select_failure_proposer_id(effective_config, proposal_command)
    proposer = build_proposer(
        proposer_id,
        effective_config=effective_config,
    )
    generated = proposer.propose(
        objective=objective,
        experience=experience,
        constraints=constraints,
    )
    proposal_payload = (
        generated.get("proposal")
        if isinstance(generated.get("proposal"), dict)
        else {}
    )
    return {
        "proposer_kind": str(
            generated.get("proposer_kind", getattr(proposer, "proposer_id", "unknown"))
        ),
        "config_patch": (
            generated.get("config_patch")
            if isinstance(generated.get("config_patch"), dict)
            else None
        ),
        "code_patch": (
            str(generated["code_patch"])
            if generated.get("code_patch") is not None
            else None
        ),
        "notes": str(generated.get("notes", "optimizer proposal")),
        "proposal": proposal_payload,
        "source_run_ids": [
            str(item)
            for item in generated.get("source_run_ids", [])
            if str(item)
        ],
    }


def _select_failure_proposer_id(
    effective_config: dict[str, Any],
    proposal_command: Any,
) -> str:
    optimization = effective_config.get("optimization")
    if isinstance(optimization, dict):
        llm_harness = optimization.get("llm_harness")
        if (
            isinstance(llm_harness, dict)
            and isinstance(llm_harness.get("command"), list)
            and bool(llm_harness.get("model") or llm_harness.get("model_name"))
        ):
            return "llm_harness"
    return "command" if proposal_command else "heuristic"
