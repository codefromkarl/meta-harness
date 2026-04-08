from __future__ import annotations

from pathlib import Path

from meta_harness.strategy_cards import (
    load_web_scrape_strategy_cards,
    recommend_web_scrape_strategy_cards,
)


def test_load_web_scrape_strategy_cards_from_repo_assets() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    cards = load_web_scrape_strategy_cards(repo_root / "configs")

    assert {card.strategy_id for card in cards} >= {
        "web_scrape/html-to-markdown-llm",
        "web_scrape/selector-only",
        "web_scrape/vlm-visual-extract",
        "web_scrape/headless-fingerprint-proxy",
    }


def test_recommend_web_scrape_strategy_cards_prefers_markdown_for_low_complexity_ad_hoc() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    payload = recommend_web_scrape_strategy_cards(
        config_root=repo_root / "configs",
        page_profile={
            "complexity": "low",
            "requires_rendering": False,
            "requires_interaction": False,
            "anti_bot_level": "low",
            "media_dependency": "low",
        },
        workload_profile={
            "usage_mode": "ad_hoc",
        },
    )

    assert payload["selected_strategy_id"] == "web_scrape/html-to-markdown-llm"


def test_recommend_web_scrape_strategy_cards_prefers_selector_for_low_complexity_recurring() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    payload = recommend_web_scrape_strategy_cards(
        config_root=repo_root / "configs",
        page_profile={
            "complexity": "low",
            "requires_rendering": False,
            "anti_bot_level": "low",
        },
        workload_profile={
            "usage_mode": "recurring",
            "batch_size": 100,
            "latency_sla_ms": 3000,
        },
    )

    assert payload["selected_strategy_id"] == "web_scrape/selector-only"


def test_recommend_web_scrape_strategy_cards_prefers_visual_for_high_complexity_ad_hoc() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    payload = recommend_web_scrape_strategy_cards(
        config_root=repo_root / "configs",
        page_profile={
            "complexity": "high",
            "requires_rendering": True,
            "anti_bot_level": "high",
            "media_dependency": "high",
        },
        workload_profile={
            "usage_mode": "ad_hoc",
        },
    )

    assert payload["selected_strategy_id"] == "web_scrape/vlm-visual-extract"


def test_recommend_web_scrape_strategy_cards_prefers_headless_for_high_complexity_recurring() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    payload = recommend_web_scrape_strategy_cards(
        config_root=repo_root / "configs",
        page_profile={
            "complexity": "high",
            "requires_rendering": True,
            "requires_interaction": True,
            "anti_bot_level": "high",
        },
        workload_profile={
            "usage_mode": "recurring",
            "batch_size": 200,
            "freshness_requirement": "high",
        },
    )

    assert payload["selected_strategy_id"] == "web_scrape/headless-fingerprint-proxy"
