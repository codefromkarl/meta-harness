from __future__ import annotations

from pathlib import Path
from typing import Any

from meta_harness.services.benchmark_service import persist_benchmark_payload
from meta_harness.services.strategy_service_audit import (
    build_web_scrape_audit_benchmark_spec_payload,
    build_web_scrape_audit_report_payload,
)
from meta_harness.strategy_cards_core import (
    evaluate_strategy_card_compatibility,
    load_strategy_card,
    shortlist_strategy_cards,
)
from meta_harness.strategy_cards_execution import (
    create_candidate_from_strategy_card,
    run_strategy_benchmark as _run_strategy_benchmark_impl,
    write_strategy_benchmark_spec,
)
from meta_harness.strategy_cards_recommendation import (
    recommend_web_scrape_strategy_cards,
)


def run_strategy_benchmark(*args, **kwargs):
    return _run_strategy_benchmark_impl(*args, **kwargs)


def build_strategy_benchmark_spec_payload(
    *,
    strategy_card_paths: list[Path],
    experiment: str,
    baseline_name: str,
    output_path: Path,
    repeats: int = 1,
    template: str = "generic",
) -> dict[str, Any]:
    return write_strategy_benchmark_spec(
        output_path=output_path,
        experiment=experiment,
        baseline_name=baseline_name,
        strategy_card_paths=strategy_card_paths,
        repeats=repeats,
        template=template,
    )


def create_candidate_from_strategy_card_payload(
    *,
    strategy_card_path: Path,
    profile_name: str,
    project_name: str,
    config_root: Path,
    candidates_root: Path,
) -> dict[str, Any]:
    candidate_id = create_candidate_from_strategy_card(
        config_root=config_root,
        candidates_root=candidates_root,
        profile_name=profile_name,
        project_name=project_name,
        strategy_card_path=strategy_card_path,
    )
    return {"candidate_id": candidate_id}


def run_strategy_benchmark_payload(
    *,
    strategy_card_paths: list[Path],
    profile_name: str,
    project_name: str,
    task_set_path: Path,
    experiment: str,
    baseline_name: str,
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    reports_root: Path = Path("reports"),
    focus: str | None = None,
    template: str = "generic",
) -> dict[str, Any]:
    payload = run_strategy_benchmark(
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        profile_name=profile_name,
        project_name=project_name,
        task_set_path=task_set_path,
        experiment=experiment,
        baseline_name=baseline_name,
        strategy_card_paths=strategy_card_paths,
        focus=focus,
        template=template,
    )
    return persist_benchmark_payload(reports_root=reports_root, payload=payload)


def inspect_strategy_card_payload(
    *,
    strategy_card_path: Path,
    profile_name: str,
    project_name: str,
    config_root: Path,
) -> dict[str, Any]:
    return evaluate_strategy_card_compatibility(
        load_strategy_card(strategy_card_path),
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
        strategy_card_path=strategy_card_path,
    )


def shortlist_strategy_cards_payload(
    *,
    strategy_card_paths: list[Path],
    profile_name: str,
    project_name: str,
    config_root: Path,
) -> dict[str, Any]:
    return shortlist_strategy_cards(
        strategy_card_paths=strategy_card_paths,
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
    )


def recommend_web_scrape_strategy_cards_payload(
    *,
    page_profile: dict[str, Any],
    workload_profile: dict[str, Any],
    config_root: Path,
    strategy_card_paths: list[Path] | None = None,
    limit: int = 4,
) -> dict[str, Any]:
    return recommend_web_scrape_strategy_cards(
        page_profile=page_profile,
        workload_profile=workload_profile,
        strategy_card_paths=strategy_card_paths,
        config_root=config_root,
        limit=limit,
    )


__all__ = [
    "build_strategy_benchmark_spec_payload",
    "build_web_scrape_audit_benchmark_spec_payload",
    "build_web_scrape_audit_report_payload",
    "create_candidate_from_strategy_card_payload",
    "inspect_strategy_card_payload",
    "recommend_web_scrape_strategy_cards_payload",
    "run_strategy_benchmark",
    "run_strategy_benchmark_payload",
    "shortlist_strategy_cards_payload",
]
