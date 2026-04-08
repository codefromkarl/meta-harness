from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from meta_harness.datasets import (
    build_dataset_from_task_set,
    build_dataset_promotion_target,
    derive_dataset_split,
    extract_failure_dataset,
    ingest_annotations_into_dataset,
    write_dataset_artifact,
)


def extract_failure_dataset_to_path(
    *,
    runs_root: Path,
    output_path: Path,
    profile_name: str | None = None,
    project_name: str | None = None,
) -> dict[str, Any]:
    payload = extract_failure_dataset(
        runs_root,
        profile_name=profile_name,
        project_name=project_name,
    )
    write_dataset_artifact(output_path, payload)
    return {
        "output_path": str(output_path),
        "dataset_id": payload["dataset_id"],
        "case_count": payload["case_count"],
    }


def build_task_set_dataset_to_path(
    *,
    task_set_path: Path,
    output_path: Path,
    dataset_id: str,
    version: str = "v1",
) -> dict[str, Any]:
    payload = build_dataset_from_task_set(
        task_set_path,
        dataset_id=dataset_id,
        version=version,
    )
    write_dataset_artifact(output_path, payload)
    return {
        "output_path": str(output_path),
        "dataset_id": payload["dataset_id"],
        "version": payload["version"],
        "case_count": payload["case_count"],
    }


def ingest_dataset_annotations_to_path(
    *,
    dataset_path: Path,
    annotations_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    payload = ingest_annotations_into_dataset(
        dataset_path,
        annotations_path=annotations_path,
        output_version=output_path.parent.name or None,
    )
    write_dataset_artifact(output_path, payload)
    return {
        "output_path": str(output_path),
        "dataset_id": payload["dataset_id"],
        "version": payload["version"],
        "case_count": payload["case_count"],
        "annotation_count": payload.get("annotation_count", 0),
    }


def derive_dataset_split_to_path(
    *,
    dataset_path: Path,
    output_path: Path,
    split: str,
    dataset_id: str,
    version: str,
) -> dict[str, Any]:
    payload = derive_dataset_split(
        dataset_path,
        split=split,
        dataset_id=dataset_id,
        version=version,
    )
    write_dataset_artifact(output_path, payload)
    return {
        "output_path": str(output_path),
        "dataset_id": payload["dataset_id"],
        "version": payload["version"],
        "case_count": payload["case_count"],
        "split": payload.get("split"),
    }


def promote_dataset_version(
    *,
    datasets_root: Path,
    dataset_id: str,
    version: str,
    promoted_by: str | None = None,
    reason: str | None = None,
    split: str | None = None,
) -> dict[str, Any]:
    dataset_path = datasets_root / dataset_id / version / "dataset.json"
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    resolved_split = split if split is not None else payload.get("split")
    promotion_key = f"{dataset_id}:{resolved_split or 'default'}"

    promotions_path = datasets_root / "promotions.json"
    promotions = (
        json.loads(promotions_path.read_text(encoding="utf-8"))
        if promotions_path.exists()
        else {}
    )
    promotions[promotion_key] = version
    promotions_path.write_text(json.dumps(promotions, indent=2), encoding="utf-8")

    record = {
        "dataset_id": dataset_id,
        "version": version,
        "split": resolved_split,
        "promoted_by": promoted_by,
        "promotion_reason": reason or "",
        "dataset_path": str(dataset_path),
    }
    records_path = datasets_root / "promotion_records.json"
    records = (
        json.loads(records_path.read_text(encoding="utf-8"))
        if records_path.exists()
        else {}
    )
    records[promotion_key] = record
    records_path.write_text(json.dumps(records, indent=2), encoding="utf-8")

    promotion_target = build_dataset_promotion_target(
        dataset_path,
        promoted_by=promoted_by,
        reason=reason,
        split=resolved_split,
    )
    promotion_target_path = dataset_path.parent / "promotion_target.json"
    promotion_target_path.write_text(
        json.dumps(promotion_target, indent=2), encoding="utf-8"
    )
    return {
        "dataset_id": dataset_id,
        "version": version,
        "promotion_key": promotion_key,
        "promotion_record": record,
        "promotion_target_path": str(promotion_target_path),
    }


def list_dataset_versions(datasets_root: Path) -> list[dict[str, Any]]:
    if not datasets_root.exists():
        return []
    items: list[dict[str, Any]] = []
    for dataset_dir in sorted(path for path in datasets_root.iterdir() if path.is_dir()):
        for version_dir in sorted(path for path in dataset_dir.iterdir() if path.is_dir()):
            dataset_path = version_dir / "dataset.json"
            if not dataset_path.exists():
                continue
            payload = json.loads(dataset_path.read_text(encoding="utf-8"))
            items.append(
                {
                    "dataset_id": str(payload.get("dataset_id", dataset_dir.name)),
                    "version": str(payload.get("version", version_dir.name)),
                    "case_count": int(payload.get("case_count", 0) or 0),
                    "schema_version": payload.get("schema_version"),
                    "path": str(dataset_path),
                }
            )
    return items


def load_dataset_summary(datasets_root: Path, dataset_id: str) -> dict[str, Any]:
    versions = [
        item for item in list_dataset_versions(datasets_root) if item["dataset_id"] == dataset_id
    ]
    if not versions:
        raise FileNotFoundError(f"dataset '{dataset_id}' not found")
    return {
        "dataset_id": dataset_id,
        "versions": [str(item["version"]) for item in versions],
        "latest_version": str(versions[-1]["version"]),
    }


def load_dataset_version(
    datasets_root: Path,
    dataset_id: str,
    version: str,
) -> dict[str, Any]:
    path = datasets_root / dataset_id / version / "dataset.json"
    if not path.exists():
        raise FileNotFoundError(
            f"dataset version '{dataset_id}/{version}' not found"
        )
    return json.loads(path.read_text(encoding="utf-8"))
