from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from meta_harness.loop.schemas import SelectionResult


def score_from_evaluation_result(result: dict[str, Any]) -> float:
    if not result:
        return 0.0
    if isinstance(result.get("score"), dict):
        score = result["score"]
        if "composite" in score:
            return float(score.get("composite", 0.0))
        if "ranking_score" in score:
            return float(score.get("ranking_score", 0.0))
    if isinstance(result.get("score"), (int, float)):
        return float(result["score"])
    if isinstance(result.get("composite"), (int, float)):
        return float(result["composite"])
    if isinstance(result.get("ranking_score"), (int, float)):
        return float(result["ranking_score"])
    variants = result.get("variants")
    if isinstance(variants, list) and variants:
        return max(_variant_score(item) for item in variants)
    return 0.0


def select_best_result(
    *,
    candidate_id: str,
    evaluation_result: dict[str, Any],
    previous_best: SelectionResult | None = None,
    selection_policy: str | None = None,
) -> SelectionResult:
    best_variant = _best_variant(evaluation_result, selection_policy=selection_policy)
    current_score = _selection_score(best_variant or evaluation_result, selection_policy)
    current_run_id = None
    current_variant_name = None
    selected_candidate_id = candidate_id
    if isinstance(best_variant, dict):
        current_run_id = best_variant.get("best_run_id") or best_variant.get("run_id")
        current_variant_name = best_variant.get("name")
        variant_candidate_id = best_variant.get("candidate_id")
        if isinstance(variant_candidate_id, str) and variant_candidate_id:
            selected_candidate_id = variant_candidate_id
    elif isinstance(evaluation_result.get("run_id"), str):
        current_run_id = evaluation_result["run_id"]
    elif isinstance(evaluation_result.get("name"), str):
        current_variant_name = evaluation_result["name"]

    if previous_best is not None and previous_best.score >= current_score:
        return previous_best

    return SelectionResult(
        candidate_id=selected_candidate_id,
        run_id=str(current_run_id) if current_run_id is not None else None,
        score=current_score,
        variant_name=str(current_variant_name) if current_variant_name is not None else None,
        reason=f"selected by {selection_policy or 'best_by_score'}",
        selection_kind=str(selection_policy or "best_by_score"),
        raw_result=evaluation_result,
    )


def _best_variant(
    result: dict[str, Any],
    selection_policy: str | None = None,
) -> dict[str, Any] | None:
    variants = result.get("variants")
    if isinstance(variants, list) and variants:
        if selection_policy == "prefer_non_reference":
            non_reference = [
                item
                for item in variants
                if isinstance(item, dict) and not bool(item.get("is_reference"))
            ]
            if non_reference:
                return max(non_reference, key=_variant_score)
        if selection_policy == "best_by_stability":
            return max(variants, key=_stability_rank)
        if selection_policy == "baseline_guardrail":
            baseline = next(
                (
                    item
                    for item in variants
                    if isinstance(item, dict) and bool(item.get("is_reference"))
                ),
                None,
            )
            current = max(variants, key=_variant_score)
            if baseline is not None and _variant_score(current) < _variant_score(baseline):
                return baseline
            return current
        if selection_policy == "multi_objective_rank":
            return max(variants, key=_multi_objective_rank)
        return max(variants, key=_variant_score)
    return None


def _variant_score(item: dict[str, Any]) -> float:
    if not isinstance(item, dict):
        return 0.0
    if isinstance(item.get("ranking_score"), (int, float)):
        return float(item["ranking_score"])
    if isinstance(item.get("score"), dict):
        score = item["score"]
        if isinstance(score.get("composite"), (int, float)):
            return float(score["composite"])
        if isinstance(score.get("ranking_score"), (int, float)):
            return float(score["ranking_score"])
    if isinstance(item.get("composite"), (int, float)):
        return float(item["composite"])
    if isinstance(item.get("score"), (int, float)):
        return float(item["score"])
    return 0.0


def _selection_score(item: dict[str, Any], selection_policy: str | None) -> float:
    if selection_policy == "best_by_stability":
        return _stability_rank(item)
    if selection_policy == "multi_objective_rank":
        return _multi_objective_rank(item)
    return _variant_score(item)


def _stability_rank(item: dict[str, Any]) -> float:
    stability = item.get("stability")
    if not isinstance(stability, dict):
        stability = {}
    composite = _variant_score(item)
    composite_range = float(stability.get("composite_range", 0.0) or 0.0)
    composite_stddev = float(stability.get("composite_stddev", 0.0) or 0.0)
    penalty = composite_range + composite_stddev
    return composite - penalty


def _multi_objective_rank(item: dict[str, Any]) -> float:
    stability = item.get("stability")
    if not isinstance(stability, dict):
        stability = {}
    cost = item.get("cost")
    if not isinstance(cost, dict):
        cost = {}
    composite = _variant_score(item)
    stability_bonus = max(0.0, 1.0 - float(stability.get("composite_range", 0.0) or 0.0))
    cost_bonus = max(0.0, 1.0 - float(cost.get("total_cost", 0.0) or 0.0) / 10.0)
    return composite + stability_bonus * 0.1 + cost_bonus * 0.1
