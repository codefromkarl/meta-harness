from __future__ import annotations

from dataclasses import dataclass

from meta_harness.loop.schemas import StopDecision


def decide_stop(
    *,
    iteration_index: int,
    max_iterations: int,
    best_score: float,
    target_score: float | None = None,
    no_improvement_count: int = 0,
    no_improvement_limit: int = 1,
    current_score: float | None = None,
    score_history: list[float] | None = None,
    recent_scores: list[float] | None = None,
    stability_window: int = 3,
    instability_threshold: float | None = None,
    regression_tolerance: float | None = None,
) -> StopDecision:
    if target_score is not None and best_score >= target_score:
        return StopDecision(
            should_stop=True,
            reason="target score reached",
            iteration_index=iteration_index,
            max_iterations=max_iterations,
            target_score=target_score,
            no_improvement_count=no_improvement_count,
        )

    if iteration_index >= max_iterations:
        return StopDecision(
            should_stop=True,
            reason="max iterations reached",
            iteration_index=iteration_index,
            max_iterations=max_iterations,
            target_score=target_score,
            no_improvement_count=no_improvement_count,
        )

    if (
        instability_threshold is not None
        and recent_scores
        and len(recent_scores) >= max(2, stability_window)
    ):
        window = recent_scores[-max(2, stability_window) :]
        if max(window) - min(window) >= instability_threshold:
            return StopDecision(
                should_stop=True,
                reason="instability threshold reached",
                iteration_index=iteration_index,
                max_iterations=max_iterations,
                target_score=target_score,
                no_improvement_count=no_improvement_count,
            )

    if (
        regression_tolerance is not None
        and current_score is not None
        and best_score - current_score >= regression_tolerance
    ):
        return StopDecision(
            should_stop=True,
            reason="regression tolerance reached",
            iteration_index=iteration_index,
            max_iterations=max_iterations,
            target_score=target_score,
            no_improvement_count=no_improvement_count,
        )

    if no_improvement_count >= no_improvement_limit:
        return StopDecision(
            should_stop=True,
            reason="no improvement limit reached",
            iteration_index=iteration_index,
            max_iterations=max_iterations,
            target_score=target_score,
            no_improvement_count=no_improvement_count,
        )

    return StopDecision(
        should_stop=False,
        reason="continue searching",
        iteration_index=iteration_index,
        max_iterations=max_iterations,
        target_score=target_score,
        no_improvement_count=no_improvement_count,
    )
