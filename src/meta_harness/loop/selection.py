from __future__ import annotations

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
    selected_result = best_variant or evaluation_result
    current_score = _selection_score(selected_result, selection_policy)
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
        selection_rationale=_build_selection_rationale(
            selected_result,
            selection_policy=selection_policy,
            evaluation_result=evaluation_result,
        ),
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
            normalized_variants = [
                item for item in variants if isinstance(item, dict)
            ]
            frontier = _pareto_frontier(normalized_variants)
            return max(frontier or normalized_variants, key=_multi_objective_sort_key)
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
    metrics = _multi_objective_metrics(item)
    aggregate = (
        metrics["composite"]
        + metrics["stability_margin"] * 0.1
        + metrics["cost_efficiency"] * 0.1
    )
    return metrics["bottleneck"] * 10.0 + aggregate


def _multi_objective_metrics(item: dict[str, Any]) -> dict[str, float]:
    stability = item.get("stability")
    if not isinstance(stability, dict):
        stability = {}
    cost = item.get("cost")
    if not isinstance(cost, dict):
        cost = {}
    composite = _variant_score(item)
    stability_margin = max(
        0.0,
        1.0
        - float(stability.get("composite_range", 0.0) or 0.0)
        - float(stability.get("composite_stddev", 0.0) or 0.0),
    )
    cost_efficiency = max(
        0.0,
        1.0 - float(cost.get("total_cost", 0.0) or 0.0) / 10.0,
    )
    bottleneck = min(composite, stability_margin, cost_efficiency)
    return {
        "composite": composite,
        "stability_margin": stability_margin,
        "cost_efficiency": cost_efficiency,
        "bottleneck": bottleneck,
    }


def _multi_objective_sort_key(item: dict[str, Any]) -> tuple[float, float, float]:
    metrics = _multi_objective_metrics(item)
    return (
        metrics["bottleneck"],
        _multi_objective_rank(item),
        metrics["composite"],
    )


def _pareto_frontier(variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    frontier: list[dict[str, Any]] = []
    for candidate in variants:
        if not any(
            other is not candidate and _dominates(other, candidate)
            for other in variants
        ):
            frontier.append(candidate)
    return frontier


def _dominates(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_metrics = _multi_objective_metrics(left)
    right_metrics = _multi_objective_metrics(right)
    metric_keys = ("composite", "stability_margin", "cost_efficiency")
    return all(
        left_metrics[key] >= right_metrics[key] for key in metric_keys
    ) and any(left_metrics[key] > right_metrics[key] for key in metric_keys)


def _build_selection_rationale(
    item: dict[str, Any],
    *,
    selection_policy: str | None,
    evaluation_result: dict[str, Any],
) -> list[str]:
    policy = str(selection_policy or "best_by_score")
    rationale = [f"selection_policy={policy}"]
    variant_name = item.get("name")
    if isinstance(variant_name, str) and variant_name:
        rationale.append(f"variant={variant_name}")
    if policy == "best_by_stability":
        rationale.append(f"stability_rank={_stability_rank(item):.3f}")
    elif policy == "baseline_guardrail":
        if bool(item.get("is_reference")):
            rationale.append("baseline_guardrail=retained_reference")
        rationale.append(f"score={_variant_score(item):.3f}")
    elif policy == "multi_objective_rank":
        metrics = _multi_objective_metrics(item)
        frontier = _pareto_frontier(
            [variant for variant in evaluation_result.get("variants", []) if isinstance(variant, dict)]
        )
        if item in frontier:
            rationale.append("pareto_frontier=selected")
        rationale.append(f"composite={metrics['composite']:.3f}")
        rationale.append(f"stability_margin={metrics['stability_margin']:.3f}")
        rationale.append(f"cost_efficiency={metrics['cost_efficiency']:.3f}")
        rationale.append(f"bottleneck={metrics['bottleneck']:.3f}")
    else:
        rationale.append(f"score={_selection_score(item, selection_policy):.3f}")
    return rationale
