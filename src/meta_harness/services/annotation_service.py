from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def _annotations_root(root: Path) -> Path:
    return root / "annotations"


def create_annotation_record(
    *,
    annotations_root: Path,
    target_type: str,
    target_ref: str,
    label: str,
    value: str,
    notes: str | None = None,
    annotator: str | None = None,
) -> dict[str, Any]:
    annotation = {
        "annotation_id": uuid4().hex[:12],
        "target_type": target_type,
        "target_ref": target_ref,
        "label": label,
        "value": value,
        "notes": notes or "",
        "annotator": annotator,
        "created_at": datetime.now(UTC).isoformat(),
    }
    path = _annotations_root(annotations_root) / f"{annotation['annotation_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(annotation, indent=2), encoding="utf-8")
    return annotation


def list_annotation_records(
    *,
    annotations_root: Path,
    target_type: str | None = None,
    target_ref: str | None = None,
    label: str | None = None,
    annotator: str | None = None,
) -> list[dict[str, Any]]:
    root = _annotations_root(annotations_root)
    if not root.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if target_type is not None and payload.get("target_type") != target_type:
            continue
        if target_ref is not None and payload.get("target_ref") != target_ref:
            continue
        if label is not None and payload.get("label") != label:
            continue
        if annotator is not None and payload.get("annotator") != annotator:
            continue
        items.append(payload)
    return items
