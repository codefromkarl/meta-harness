from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_harness.config_loader import load_effective_config


DEFAULT_HEADROOM_THRESHOLDS: dict[str, dict[str, float]] = {
    "indexing": {
        "vector_coverage_ratio": 0.9,
        "index_freshness_ratio": 0.85,
    },
    "memory": {
        "memory_completeness": 0.8,
        "memory_freshness": 0.85,
        "memory_stale_ratio": 0.1,
    },
    "retrieval": {
        "retrieval_hit_rate": 0.7,
        "retrieval_mrr": 0.5,
        "grounded_answer_rate": 0.8,
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@dataclass(frozen=True)
class ObservationStrategy:
    name: str
    threshold_defaults: dict[str, dict[str, float]]
    metric_sections: tuple[str, ...] = ("maintainability", "architecture", "retrieval")

    def load_thresholds(
        self,
        config_root: Path,
        profile_name: str,
        project_name: str,
    ) -> dict[str, dict[str, float]]:
        try:
            effective_config = load_effective_config(
                config_root=config_root,
                profile_name=profile_name,
                project_name=project_name,
            )
        except (FileNotFoundError, ValueError):
            return self.threshold_defaults
        configured = (effective_config.get("optimization") or {}).get(
            "headroom_thresholds"
        ) or {}
        return _deep_merge(self.threshold_defaults, configured)

    def metric_gap_names(
        self,
        score: dict[str, Any],
        thresholds: dict[str, dict[str, float]],
    ) -> list[str]:
        maintainability = score.get("maintainability") or {}
        architecture = score.get("architecture") or {}
        retrieval = score.get("retrieval") or {}

        gaps: list[str] = []

        if (value := architecture.get("vector_coverage_ratio")) is not None and float(
            value
        ) < thresholds["indexing"]["vector_coverage_ratio"]:
            gaps.append("vector_coverage_ratio")
        if (value := architecture.get("index_freshness_ratio")) is not None and float(
            value
        ) < thresholds["indexing"]["index_freshness_ratio"]:
            gaps.append("index_freshness_ratio")

        if (value := maintainability.get("memory_completeness")) is not None and float(
            value
        ) < thresholds["memory"]["memory_completeness"]:
            gaps.append("memory_completeness")
        if (value := maintainability.get("memory_freshness")) is not None and float(
            value
        ) < thresholds["memory"]["memory_freshness"]:
            gaps.append("memory_freshness")
        if (value := maintainability.get("memory_stale_ratio")) is not None and float(
            value
        ) > thresholds["memory"]["memory_stale_ratio"]:
            gaps.append("memory_stale_ratio")

        if (value := retrieval.get("retrieval_hit_rate")) is not None and float(
            value
        ) < thresholds["retrieval"]["retrieval_hit_rate"]:
            gaps.append("retrieval_hit_rate")
        if (value := retrieval.get("retrieval_mrr")) is not None and float(
            value
        ) < thresholds["retrieval"]["retrieval_mrr"]:
            gaps.append("retrieval_mrr")
        if (value := retrieval.get("grounded_answer_rate")) is not None and float(
            value
        ) < thresholds["retrieval"]["grounded_answer_rate"]:
            gaps.append("grounded_answer_rate")

        return gaps

    def focus_gap_names(
        self,
        focus: str,
        score: dict[str, Any],
        thresholds: dict[str, dict[str, float]],
    ) -> list[str]:
        maintainability = score.get("maintainability") or {}
        architecture = score.get("architecture") or {}
        retrieval = score.get("retrieval") or {}

        if focus == "indexing":
            gaps: list[str] = []
            for signal in ("snapshot_ready", "vector_index_ready", "db_integrity_ok"):
                if architecture.get(signal) is False:
                    gaps.append(signal)
            if (
                (value := architecture.get("vector_coverage_ratio")) is not None
                and float(value) < thresholds["indexing"]["vector_coverage_ratio"]
            ):
                gaps.append("vector_coverage_ratio")
            if (
                (value := architecture.get("index_freshness_ratio")) is not None
                and float(value) < thresholds["indexing"]["index_freshness_ratio"]
            ):
                gaps.append("index_freshness_ratio")
            return gaps

        if focus == "memory":
            boolean_gaps: list[str] = []
            for signal in ("profile_present", "memory_consistency_ok"):
                if maintainability.get(signal) is False:
                    boolean_gaps.append(signal)
            if boolean_gaps:
                return boolean_gaps

            gaps: list[str] = []
            if (
                (value := maintainability.get("memory_completeness")) is not None
                and float(value) < thresholds["memory"]["memory_completeness"]
            ):
                gaps.append("memory_completeness")
            if (
                (value := maintainability.get("memory_freshness")) is not None
                and float(value) < thresholds["memory"]["memory_freshness"]
            ):
                gaps.append("memory_freshness")
            if (
                (value := maintainability.get("memory_stale_ratio")) is not None
                and float(value) > thresholds["memory"]["memory_stale_ratio"]
            ):
                gaps.append("memory_stale_ratio")
            return gaps

        if focus == "retrieval":
            gaps: list[str] = []
            if (
                (value := retrieval.get("retrieval_hit_rate")) is not None
                and float(value) < thresholds["retrieval"]["retrieval_hit_rate"]
            ):
                gaps.append("retrieval_hit_rate")
            if (
                (value := retrieval.get("retrieval_mrr")) is not None
                and float(value) < thresholds["retrieval"]["retrieval_mrr"]
            ):
                gaps.append("retrieval_mrr")
            if (
                (value := retrieval.get("grounded_answer_rate")) is not None
                and float(value) < thresholds["retrieval"]["grounded_answer_rate"]
            ):
                gaps.append("grounded_answer_rate")
            return gaps

        return []

    def recommended_focus(
        self,
        score: dict[str, Any] | None,
        thresholds: dict[str, dict[str, float]],
    ) -> str:
        if not score:
            return "none"

        maintainability = score.get("maintainability") or {}
        architecture = score.get("architecture") or {}

        if (
            maintainability.get("profile_present") is False
            or maintainability.get("memory_consistency_ok") is False
        ):
            return "memory"

        if (
            architecture.get("snapshot_ready") is False
            or architecture.get("vector_index_ready") is False
            or architecture.get("db_integrity_ok") is False
        ):
            return "indexing"

        if (
            (value := architecture.get("vector_coverage_ratio")) is not None
            and float(value) < thresholds["indexing"]["vector_coverage_ratio"]
        ) or (
            (value := architecture.get("index_freshness_ratio")) is not None
            and float(value) < thresholds["indexing"]["index_freshness_ratio"]
        ):
            return "indexing"

        if (
            (
                (value := maintainability.get("memory_completeness")) is not None
                and float(value) < thresholds["memory"]["memory_completeness"]
            )
            or (
                (value := maintainability.get("memory_freshness")) is not None
                and float(value) < thresholds["memory"]["memory_freshness"]
            )
            or (
                (value := maintainability.get("memory_stale_ratio")) is not None
                and float(value) > thresholds["memory"]["memory_stale_ratio"]
            )
        ):
            return "memory"

        retrieval = score.get("retrieval") or {}
        if (
            (
                (value := retrieval.get("retrieval_hit_rate")) is not None
                and float(value) < thresholds["retrieval"]["retrieval_hit_rate"]
            )
            or (
                (value := retrieval.get("retrieval_mrr")) is not None
                and float(value) < thresholds["retrieval"]["retrieval_mrr"]
            )
            or (
                (value := retrieval.get("grounded_answer_rate")) is not None
                and float(value) < thresholds["retrieval"]["grounded_answer_rate"]
            )
        ):
            return "retrieval"

        return "none"

    def needs_optimization(
        self,
        score: dict[str, Any],
        thresholds: dict[str, dict[str, float]],
    ) -> bool:
        return self.recommended_focus(score, thresholds) != "none"

    def architecture_recommendation(
        self,
        score: dict[str, Any] | None,
        thresholds: dict[str, dict[str, float]],
        *,
        focus_override: str | None = None,
    ) -> dict[str, Any] | None:
        focus = focus_override or self.recommended_focus(score, thresholds)
        if focus == "none":
            return None

        score = score or {}
        gap_signals = self.focus_gap_names(focus, score, thresholds)

        if focus == "indexing":
            return {
                "focus": "indexing",
                "variant_type": "method_family",
                "proposal_strategy": "explore_indexing_method_family",
                "hypothesis": "improve indexing coverage and freshness before retrieval tuning",
                "gap_signals": gap_signals,
                "metric_thresholds": thresholds["indexing"],
            }

        if focus == "memory":
            boolean_gap_signals = [
                signal for signal in gap_signals if signal in {"profile_present", "memory_consistency_ok"}
            ]
            hypothesis = (
                "restore profile import and memory consistency before further retrieval optimization"
                if boolean_gap_signals
                else "improve memory completeness and freshness while reducing stale memory interference"
            )
            return {
                "focus": "memory",
                "variant_type": "method_family",
                "proposal_strategy": "explore_memory_method_family",
                "hypothesis": hypothesis,
                "gap_signals": gap_signals,
                "metric_thresholds": thresholds["memory"],
            }

        if focus == "retrieval":
            return {
                "focus": "retrieval",
                "variant_type": "method_family",
                "proposal_strategy": "explore_retrieval_method_family",
                "hypothesis": "improve retrieval hit rate, ranking quality, and grounded answer generation",
                "gap_signals": gap_signals,
                "metric_thresholds": thresholds["retrieval"],
            }

        return None


class ContextAtlasObservationStrategy(ObservationStrategy):
    def needs_optimization(
        self,
        score: dict[str, Any],
        thresholds: dict[str, dict[str, float]],
    ) -> bool:
        maintainability = score.get("maintainability") or {}
        architecture = score.get("architecture") or {}
        has_boolean_gap = any(
            value is False
            for value in (
                maintainability.get("profile_present"),
                maintainability.get("memory_consistency_ok"),
                architecture.get("snapshot_ready"),
                architecture.get("vector_index_ready"),
                architecture.get("db_integrity_ok"),
            )
        )
        return has_boolean_gap or bool(self.metric_gap_names(score, thresholds))


DEFAULT_OBSERVATION_STRATEGY = ObservationStrategy(
    name="default",
    threshold_defaults=DEFAULT_HEADROOM_THRESHOLDS,
)

CONTEXTATLAS_OBSERVATION_STRATEGY = ContextAtlasObservationStrategy(
    name="contextatlas",
    threshold_defaults=DEFAULT_HEADROOM_THRESHOLDS,
)


def resolve_observation_strategy(
    config_root: Path,
    profile_name: str,
    project_name: str,
) -> ObservationStrategy:
    try:
        effective_config = load_effective_config(
            config_root=config_root,
            profile_name=profile_name,
            project_name=project_name,
        )
    except (FileNotFoundError, ValueError):
        effective_config = {}

    contextatlas_config = (
        effective_config.get("contextatlas")
        if isinstance(effective_config, dict)
        else None
    )
    if contextatlas_config:
        return CONTEXTATLAS_OBSERVATION_STRATEGY
    if profile_name.startswith("contextatlas") or project_name.startswith(
        "contextatlas"
    ):
        return CONTEXTATLAS_OBSERVATION_STRATEGY
    return DEFAULT_OBSERVATION_STRATEGY
