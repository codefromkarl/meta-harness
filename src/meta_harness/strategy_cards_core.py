from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from meta_harness.config_loader import load_effective_config
from meta_harness.schemas import StrategyCard


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

def load_strategy_cards_from_directory(directory: Path) -> list[StrategyCard]:
    if not directory.exists():
        return []
    return [
        load_strategy_card(path)
        for path in sorted(path for path in directory.glob("*.json") if path.is_file())
    ]

def load_web_scrape_strategy_cards(config_root: Path = Path("configs")) -> list[StrategyCard]:
    return load_strategy_cards_from_directory(config_root / "strategy_cards" / "web_scrape")

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

