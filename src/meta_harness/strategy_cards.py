from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from meta_harness.benchmark import run_benchmark
from meta_harness.candidates import create_candidate
from meta_harness.config_loader import load_effective_config
from meta_harness.schemas import StrategyCard


_CONTEXTATLAS_INDEXING_SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "exact_symbol_lookup",
        "label": "Exact Symbol Lookup",
        "weight": 1.0,
    },
    {
        "id": "cross_file_dependency_trace",
        "label": "Cross File Dependency Trace",
        "weight": 1.0,
    },
    {
        "id": "index_freshness_sensitive",
        "label": "Index Freshness Sensitive",
        "weight": 1.2,
    },
    {
        "id": "recent_change_discovery",
        "label": "Recent Change Discovery",
        "weight": 1.2,
    },
    {
        "id": "stale_index_recovery",
        "label": "Stale Index Recovery",
        "weight": 1.1,
    },
    {
        "id": "large_repo_retrieval",
        "label": "Large Repo Retrieval",
        "weight": 0.9,
    },
]


def load_strategy_card(path: Path) -> StrategyCard:
    return StrategyCard.model_validate_json(path.read_text(encoding="utf-8"))


def evaluate_strategy_card_compatibility(
    card: StrategyCard,
    *,
    config_root: Path,
    profile_name: str,
    project_name: str,
    strategy_card_path: Path | None = None,
) -> dict[str, Any]:
    effective_config = load_effective_config(
        config_root=config_root,
        profile_name=profile_name,
        project_name=project_name,
    )
    compatibility = card.compatibility if isinstance(card.compatibility, dict) else {}
    required_runtime_keys = compatibility.get("required_runtime_keys") or []
    required_paths = compatibility.get("required_paths") or []
    review_required = bool(compatibility.get("review_required", False))

    missing_runtime_keys = [
        str(key)
        for key in required_runtime_keys
        if _lookup_nested_value(effective_config, str(key)) is None
    ]

    source_repo_value = _lookup_nested_value(
        effective_config, "runtime.workspace.source_repo"
    )
    source_repo = (
        Path(str(source_repo_value)).expanduser().resolve()
        if isinstance(source_repo_value, str) and source_repo_value
        else None
    )
    missing_paths: list[str] = []
    for required_path in required_paths:
        required = str(required_path)
        if source_repo is None or not (source_repo / required).exists():
            missing_paths.append(required)

    missing_artifacts: list[str] = []
    if card.code_patch is not None:
        resolved_patch = _resolve_card_file_reference(
            card.code_patch,
            strategy_card_path=strategy_card_path,
        )
        if not resolved_patch.exists():
            missing_artifacts.append(str(card.code_patch))

    executable = _is_executable(card)
    if not executable or missing_runtime_keys or missing_paths or missing_artifacts:
        status = "blocked"
    elif review_required:
        status = "review_required"
    else:
        status = "executable"

    return {
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
        "status": status,
        "change_type": card.change_type,
        "source": card.source,
        "can_benchmark": status != "blocked",
        "can_create_candidate": status != "blocked",
        "review_required": review_required,
        "missing_runtime_keys": missing_runtime_keys,
        "missing_paths": missing_paths,
        "missing_artifacts": missing_artifacts,
        "source_repo": str(source_repo) if source_repo is not None else None,
    }


