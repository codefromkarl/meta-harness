from __future__ import annotations

from pathlib import Path
from typing import Any

from meta_harness.schemas import StrategyCard
from meta_harness.strategy_cards_core import (
    _default_variant_name,
    _is_executable,
    _lookup_nested_value,
    evaluate_strategy_card_compatibility,
    load_strategy_card,
)


def recommend_web_scrape_strategy_cards(
    *,
    page_profile: dict[str, Any],
    workload_profile: dict[str, Any],
    strategy_card_paths: list[Path] | None = None,
    config_root: Path = Path("configs"),
    limit: int = 4,
) -> dict[str, Any]:
    resolved_strategy_card_paths = (
        list(strategy_card_paths)
        if strategy_card_paths is not None
        else sorted(
            path
            for path in (config_root / "strategy_cards" / "web_scrape").glob("*.json")
            if path.is_file()
        )
    )
    strategy_cards = [load_strategy_card(path) for path in resolved_strategy_card_paths]
    scored: list[dict[str, Any]] = []
    for index, card in enumerate(strategy_cards):
        strategy_card_path = (
            resolved_strategy_card_paths[index]
            if index < len(resolved_strategy_card_paths)
            else None
        )
        try:
            compatibility = evaluate_strategy_card_compatibility(
                card,
                config_root=config_root,
                profile_name=str(page_profile.get("profile_name", "base")),
                project_name=str(workload_profile.get("project_name", "web_scrape")),
                strategy_card_path=strategy_card_path,
            )
        except FileNotFoundError:
            compatibility = {
                "strategy_id": card.strategy_id,
                "title": card.title,
                "category": card.category,
                **({"primitive_id": card.primitive_id} if card.primitive_id else {}),
                **(
                    {"capability_metadata": dict(card.capability_metadata)}
                    if isinstance(card.capability_metadata, dict) and card.capability_metadata
                    else {}
                ),
                "group": card.group,
                "priority": int(card.priority),
                "status": "executable" if _is_executable(card) else "blocked",
                "change_type": card.change_type,
                "source": card.source,
                "can_benchmark": _is_executable(card),
                "can_create_candidate": _is_executable(card),
                "review_required": False,
                "missing_runtime_keys": [],
                "missing_paths": [],
                "missing_artifacts": [],
                "source_repo": None,
            }
        score, reasons = _score_web_scrape_strategy_card(
            card,
            page_profile=page_profile,
            workload_profile=workload_profile,
        )
        scored.append(
            {
                **compatibility,
                "variant_name": card.variant_name or _default_variant_name(card.strategy_id),
                "expected_benefits": list(card.expected_benefits),
                "expected_costs": list(card.expected_costs),
                "risk_notes": list(card.risk_notes),
                "expected_signals": (
                    dict(card.expected_signals)
                    if isinstance(card.expected_signals, dict)
                    else None
                ),
                "strategy_card_path": (
                    str(strategy_card_path) if strategy_card_path is not None else None
                ),
                "tags": list(card.tags),
                "recommendation_score": score,
                "recommendation_reasons": reasons,
            }
        )

    scored.sort(
        key=lambda item: (
            -float(item.get("recommendation_score", 0.0)),
            int(item.get("priority", 100)),
            str(item.get("strategy_id") or ""),
        )
    )
    recommendations = scored[: max(limit, 0)]
    assessment = _build_web_scrape_assessment(
        page_profile=page_profile,
        workload_profile=workload_profile,
    )
    primary_recommendation = (
        _build_web_scrape_recommendation_summary(recommendations[0], assessment=assessment)
        if recommendations
        else None
    )
    alternatives = [
        _build_web_scrape_recommendation_summary(item, assessment=assessment)
        for item in recommendations[1:]
    ]
    return {
        "page_profile": page_profile,
        "workload_profile": workload_profile,
        "assessment": assessment,
        "selected_strategy_id": (
            str(recommendations[0]["strategy_id"]) if recommendations else None
        ),
        "primary_recommendation": primary_recommendation,
        "alternatives": alternatives,
        "recommendations": recommendations,
    }

