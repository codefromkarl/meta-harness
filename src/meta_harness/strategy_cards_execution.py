from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from meta_harness.benchmark_engine import run_benchmark
from meta_harness.candidates import create_candidate
from meta_harness.config_loader import load_effective_config
from meta_harness.schemas import StrategyCard
from meta_harness.strategy_cards_core import (
    _format_compatibility_failure,
    _is_executable,
    _resolve_card_file_reference,
    build_strategy_benchmark_spec,
    evaluate_strategy_card_compatibility,
    load_strategy_card,
    strategy_card_to_benchmark_variant,
)


def strategy_card_to_candidate_payload(
    card: StrategyCard,
    *,
    strategy_card_path: Path | None = None,
) -> dict[str, Any]:
    if not _is_executable(card):
        raise ValueError(
            f"strategy card '{card.strategy_id}' is not executable and cannot become a candidate"
        )

    variant = strategy_card_to_benchmark_variant(card)
    return {
        "config_patch": variant.get("config_patch"),
        "code_patch_path": _resolve_card_file_reference(
            variant["code_patch"],
            strategy_card_path=strategy_card_path,
        )
        if variant.get("code_patch") is not None
        else None,
        "notes": f"external strategy candidate: {card.strategy_id}",
        "proposal": {
            "strategy": "external_strategy_card",
            "strategy_id": card.strategy_id,
            "source": card.source,
            "category": card.category,
            "change_type": card.change_type,
            "variant_type": variant["variant_type"],
            "implementation_id": variant["implementation_id"],
            "hypothesis": variant["hypothesis"],
            "expected_signals": variant.get("expected_signals"),
            "tags": variant.get("tags", []),
        },
    }

def create_candidate_from_strategy_card(
    *,
    config_root: Path,
    candidates_root: Path,
    profile_name: str,
    project_name: str,
    strategy_card_path: Path,
) -> str:
    card = load_strategy_card(strategy_card_path)
    compatibility = evaluate_strategy_card_compatibility(
        card,
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
        strategy_card_path=strategy_card_path,
    )
    if compatibility["status"] == "blocked":
        raise ValueError(_format_compatibility_failure(compatibility))
    payload = strategy_card_to_candidate_payload(
        card,
        strategy_card_path=strategy_card_path,
    )
    return create_candidate(
        candidates_root=candidates_root,
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
        config_patch=payload["config_patch"],
        code_patch_path=payload["code_patch_path"],
        notes=payload["notes"],
        proposal=payload["proposal"],
        reuse_existing=True,
    )

def write_strategy_benchmark_spec(
    *,
    output_path: Path,
    experiment: str,
    baseline_name: str,
    strategy_card_paths: list[Path],
    scenarios: list[dict[str, Any]] | None = None,
    repeats: int = 1,
    template: str = "generic",
) -> dict[str, Any]:
    strategy_cards = [load_strategy_card(path) for path in strategy_card_paths]
    if template != "generic":
        raise ValueError(f"unsupported strategy benchmark template: {template}")
    spec = build_strategy_benchmark_spec(
        experiment=experiment,
        baseline_name=baseline_name,
        strategy_cards=strategy_cards,
        scenarios=scenarios,
        repeats=repeats,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return spec

def run_strategy_benchmark(
    *,
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    profile_name: str,
    project_name: str,
    task_set_path: Path,
    experiment: str,
    baseline_name: str,
    strategy_card_paths: list[Path],
    focus: str | None = None,
    template: str = "generic",
) -> dict[str, Any]:
    cards = [load_strategy_card(path) for path in strategy_card_paths]
    compatibility_reports = [
        evaluate_strategy_card_compatibility(
            card,
            config_root=config_root,
            profile_name=profile_name,
            project_name=project_name,
            strategy_card_path=path,
        )
        for card, path in zip(cards, strategy_card_paths, strict=False)
    ]
    blocked = [report for report in compatibility_reports if report["status"] == "blocked"]
    if blocked:
        raise ValueError(
            "; ".join(_format_compatibility_failure(report) for report in blocked)
        )
    with TemporaryDirectory(prefix="meta-harness-strategy-benchmark-") as temp_dir:
        spec_path = Path(temp_dir) / "benchmark.json"
        write_strategy_benchmark_spec(
            output_path=spec_path,
            experiment=experiment,
            baseline_name=baseline_name,
            strategy_card_paths=strategy_card_paths,
            template=template,
        )
        return run_benchmark(
            config_root=config_root,
            runs_root=runs_root,
            candidates_root=candidates_root,
            profile_name=profile_name,
            project_name=project_name,
            task_set_path=task_set_path,
            spec_path=spec_path,
            focus=focus,
        )
