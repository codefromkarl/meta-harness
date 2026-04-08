from __future__ import annotations

from pathlib import Path
from typing import Any

from meta_harness.config_loader import load_effective_config
from meta_harness.observation import summarize_observation
from meta_harness.observation_strategies import resolve_observation_strategy
from meta_harness.optimizer_generation import (
    propose_candidate_from_architecture_recommendation,
)
from meta_harness.optimizer_shadow import shadow_run_candidate
from meta_harness.runtime_execution import execute_managed_run
from meta_harness.services.optimize_service import propose_candidate_payload


def _should_bootstrap_observation_optimization(
    summary: dict[str, object],
    effective_config: dict[str, Any],
    *,
    auto_propose: bool,
) -> tuple[bool, str]:
    if bool(summary.get("needs_optimization")):
        return True, str(summary.get("recommended_focus", "none"))

    optimization = (
        (effective_config.get("optimization") or {})
        if isinstance(effective_config, dict)
        else {}
    )
    proposal_command = (
        optimization.get("proposal_command") if isinstance(optimization, dict) else None
    )
    llm_harness = optimization.get("llm_harness") if isinstance(optimization, dict) else None
    has_llm_harness = (
        isinstance(llm_harness, dict)
        and isinstance(llm_harness.get("command"), list)
        and bool(llm_harness.get("model") or llm_harness.get("model_name"))
    )
    latest_score = (
        summary.get("score") if isinstance(summary.get("score"), dict) else {}
    )
    latest_score = latest_score if isinstance(latest_score, dict) else {}
    if (
        auto_propose
        and (proposal_command or has_llm_harness)
        and not any(
            latest_score.get(section)
            for section in ("maintainability", "architecture", "retrieval")
        )
    ):
        return True, "retrieval"
    return False, str(summary.get("recommended_focus", "none"))


def observe_summary_payload(
    *,
    runs_root: Path,
    profile_name: str,
    project_name: str,
    config_root: Path = Path("configs"),
    limit: int | None = None,
) -> dict[str, Any]:
    return summarize_observation(
        runs_root=runs_root,
        profile_name=profile_name,
        project_name=project_name,
        config_root=config_root,
        limit=limit,
    )


def observe_once_payload(
    *,
    profile_name: str,
    project_name: str,
    task_set_path: Path,
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    auto_propose: bool = False,
    method_id: str | None = None,
    target_binding_id: str | None = None,
) -> dict[str, Any]:
    effective_config = load_effective_config(
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
    )
    execution = execute_managed_run(
        runs_root=runs_root,
        profile_name=profile_name,
        project_name=project_name,
        effective_config=effective_config,
        task_set_path=task_set_path,
    )
    run_id = str(execution["run_id"])
    score = execution["score"]
    summary = summarize_observation(
        runs_root=runs_root,
        profile_name=profile_name,
        project_name=project_name,
        config_root=config_root,
    )

    result: dict[str, object] = {
        "run_id": run_id,
        "score": score,
        "needs_optimization": bool(summary.get("needs_optimization")),
        "recommended_focus": summary.get("recommended_focus", "none"),
        "architecture_recommendation": summary.get("architecture_recommendation"),
        "triggered_optimization": False,
        "triggered_shadow_run": False,
    }

    needs_optimization, recommended_focus = _should_bootstrap_observation_optimization(
        {
            **summary,
            "score": score,
        },
        effective_config,
        auto_propose=auto_propose,
    )
    result["needs_optimization"] = needs_optimization
    result["recommended_focus"] = recommended_focus
    if result.get("architecture_recommendation") is None and needs_optimization:
        strategy = resolve_observation_strategy(
            config_root,
            profile_name,
            project_name,
        )
        thresholds = strategy.load_thresholds(config_root, profile_name, project_name)
        result["architecture_recommendation"] = strategy.architecture_recommendation(
            score,
            thresholds,
            focus_override=recommended_focus,
        )

    if auto_propose and needs_optimization:
        optimization = (
            (effective_config.get("optimization") or {})
            if isinstance(effective_config, dict)
            else {}
        )
        proposal_command = (
            optimization.get("proposal_command")
            if isinstance(optimization, dict)
            else None
        )
        llm_harness = (
            optimization.get("llm_harness")
            if isinstance(optimization, dict)
            else None
        )
        has_llm_harness = (
            isinstance(llm_harness, dict)
            and isinstance(llm_harness.get("command"), list)
            and bool(llm_harness.get("model") or llm_harness.get("model_name"))
        )
        source_binding_id = _source_binding_id(effective_config)
        if target_binding_id is not None and method_id is None:
            raise RuntimeError("target binding auto-propose requires method_id")
        if target_binding_id is not None and source_binding_id is None:
            raise RuntimeError("target binding auto-propose requires source binding in effective_config.runtime.binding.binding_id")

        if (proposal_command or has_llm_harness) and target_binding_id is None:
            proposal_payload = propose_candidate_payload(
                config_root=config_root,
                runs_root=runs_root,
                candidates_root=candidates_root,
                profile_name=profile_name,
                project_name=project_name,
            )
            candidate_id = str(proposal_payload["candidate_id"])
        else:
            architecture_recommendation = result.get("architecture_recommendation")
            if not isinstance(architecture_recommendation, dict):
                raise RuntimeError(
                    "auto-propose requires proposal_command or architecture_recommendation"
                )
            candidate_id = propose_candidate_from_architecture_recommendation(
                config_root=config_root,
                candidates_root=candidates_root,
                profile_name=profile_name,
                project_name=project_name,
                source_run_ids=[run_id],
                architecture_recommendation=architecture_recommendation,
                method_id=method_id,
                source_binding_id=source_binding_id,
                target_binding_id=target_binding_id,
            )
        result["triggered_optimization"] = True
        result["candidate_id"] = candidate_id
        if source_binding_id is not None:
            result["source_binding_id"] = source_binding_id
        if target_binding_id is not None:
            result["target_binding_id"] = target_binding_id
            shadow_run_id = shadow_run_candidate(
                candidates_root=candidates_root,
                runs_root=runs_root,
                candidate_id=candidate_id,
                task_set_path=task_set_path,
            )
            result["triggered_shadow_run"] = True
            result["shadow_run_id"] = shadow_run_id

    return result


def _source_binding_id(effective_config: dict[str, Any]) -> str | None:
    runtime = effective_config.get("runtime")
    if not isinstance(runtime, dict):
        return None
    binding = runtime.get("binding")
    if not isinstance(binding, dict):
        return None
    binding_id = binding.get("binding_id")
    return str(binding_id) if isinstance(binding_id, str) and binding_id else None
