from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meta_harness.config_loader import load_effective_config

DEFAULT_HEADROOM_THRESHOLDS: dict[str, dict[str, float]] = {
    "binding": {
        "binding_execution_rate": 0.9,
        "method_trace_coverage_rate": 0.85,
        "binding_payload_rate": 0.9,
        "assistant_reply_rate": 0.85,
        "artifact_coverage_rate": 0.85,
    },
    "workflow": {
        "hot_path_success_rate": 0.9,
        "fallback_rate": 0.15,
    },
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
        workflow = score.get("workflow_scores") or {}
        maintainability = score.get("maintainability") or {}
        architecture = score.get("architecture") or {}
        retrieval = score.get("retrieval") or {}
        capability_scores = score.get("capability_scores") or {}
        transfer_capability = (
            self._recommended_transfer_capability(score)
            if isinstance(capability_scores, dict)
            else {}
        )

        gaps: list[str] = []

        if (
            (value := workflow.get("binding_execution_rate")) is not None
            and float(value) < thresholds["binding"]["binding_execution_rate"]
        ):
            gaps.append("binding_execution_rate")
        if (
            (value := workflow.get("method_trace_coverage_rate")) is not None
            and float(value) < thresholds["binding"]["method_trace_coverage_rate"]
        ):
            gaps.append("method_trace_coverage_rate")
        if (
            (value := transfer_capability.get("binding_payload_rate")) is not None
            and float(value) < thresholds["binding"]["binding_payload_rate"]
        ):
            gaps.append("binding_payload_rate")
        if (
            (value := transfer_capability.get("assistant_reply_rate")) is not None
            and float(value) < thresholds["binding"]["assistant_reply_rate"]
        ):
            gaps.append("assistant_reply_rate")
        if (
            (value := transfer_capability.get("artifact_coverage_rate")) is not None
            and float(value) < thresholds["binding"]["artifact_coverage_rate"]
        ):
            gaps.append("artifact_coverage_rate")

        if (value := workflow.get("hot_path_success_rate")) is not None and float(
            value
        ) < thresholds["workflow"]["hot_path_success_rate"]:
            gaps.append("hot_path_success_rate")
        if (value := workflow.get("fallback_rate")) is not None and float(
            value
        ) > thresholds["workflow"]["fallback_rate"]:
            gaps.append("fallback_rate")

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
        workflow = score.get("workflow_scores") or {}
        maintainability = score.get("maintainability") or {}
        architecture = score.get("architecture") or {}
        retrieval = score.get("retrieval") or {}
        capability_scores = score.get("capability_scores") or {}
        transfer_capability = (
            self._recommended_transfer_capability(score)
            if isinstance(capability_scores, dict)
            else {}
        )

        if focus == "binding":
            gaps: list[str] = []
            if (
                (value := workflow.get("binding_execution_rate")) is not None
                and float(value) < thresholds["binding"]["binding_execution_rate"]
            ):
                gaps.append("binding_execution_rate")
            if (
                (value := workflow.get("method_trace_coverage_rate")) is not None
                and float(value) < thresholds["binding"]["method_trace_coverage_rate"]
            ):
                gaps.append("method_trace_coverage_rate")
            if (
                (value := transfer_capability.get("binding_payload_rate")) is not None
                and float(value) < thresholds["binding"]["binding_payload_rate"]
            ):
                gaps.append("binding_payload_rate")
            if (
                (value := transfer_capability.get("assistant_reply_rate")) is not None
                and float(value) < thresholds["binding"]["assistant_reply_rate"]
            ):
                gaps.append("assistant_reply_rate")
            if (
                (value := transfer_capability.get("artifact_coverage_rate")) is not None
                and float(value) < thresholds["binding"]["artifact_coverage_rate"]
            ):
                gaps.append("artifact_coverage_rate")
            return gaps

        if focus == "workflow":
            gaps: list[str] = []
            if (
                (value := workflow.get("hot_path_success_rate")) is not None
                and float(value) < thresholds["workflow"]["hot_path_success_rate"]
            ):
                gaps.append("hot_path_success_rate")
            if (
                (value := workflow.get("fallback_rate")) is not None
                and float(value) > thresholds["workflow"]["fallback_rate"]
            ):
                gaps.append("fallback_rate")
            return gaps

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

        workflow = score.get("workflow_scores") or {}
        maintainability = score.get("maintainability") or {}
        architecture = score.get("architecture") or {}
        transfer_capability = self._recommended_transfer_capability(score)

        if (
            (
                (value := workflow.get("binding_execution_rate")) is not None
                and float(value) < thresholds["binding"]["binding_execution_rate"]
            )
            or (
                (value := workflow.get("method_trace_coverage_rate")) is not None
                and float(value) < thresholds["binding"]["method_trace_coverage_rate"]
            )
            or (
                (value := transfer_capability.get("binding_payload_rate")) is not None
                and float(value) < thresholds["binding"]["binding_payload_rate"]
            )
            or (
                (value := transfer_capability.get("assistant_reply_rate")) is not None
                and float(value) < thresholds["binding"]["assistant_reply_rate"]
            )
            or (
                (value := transfer_capability.get("artifact_coverage_rate")) is not None
                and float(value) < thresholds["binding"]["artifact_coverage_rate"]
            )
        ):
            return "binding"

        if (
            (
                (value := workflow.get("hot_path_success_rate")) is not None
                and float(value) < thresholds["workflow"]["hot_path_success_rate"]
            )
            or (
                (value := workflow.get("fallback_rate")) is not None
                and float(value) > thresholds["workflow"]["fallback_rate"]
            )
        ):
            return "workflow"

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

        if focus == "workflow":
            primitive_id = self._recommended_workflow_primitive(score)
            return {
                "focus": "workflow",
                **({"primitive_id": primitive_id} if primitive_id else {}),
                "variant_type": "method_family",
                "proposal_strategy": "explore_workflow_method_family",
                "hypothesis": "improve hot path success rate while reducing fallback reliance across workflow steps",
                "gap_signals": gap_signals,
                "metric_thresholds": thresholds["workflow"],
            }

        if focus == "binding":
            primitive_id = self._recommended_workflow_primitive(score)
            return {
                "focus": "binding",
                **({"primitive_id": primitive_id} if primitive_id else {}),
                "variant_type": "method_family",
                "proposal_strategy": "explore_binding_patch",
                "hypothesis": "improve binding execution fidelity so transferred task methods preserve payloads, assistant replies, and trace coverage across claws",
                "gap_signals": gap_signals,
                "metric_thresholds": thresholds["binding"],
            }

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

    def _recommended_workflow_primitive(
        self,
        score: dict[str, Any],
    ) -> str | None:
        capability_scores = score.get("capability_scores") or {}
        if not isinstance(capability_scores, dict) or not capability_scores:
            return None

        def sort_key(item: tuple[str, Any]) -> tuple[float, float, str]:
            primitive_id, payload = item
            metrics = payload if isinstance(payload, dict) else {}
            success_rate = metrics.get("success_rate")
            latency_ms = metrics.get("latency_ms")
            normalized_success = (
                float(success_rate) if isinstance(success_rate, (int, float)) else 1.0
            )
            normalized_latency = (
                -float(latency_ms) if isinstance(latency_ms, (int, float)) else 0.0
            )
            return (normalized_success, normalized_latency, primitive_id)

        return sorted(capability_scores.items(), key=sort_key)[0][0]

    def _recommended_transfer_capability(
        self,
        score: dict[str, Any],
    ) -> dict[str, Any]:
        capability_scores = score.get("capability_scores") or {}
        if not isinstance(capability_scores, dict):
            return {}

        def has_transfer_metrics(payload: Any) -> bool:
            if not isinstance(payload, dict):
                return False
            return any(
                key in payload
                for key in (
                    "binding_payload_rate",
                    "assistant_reply_rate",
                    "artifact_coverage_rate",
                )
            )

        transfer_candidates = [
            payload for payload in capability_scores.values() if has_transfer_metrics(payload)
        ]
        if not transfer_candidates:
            return {}
        ranked = sorted(
            transfer_candidates,
            key=lambda payload: (
                float(payload.get("binding_payload_rate", 1.0)),
                float(payload.get("assistant_reply_rate", 1.0)),
                float(payload.get("artifact_coverage_rate", 1.0)),
            ),
        )
        selected = ranked[0]
        return selected if isinstance(selected, dict) else {}


DEFAULT_OBSERVATION_STRATEGY = ObservationStrategy(
    name="default",
    threshold_defaults=DEFAULT_HEADROOM_THRESHOLDS,
)


def resolve_observation_strategy(
    config_root: Path,
    profile_name: str,
    project_name: str,
) -> ObservationStrategy:
    return DEFAULT_OBSERVATION_STRATEGY
