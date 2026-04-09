from __future__ import annotations

import json
from pathlib import Path

from meta_harness.candidates import (
    backfill_candidate_lineage,
    create_candidate,
    load_candidate_record,
)


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


def test_create_candidate_persists_lineage_metadata(tmp_path: Path) -> None:
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

    candidate_id = create_candidate(
        candidates_root=candidates_root,
        config_root=config_root,
        profile_name="base",
        project_name="demo",
        notes="lineage candidate",
        proposal_id="proposal-1",
        iteration_id="loop-1-0001",
        source_run_ids=["run-1", "run-2"],
        source_artifacts=["proposals/proposal-1/proposal.json", "reports/loops/loop-1"],
    )

    record = load_candidate_record(candidates_root, candidate_id)

    assert record["proposal_id"] == "proposal-1"
    assert record["source_proposal_ids"] == ["proposal-1"]
    assert record["iteration_id"] == "loop-1-0001"
    assert record["source_iteration_ids"] == ["loop-1-0001"]
    assert record["source_run_ids"] == ["run-1", "run-2"]
    assert record["source_artifacts"] == [
        "proposals/proposal-1/proposal.json",
        "reports/loops/loop-1",
    ]


def test_create_candidate_reuse_existing_backfills_lineage_metadata(tmp_path: Path) -> None:
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

    original_id = create_candidate(
        candidates_root=candidates_root,
        config_root=config_root,
        profile_name="base",
        project_name="demo",
        notes="baseline candidate",
    )
    reused_id = create_candidate(
        candidates_root=candidates_root,
        config_root=config_root,
        profile_name="base",
        project_name="demo",
        notes="baseline candidate",
        proposal_id="proposal-2",
        iteration_id="loop-2-0001",
        source_run_ids=["run-2"],
        source_artifacts=["proposals/proposal-2/proposal.json"],
        reuse_existing=True,
    )

    record = json.loads(
        (candidates_root / reused_id / "candidate.json").read_text(encoding="utf-8")
    )

    assert reused_id == original_id
    assert record["proposal_id"] == "proposal-2"
    assert record["source_proposal_ids"] == ["proposal-2"]
    assert record["iteration_id"] == "loop-2-0001"
    assert record["source_iteration_ids"] == ["loop-2-0001"]
    assert record["source_run_ids"] == ["run-2"]
    assert record["source_artifacts"] == ["proposals/proposal-2/proposal.json"]


def test_create_candidate_reuse_existing_accumulates_source_iteration_ids(tmp_path: Path) -> None:
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
        notes="lineage candidate",
        proposal_id="proposal-1",
        iteration_id="loop-1-0001",
        reuse_existing=True,
    )
    reused_id = create_candidate(
        candidates_root=candidates_root,
        config_root=config_root,
        profile_name="base",
        project_name="demo",
        notes="lineage candidate",
        proposal_id="proposal-1",
        iteration_id="loop-1-0002",
        reuse_existing=True,
    )

    record = load_candidate_record(candidates_root, reused_id)

    assert reused_id == first_id
    assert record["iteration_id"] == "loop-1-0001"
    assert record["source_proposal_ids"] == ["proposal-1"]
    assert record["source_iteration_ids"] == ["loop-1-0001", "loop-1-0002"]


def test_create_candidate_reuse_existing_accumulates_source_proposal_ids(tmp_path: Path) -> None:
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
        notes="proposal lineage candidate",
        proposal_id="proposal-1",
        reuse_existing=True,
    )
    reused_id = create_candidate(
        candidates_root=candidates_root,
        config_root=config_root,
        profile_name="base",
        project_name="demo",
        notes="proposal lineage candidate",
        proposal_id="proposal-2",
        reuse_existing=True,
    )

    record = load_candidate_record(candidates_root, reused_id)

    assert reused_id == first_id
    assert record["proposal_id"] == "proposal-1"
    assert record["source_proposal_ids"] == ["proposal-1", "proposal-2"]


def test_create_candidate_reuse_existing_accumulates_source_run_ids(tmp_path: Path) -> None:
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
        notes="run lineage candidate",
        source_run_ids=["run-1"],
        reuse_existing=True,
    )
    reused_id = create_candidate(
        candidates_root=candidates_root,
        config_root=config_root,
        profile_name="base",
        project_name="demo",
        notes="run lineage candidate",
        source_run_ids=["run-2"],
        reuse_existing=True,
    )

    record = load_candidate_record(candidates_root, reused_id)

    assert reused_id == first_id
    assert record["source_run_ids"] == ["run-1", "run-2"]