def _build_web_scrape_assessment(
    *,
    page_profile: dict[str, Any],
    workload_profile: dict[str, Any],
) -> dict[str, Any]:
    page_bucket = _normalize_web_scrape_page_bucket(page_profile)
    workload_bucket = _normalize_web_scrape_workload_bucket(workload_profile)
    render_required = bool(
        _lookup_nested_value(page_profile, "render_required")
        or _lookup_nested_value(page_profile, "requires_rendering")
    )
    interaction_required = bool(
        _lookup_nested_value(page_profile, "interaction_required")
        or _lookup_nested_value(page_profile, "requires_interaction")
    )
    anti_bot_level = str(_lookup_nested_value(page_profile, "anti_bot_level") or "unknown")
    media_dependency = str(_lookup_nested_value(page_profile, "media_dependency") or "unknown")
    batch_size = _lookup_nested_value(workload_profile, "batch_size")
    latency_sla_ms = _lookup_nested_value(workload_profile, "latency_sla_ms")
    budget_mode = str(_lookup_nested_value(workload_profile, "budget_mode") or "balanced")

    summary_lines = [
        f"page complexity classified as {page_bucket}",
        f"workload mode classified as {workload_bucket}",
    ]
    if render_required:
        summary_lines.append("rendered content is likely required")
    if interaction_required:
        summary_lines.append("interactive flow is likely required")
    if anti_bot_level != "unknown":
        summary_lines.append(f"anti-bot level appears {anti_bot_level}")
    if media_dependency not in {"unknown", "low", "false", "0"}:
        summary_lines.append(f"media dependency appears {media_dependency}")
    if isinstance(batch_size, (int, float)):
        summary_lines.append(f"batch size target is {int(batch_size)}")
    if isinstance(latency_sla_ms, (int, float)):
        summary_lines.append(f"latency SLA target is {int(latency_sla_ms)} ms")
    summary_lines.append(f"budget mode is {budget_mode}")

    return {
        "page_bucket": page_bucket,
        "workload_bucket": workload_bucket,
        "render_required": render_required,
        "interaction_required": interaction_required,
        "anti_bot_level": anti_bot_level,
        "media_dependency": media_dependency,
        "batch_size": batch_size,
        "latency_sla_ms": latency_sla_ms,
        "budget_mode": budget_mode,
        "summary": summary_lines,
    }

def _build_web_scrape_recommendation_summary(
    recommendation: dict[str, Any],
    *,
    assessment: dict[str, Any],
) -> dict[str, Any]:
    recommendation_reasons = recommendation.get("recommendation_reasons") or []
    expected_benefits = recommendation.get("expected_benefits") or []
    expected_costs = recommendation.get("expected_costs") or []
    risk_notes = recommendation.get("risk_notes") or []
    rationale = list(recommendation_reasons)
    if assessment["page_bucket"] == "high" and "visual" in set(recommendation.get("tags") or []):
        rationale.append("high-complexity page justifies higher-cost visual extraction")
    if assessment["workload_bucket"] == "recurring" and "selector" in set(recommendation.get("tags") or []):
        rationale.append("recurring workload rewards low-variance extraction paths")
    if assessment["workload_bucket"] == "recurring" and "proxy" in set(recommendation.get("tags") or []):
        rationale.append("recurring workload benefits from hardened automation infrastructure")
    return {
        "strategy_id": recommendation.get("strategy_id"),
        "title": recommendation.get("title"),
        "variant_name": recommendation.get("variant_name"),
        "strategy_card_path": recommendation.get("strategy_card_path"),
        "recommendation_score": recommendation.get("recommendation_score"),
        "rationale": rationale,
        "expected_benefits": expected_benefits,
        "expected_costs": expected_costs,
        "risk_notes": risk_notes,
        "expected_signals": recommendation.get("expected_signals"),
        "status": recommendation.get("status"),
    }

