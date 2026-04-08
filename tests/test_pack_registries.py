from __future__ import annotations

import json
from pathlib import Path

import pytest

from meta_harness.evaluator_pack_registry import (
    list_evaluator_packs,
    load_evaluator_pack,
    load_registered_evaluator_pack,
)
from meta_harness.primitive_registry import (
    list_primitive_packs,
    load_primitive_pack,
    load_registered_primitive_pack,
)
from meta_harness.transfer import load_claw_binding


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_primitive_registry_loads_and_lists_packs(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    primitive_path = config_root / "primitives" / "web_scrape.json"
    write_json(
        primitive_path,
        {
            "primitive_id": "web_scrape",
            "kind": "browser_interaction",
            "proposal_templates": [
                {
                    "template_id": "web_scrape/fast_path",
                    "title": "Fast path",
                    "hypothesis": "Reduce wait time on stable pages",
                    "knobs": {"timeout_ms": 5000},
                }
            ],
        },
    )

    payload = load_primitive_pack(primitive_path).model_dump()
    listing = list_primitive_packs(config_root)
    resolved = load_registered_primitive_pack(config_root, "web_scrape").model_dump()

    assert payload["primitive_id"] == "web_scrape"
    assert listing == ["web_scrape"]
    assert resolved["proposal_templates"][0]["template_id"] == "web_scrape/fast_path"


def test_evaluator_pack_registry_loads_and_lists_packs(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    pack_path = config_root / "evaluator_packs" / "web_scrape_core.json"
    write_json(
        pack_path,
        {
            "pack_id": "web_scrape/core",
            "supported_primitives": ["web_scrape"],
            "command": ["python", "scripts/eval_web_scrape.py"],
        },
    )

    payload = load_evaluator_pack(pack_path).model_dump()
    listing = list_evaluator_packs(config_root)
    resolved = load_registered_evaluator_pack(config_root, "web_scrape/core").model_dump()

    assert payload["pack_id"] == "web_scrape/core"
    assert listing == ["web_scrape/core"]
    assert resolved["supported_primitives"] == ["web_scrape"]


def test_registered_pack_lookup_raises_for_missing_pack(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"

    with pytest.raises(FileNotFoundError, match="missing_primitive"):
        load_registered_primitive_pack(config_root, "missing_primitive")

    with pytest.raises(FileNotFoundError, match="missing/pack"):
        load_registered_evaluator_pack(config_root, "missing/pack")


def test_repository_pack_assets_exist() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    primitive = load_primitive_pack(
        repo_root / "configs" / "primitives" / "web_scrape.json"
    )
    evaluator = load_evaluator_pack(
        repo_root / "configs" / "evaluator_packs" / "web_scrape_core.json"
    )
    web_binding = load_claw_binding(
        repo_root / "configs",
        "bridge/web_scrape",
    )
    analysis_binding = load_claw_binding(
        repo_root / "configs",
        "bridge/data_analysis",
    )

    assert primitive.primitive_id == "web_scrape"
    assert primitive.evaluation_contract.artifact_requirements == [
        "page.html",
        "extracted.json",
    ]
    assert primitive.proposal_templates[0].template_id == "web_scrape/fast_path"
    assert evaluator.pack_id == "web_scrape/core"
    assert evaluator.supported_primitives == ["web_scrape"]
    assert web_binding.adapter_kind == "json_agent_cli"
    assert web_binding.execution["bridge_contract"] == "primitive_output"
    assert analysis_binding.primitive_id == "data_analysis"
