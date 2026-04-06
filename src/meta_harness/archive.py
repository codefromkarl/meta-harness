from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from meta_harness.schemas import RunMetadata


def initialize_run(
    runs_root: Path,
    profile_name: str,
    project_name: str,
    effective_config: dict,
    candidate_id: str | None = None,
    run_id: str | None = None,
) -> str:
    run_id = run_id or uuid4().hex[:12]
    run_dir = runs_root / run_id

    (run_dir / "tasks").mkdir(parents=True, exist_ok=False)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=False)

    metadata = RunMetadata(
        run_id=run_id,
        profile=profile_name,
        project=project_name,
        candidate_id=candidate_id,
    )

    (run_dir / "run_metadata.json").write_text(
        metadata.model_dump_json(indent=2),
        encoding="utf-8",
    )
    (run_dir / "effective_config.json").write_text(
        json.dumps(effective_config, indent=2),
        encoding="utf-8",
    )

    return run_id


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_run_record(runs_root: Path, run_id: str) -> dict:
    run_dir = runs_root / run_id
    metadata = _read_json(run_dir / "run_metadata.json")
    effective_config = _read_json(run_dir / "effective_config.json")
    score = None
    score_path = run_dir / "score_report.json"
    if score_path.exists():
        score = _read_json(score_path)

    return {
        "run_id": run_id,
        "profile": metadata["profile"],
        "project": metadata["project"],
        "candidate_id": metadata.get("candidate_id"),
        "created_at": metadata.get("created_at"),
        "config": effective_config,
        "score": score,
    }


def list_run_records(runs_root: Path) -> list[dict]:
    if not runs_root.exists():
        return []

    records: list[dict] = []
    for run_dir in sorted(path for path in runs_root.iterdir() if path.is_dir()):
        metadata_path = run_dir / "run_metadata.json"
        effective_config_path = run_dir / "effective_config.json"
        if not metadata_path.exists() or not effective_config_path.exists():
            continue
        records.append(load_run_record(runs_root, run_dir.name))
    return records


def diff_run_records(runs_root: Path, left_run_id: str, right_run_id: str) -> dict:
    left = load_run_record(runs_root, left_run_id)
    right = load_run_record(runs_root, right_run_id)

    left_score = left.get("score") or {}
    right_score = right.get("score") or {}

    return {
        "left_run_id": left_run_id,
        "right_run_id": right_run_id,
        "score_delta": {
            "composite": right_score.get("composite", 0.0) - left_score.get("composite", 0.0),
        },
        "profile_changed": left["profile"] != right["profile"],
        "project_changed": left["project"] != right["project"],
    }