def _score_web_scrape_strategy_card(
    card: StrategyCard,
    *,
    page_profile: dict[str, Any],
    workload_profile: dict[str, Any],
) -> tuple[float, list[str]]:
    metadata = card.capability_metadata if isinstance(card.capability_metadata, dict) else {}
    card_page_profile = metadata.get("page_profile")
    card_workload_profile = metadata.get("workload_profile")
    score = 0.0
    reasons: list[str] = []

    page_bucket = _normalize_web_scrape_page_bucket(page_profile)
    workload_bucket = _normalize_web_scrape_workload_bucket(workload_profile)

    expected_page_bucket = _normalize_web_scrape_bucket(
        card_page_profile.get("complexity") if isinstance(card_page_profile, dict) else None
    )
    expected_workload_bucket = _normalize_web_scrape_bucket(
        card_workload_profile.get("mode") if isinstance(card_workload_profile, dict) else None
    )

    if expected_page_bucket is not None:
        if expected_page_bucket == page_bucket:
            score += 4.0
            reasons.append(f"page complexity matches {expected_page_bucket}")
        else:
            score -= 2.0
            reasons.append(
                f"page complexity prefers {expected_page_bucket} but observed {page_bucket}"
            )

    if expected_workload_bucket is not None:
        if expected_workload_bucket == workload_bucket:
            score += 4.0
            reasons.append(f"workload mode matches {expected_workload_bucket}")
        else:
            score -= 2.0
            reasons.append(
                f"workload mode prefers {expected_workload_bucket} but observed {workload_bucket}"
            )

    tags = set(card.tags)
    if page_bucket == "high":
        if tags.intersection({"visual", "headless"}):
            score += 1.5
            reasons.append("high-complexity page favors visual/headless handling")
    else:
        if tags.intersection({"markdown", "selector"}):
            score += 1.5
            reasons.append("low-complexity page favors markdown/selector handling")

    if workload_bucket == "recurring":
        if tags.intersection({"selector", "headless", "proxy"}):
            score += 1.0
            reasons.append("recurring workload favors stable automation")
    else:
        if tags.intersection({"markdown", "visual"}):
            score += 1.0
            reasons.append("ad hoc workload favors quick-turn extraction")

    if bool(
        _lookup_nested_value(page_profile, "render_required")
        or _lookup_nested_value(page_profile, "requires_rendering")
    ):
        if tags.intersection({"headless", "visual"}):
            score += 1.0
            reasons.append("render-required page favors rendered extraction")
        else:
            score -= 1.0
            reasons.append("render-required page disfavors non-rendered extraction")

    media_dependency = _lookup_nested_value(page_profile, "media_dependency")
    if (
        bool(media_dependency)
        and str(media_dependency).strip().lower() not in {"low", "false", "0", ""}
    ):
        if tags.intersection({"visual"}):
            score += 1.0
            reasons.append("media-dependent page favors visual extraction")

    return score, reasons

def _normalize_web_scrape_page_bucket(profile: dict[str, Any]) -> str:
    complexity = _normalize_web_scrape_bucket(
        _lookup_nested_value(profile, "content_complexity")
        or _lookup_nested_value(profile, "complexity")
    )
    if complexity is not None:
        return complexity
    if bool(
        _lookup_nested_value(profile, "render_required")
        or _lookup_nested_value(profile, "requires_rendering")
    ):
        return "high"
    if bool(
        _lookup_nested_value(profile, "interaction_required")
        or _lookup_nested_value(profile, "requires_interaction")
    ):
        return "high"
    if _normalize_web_scrape_bucket(_lookup_nested_value(profile, "anti_bot_level")) == "high":
        return "high"
    media_dependency = _lookup_nested_value(profile, "media_dependency")
    if (
        bool(media_dependency)
        and str(media_dependency).strip().lower() not in {"low", "false", "0", ""}
    ):
        return "high"
    return "low"

def _normalize_web_scrape_workload_bucket(profile: dict[str, Any]) -> str:
    workload_mode = _normalize_web_scrape_bucket(
        _lookup_nested_value(profile, "usage_mode")
        or _lookup_nested_value(profile, "mode")
    )
    if workload_mode is not None:
        return workload_mode
    if _lookup_nested_value(profile, "batch_size") is not None:
        batch_size = _lookup_nested_value(profile, "batch_size")
        if isinstance(batch_size, (int, float)) and float(batch_size) > 1:
            return "recurring"
    return "ad_hoc"

def _normalize_web_scrape_bucket(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"low", "static", "simple", "ad_hoc", "adhoc", "single"}:
        return "low" if text in {"low", "static", "simple"} else "ad_hoc"
    if text in {"high", "dynamic", "complex"}:
        return "high"
    if text in {"recurring", "repeat", "batch"}:
        return "recurring"
    if text in {"selector_only", "selector", "markdown", "html_to_markdown_llm", "vlm_visual_extract", "headless_fingerprint_proxy"}:
        return text
    return text
