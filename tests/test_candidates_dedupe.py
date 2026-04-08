from __future__ import annotations

import json
from pathlib import Path

from meta_harness.candidates import create_candidate


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_create_candidate_reuses_equivalent_automated_candidate(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {"retrieval": {"top_k": 8}}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )

    first_id = create_candidate(
        candidates_root=candidates_root,
        config_root=config_root,
        profile_name="base",
        project_name="demo",
        config_patch={"retrieval": {"top_k": 12}},
        notes="benchmark candidate",
        proposal={"strategy": "benchmark_variant", "experiment": "demo", "variant": "wide"},
        reuse_existing=True,
    )
    second_id = create_candidate(
        candidates_root=candidates_root,
        config_root=config_root,
        profile_name="base",
        project_name="demo",
        config_patch={"retrieval": {"top_k": 12}},
        notes="same semantics, different note",
        proposal={"strategy": "benchmark_variant", "experiment": "demo", "variant": "wide"},
        reuse_existing=True,
    )

    assert second_id == first_id
    candidate_dirs = [path for path in candidates_root.iterdir() if path.is_dir()]
    assert len(candidate_dirs) == 1


def test_create_candidate_keeps_manual_creations_distinct_by_default(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {"retrieval": {"top_k": 8}}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )

    first_id = create_candidate(
        candidates_root=candidates_root,
        config_root=config_root,
        profile_name="base",
        project_name="demo",
        config_patch={"retrieval": {"top_k": 12}},
        notes="manual candidate one",
        proposal={"strategy": "manual_exploration"},
    )
    second_id = create_candidate(
        candidates_root=candidates_root,
        config_root=config_root,
        profile_name="base",
        project_name="demo",
        config_patch={"retrieval": {"top_k": 12}},
        notes="manual candidate two",
        proposal={"strategy": "manual_exploration"},
    )

    assert second_id != first_id
    candidate_dirs = [path for path in candidates_root.iterdir() if path.is_dir()]
    assert len(candidate_dirs) == 2