def test_create_candidate_reuse_existing_accumulates_source_artifacts(tmp_path: Path) -> None:
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
        notes="artifact lineage candidate",
        source_artifacts=["reports/loops/loop-1/iteration.json"],
        reuse_existing=True,
    )
    reused_id = create_candidate(
        candidates_root=candidates_root,
        config_root=config_root,
        profile_name="base",
        project_name="demo",
        notes="artifact lineage candidate",
        source_artifacts=["reports/loops/loop-1/proposal_output.json"],
        reuse_existing=True,
    )

    record = load_candidate_record(candidates_root, reused_id)

    assert reused_id == first_id
    assert record["source_artifacts"] == [
        "reports/loops/loop-1/iteration.json",
        "reports/loops/loop-1/proposal_output.json",
    ]
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


def test_create_candidate_persists_canonical_lineage_envelope(tmp_path: Path) -> None:
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

    candidate_id = create_candidate(
        candidates_root=candidates_root,
        config_root=config_root,
        profile_name="base",
        project_name="demo",
        notes="canonical lineage candidate",
        parent_candidate_id="cand-parent",
        proposal_id="proposal-1",
        iteration_id="iter-1",
        source_run_ids=["run-1"],
        source_artifacts=["proposals/proposal-1/proposal.json"],
    )

    record = load_candidate_record(candidates_root, candidate_id)

    assert record["lineage"] == {
        "parent_candidate_id": "cand-parent",
        "proposal_id": "proposal-1",
        "source_proposal_ids": ["proposal-1"],
        "iteration_id": "iter-1",
        "source_iteration_ids": ["iter-1"],
        "source_run_ids": ["run-1"],
        "source_artifacts": ["proposals/proposal-1/proposal.json"],
    }


def test_create_candidate_reuse_existing_keeps_lineage_envelope_in_sync(tmp_path: Path) -> None:
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
        notes="canonical lineage candidate",
        proposal_id="proposal-1",
        iteration_id="iter-1",
        source_run_ids=["run-1"],
        source_artifacts=["reports/loops/loop-1/iteration.json"],
        reuse_existing=True,
    )
    reused_id = create_candidate(
        candidates_root=candidates_root,
        config_root=config_root,
        profile_name="base",
        project_name="demo",
        notes="canonical lineage candidate",
        proposal_id="proposal-2",
        iteration_id="iter-2",
        source_run_ids=["run-2"],
        source_artifacts=["reports/loops/loop-2/iteration.json"],
        reuse_existing=True,
    )

    record = load_candidate_record(candidates_root, reused_id)

    assert reused_id == first_id
    assert record["lineage"]["source_proposal_ids"] == ["proposal-1", "proposal-2"]
    assert record["lineage"]["source_iteration_ids"] == ["iter-1", "iter-2"]
    assert record["lineage"]["source_run_ids"] == ["run-1", "run-2"]
    assert record["lineage"]["source_artifacts"] == [
        "reports/loops/loop-1/iteration.json",
        "reports/loops/loop-2/iteration.json",
    ]


def test_backfill_candidate_lineage_keeps_canonical_lineage_envelope_in_sync(
    tmp_path: Path,
) -> None:
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

    candidate_id = create_candidate(
        candidates_root=candidates_root,
        config_root=config_root,
        profile_name="base",
        project_name="demo",
        notes="canonical lineage candidate",
        proposal_id="proposal-1",
        iteration_id="iter-1",
        source_run_ids=["run-1"],
        source_artifacts=["reports/loops/loop-1/iteration.json"],
    )

    backfill_candidate_lineage(
        candidates_root=candidates_root,
        candidate_id=candidate_id,
        proposal_id="proposal-2",
        iteration_id="iter-2",
        source_run_ids=["run-2"],
        source_artifacts=["reports/loops/loop-2/iteration.json"],
    )

    record = json.loads(
        (candidates_root / candidate_id / "candidate.json").read_text(encoding="utf-8")
    )

    assert record["lineage"]["source_proposal_ids"] == ["proposal-1", "proposal-2"]
    assert record["lineage"]["source_iteration_ids"] == ["iter-1", "iter-2"]
    assert record["lineage"]["source_run_ids"] == ["run-1", "run-2"]
    assert record["lineage"]["source_artifacts"] == [
        "reports/loops/loop-1/iteration.json",
        "reports/loops/loop-2/iteration.json",
    ]
