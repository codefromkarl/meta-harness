from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from meta_harness.strategy_cards_core import (
    build_strategy_benchmark_spec,
    load_strategy_card,
)
from meta_harness.strategy_cards_recommendation import (
    recommend_web_scrape_strategy_cards,
)


def build_web_scrape_audit_report_payload(
    *,
    page_profile: dict[str, Any],
    workload_profile: dict[str, Any],
    config_root: Path,
    strategy_card_paths: list[Path] | None = None,
    limit: int = 4,
    benchmark_report_path: Path | None = None,
) -> dict[str, Any]:
    recommendation = recommend_web_scrape_strategy_cards(
        page_profile=page_profile,
        workload_profile=workload_profile,
        config_root=config_root,
        strategy_card_paths=strategy_card_paths,
        limit=limit,
    )
    benchmark_payload = None
    if benchmark_report_path is not None:
        benchmark_payload = json.loads(benchmark_report_path.read_text(encoding="utf-8"))

    primary = recommendation.get("primary_recommendation")
    benchmark_summary = _web_scrape_benchmark_summary(benchmark_payload)
    alignment = _web_scrape_recommendation_alignment(
        primary_recommendation=primary if isinstance(primary, dict) else None,
        benchmark_summary=benchmark_summary,
    )
    return {
        **recommendation,
        "benchmark_summary": benchmark_summary,
        "alignment": alignment,
        "audit_summary": _web_scrape_audit_summary(
            recommendation=recommendation,
            benchmark_summary=benchmark_summary,
            alignment=alignment,
        ),
    }


def build_web_scrape_audit_benchmark_spec_payload(
    *,
    page_profile: dict[str, Any],
    workload_profile: dict[str, Any],
    config_root: Path,
    output_path: Path,
    baseline_name: str = "current_strategy",
    limit: int = 4,
    repeats: int = 1,
    experiment: str = "web_scrape_audit",
    strategy_card_paths: list[Path] | None = None,
) -> dict[str, Any]:
    recommendation = recommend_web_scrape_strategy_cards(
        page_profile=page_profile,
        workload_profile=workload_profile,
        config_root=config_root,
        strategy_card_paths=strategy_card_paths,
        limit=limit,
    )
    selected_paths = [
        Path(path)
        for path in (
            item.get("strategy_card_path")
            for item in recommendation.get("recommendations", [])
        )
        if isinstance(path, str) and path
    ]
    strategy_cards = [load_strategy_card(path) for path in selected_paths]
    spec = build_strategy_benchmark_spec(
        experiment=experiment,
        baseline_name=baseline_name,
        strategy_cards=strategy_cards,
        repeats=repeats,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return {
        "output_path": str(output_path),
        "strategy_card_paths": [str(path) for path in selected_paths],
        "audit_report": recommendation,
        "benchmark_spec": spec,
    }


def _web_scrape_benchmark_summary(
    benchmark_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(benchmark_payload, dict):
        return None
    report_summary = benchmark_payload.get("report_summary")
    report_summary = report_summary if isinstance(report_summary, dict) else {}
    return {
        "experiment": benchmark_payload.get("experiment"),
        "best_variant": benchmark_payload.get("best_variant"),
        "best_by_quality": benchmark_payload.get("best_by_quality"),
        "best_by_stability": benchmark_payload.get("best_by_stability"),
        "artifact_path": benchmark_payload.get("artifact_path"),
        "report_summary": report_summary,
    }


def _web_scrape_recommendation_alignment(
    *,
    primary_recommendation: dict[str, Any] | None,
    benchmark_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    if primary_recommendation is None:
        return {
            "has_benchmark_evidence": benchmark_summary is not None,
            "recommended_variant": None,
            "benchmark_best_variant": (
                benchmark_summary.get("best_variant") if benchmark_summary else None
            ),
            "aligned": None,
            "summary": "no primary recommendation available",
        }
    recommended_variant = primary_recommendation.get("variant_name")
    benchmark_best_variant = (
        benchmark_summary.get("best_variant") if benchmark_summary else None
    )
    if benchmark_summary is None:
        return {
            "has_benchmark_evidence": False,
            "recommended_variant": recommended_variant,
            "benchmark_best_variant": None,
            "aligned": None,
            "summary": "no benchmark evidence available",
        }
    aligned = recommended_variant == benchmark_best_variant
    return {
        "has_benchmark_evidence": True,
        "recommended_variant": recommended_variant,
        "benchmark_best_variant": benchmark_best_variant,
        "aligned": aligned,
        "summary": (
            "recommendation aligns with benchmark best variant"
            if aligned
            else "recommendation differs from benchmark best variant"
        ),
    }


def _web_scrape_audit_summary(
    *,
    recommendation: dict[str, Any],
    benchmark_summary: dict[str, Any] | None,
    alignment: dict[str, Any],
) -> dict[str, Any]:
    primary = recommendation.get("primary_recommendation")
    return {
        "selected_strategy_id": recommendation.get("selected_strategy_id"),
        "selected_variant_name": (
            primary.get("variant_name") if isinstance(primary, dict) else None
        ),
        "benchmark_best_variant": (
            benchmark_summary.get("best_variant") if benchmark_summary else None
        ),
        "alignment_summary": alignment.get("summary"),
        "recommendation_count": len(recommendation.get("recommendations") or []),
    }