def shortlist_strategy_cards(
    *,
    strategy_card_paths: list[Path],
    config_root: Path,
    profile_name: str,
    project_name: str,
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {
        "executable": [],
        "review_required": [],
        "blocked": [],
    }

    for path in strategy_card_paths:
        card = load_strategy_card(path)
        report = evaluate_strategy_card_compatibility(
            card,
            config_root=config_root,
            profile_name=profile_name,
            project_name=project_name,
            strategy_card_path=path,
        )
        groups[report["status"]].append(report)

    for items in groups.values():
        items.sort(
            key=lambda item: (
                int(item.get("priority", 100)),
                str(item.get("group") or ""),
                str(item.get("strategy_id") or ""),
            )
        )

    return {
        "summary": {
            "total": sum(len(items) for items in groups.values()),
            "executable": len(groups["executable"]),
            "review_required": len(groups["review_required"]),
            "blocked": len(groups["blocked"]),
        },
        "groups": groups,
    }


def strategy_card_to_benchmark_variant(card: StrategyCard) -> dict[str, Any]:
    if not _is_executable(card):
        raise ValueError(
            f"strategy card '{card.strategy_id}' is not executable and cannot be benchmarked"
        )

    strategy_metadata: dict[str, Any] = {
        "source": card.source,
        "category": card.category,
        "change_type": card.change_type,
        "compatibility": card.compatibility,
        "expected_benefits": card.expected_benefits,
        "expected_costs": card.expected_costs,
        "risk_notes": card.risk_notes,
    }
    if card.primitive_id:
        strategy_metadata["primitive_id"] = card.primitive_id
    if isinstance(card.capability_metadata, dict) and card.capability_metadata:
        strategy_metadata["capability_metadata"] = dict(card.capability_metadata)

    variant: dict[str, Any] = {
        "name": card.variant_name or _default_variant_name(card.strategy_id),
        "variant_type": card.variant_type or _default_variant_type(card.change_type),
        "hypothesis": card.hypothesis or card.title,
        "implementation_id": card.implementation_id or card.strategy_id,
        "tags": _dedupe_tags(
            [
                "external-strategy",
                card.category,
                card.change_type,
                card.primitive_id,
                *card.tags,
            ]
        ),
        "strategy_metadata": strategy_metadata,
    }
    if card.config_patch is not None:
        variant["config_patch"] = card.config_patch
    if card.code_patch is not None:
        variant["code_patch"] = card.code_patch
    if card.expected_signals is not None:
        variant["expected_signals"] = card.expected_signals
    return variant


def build_strategy_benchmark_spec(
    *,
    experiment: str,
    baseline_name: str,
    strategy_cards: list[StrategyCard],
    scenarios: list[dict[str, Any]] | None = None,
    repeats: int = 1,
) -> dict[str, Any]:
    variants: list[dict[str, Any]] = [
        {
            "name": baseline_name,
            "variant_type": "parameter",
            "tags": ["baseline", "current-strategy"],
        }
    ]
    variants.extend(
        strategy_card_to_benchmark_variant(card)
        for card in strategy_cards
        if _is_executable(card)
    )

    return {
        "experiment": experiment,
        "baseline": baseline_name,
        "analysis_mode": "architecture",
        "repeats": repeats,
        "report": {
            "group_by": ["scenario", "variant_type"],
            "primary_axes": ["quality", "mechanism", "stability", "cost"],
        },
        "scenarios": scenarios or [],
        "variants": variants,
    }


def build_contextatlas_indexing_strategy_benchmark_spec(
    *,
    strategy_cards: list[StrategyCard],
    experiment: str = "contextatlas_external_indexing_strategies",
    baseline_name: str = "current_indexing",
) -> dict[str, Any]:
    spec = build_strategy_benchmark_spec(
        experiment=experiment,
        baseline_name=baseline_name,
        strategy_cards=strategy_cards,
        scenarios=_CONTEXTATLAS_INDEXING_SCENARIOS,
        repeats=3,
    )
    spec["report"] = {
        "group_by": ["scenario", "variant_type"],
        "primary_axes": ["quality", "mechanism", "stability", "cost"],
        "recommended_task_set": "task_sets/contextatlas/benchmark_indexing_architecture_v2.json",
        "notes": [
            "snapshot-based",
            "external-strategy-comparison",
        ],
    }
    return spec

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
    if template == "contextatlas_indexing_v2":
        spec = build_contextatlas_indexing_strategy_benchmark_spec(
            strategy_cards=strategy_cards,
            experiment=experiment,
            baseline_name=baseline_name,
        )
    else:
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


def _is_executable(card: StrategyCard) -> bool:
    return card.config_patch is not None or card.code_patch is not None


def _default_variant_name(strategy_id: str) -> str:
    return strategy_id.replace("/", "_")


def _default_variant_type(change_type: str) -> str:
    if change_type == "patch_based":
        return "implementation_patch"
    return "parameter"


def _dedupe_tags(tags: list[str]) -> list[str]:
    unique: list[str] = []
    for tag in tags:
        if tag and tag not in unique:
            unique.append(tag)
    return unique


def _lookup_nested_value(payload: dict[str, Any], dotted_key: str) -> Any:
    current: Any = payload
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _resolve_card_file_reference(
    raw_path: str,
    *,
    strategy_card_path: Path | None,
) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute() and strategy_card_path is not None:
        candidate = (strategy_card_path.parent / candidate).resolve()
    return candidate.resolve()


def _format_compatibility_failure(report: dict[str, Any]) -> str:
    parts = [f"strategy card '{report['strategy_id']}' blocked"]
    if report.get("missing_runtime_keys"):
        parts.append(
            "missing runtime keys: "
            + ", ".join(str(item) for item in report["missing_runtime_keys"])
        )
    if report.get("missing_paths"):
        parts.append(
            "missing paths: "
            + ", ".join(str(item) for item in report["missing_paths"])
        )
    if report.get("missing_artifacts"):
        parts.append(
            "missing artifacts: "
            + ", ".join(str(item) for item in report["missing_artifacts"])
        )
    return "; ".join(parts)
