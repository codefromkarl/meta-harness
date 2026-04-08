from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meta_harness.archive import load_run_record
from meta_harness.failure_index import load_or_extract_failure_signatures
from meta_harness.schemas import AnnotationRecord, DatasetCase, DatasetVersion


def _stable_case_id(
    *,
    source_type: str,
    run_id: str,
    task_id: str,
    phase: str,
    step_id: str | None = None,
) -> str:
    if source_type == "task_set":
        return f"task_set:{task_id}"
    suffix = f":{step_id}" if step_id else ""
    return f"{source_type}:{run_id}:{task_id}:{phase}{suffix}"


def _default_version_from_output_path(output_path: Path, fallback: str) -> str:
    parent_name = output_path.parent.name
    return parent_name if parent_name else fallback


def _dataset_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "dataset_id": payload["dataset_id"],
        "version": payload["version"],
        "schema_version": payload["schema_version"],
        "case_count": payload["case_count"],
        "annotation_count": payload.get("annotation_count", 0),
        "split": payload.get("split"),
        "source_dataset": payload.get("source_dataset"),
        "source_summary": payload.get("source_summary"),
        "created_at": payload.get("created_at"),
        "created_by": payload.get("created_by"),
        "frozen": payload.get("frozen", True),
    }


def write_dataset_artifact(output_path: Path, payload: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (output_path.parent / "manifest.json").write_text(
        json.dumps(_dataset_manifest(payload), indent=2),
        encoding="utf-8",
    )


def _load_dataset(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _load_annotation_records(path: Path) -> list[AnnotationRecord]:
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []

    items: list[Any]
    if path.suffix == ".jsonl":
        items = [json.loads(line) for line in raw.splitlines() if line.strip()]
    else:
        parsed = json.loads(raw)
        items = parsed if isinstance(parsed, list) else [parsed]

    records: list[AnnotationRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        records.append(AnnotationRecord.model_validate(item))
    return records


def _annotation_targets(case: dict[str, Any]) -> set[str]:
    targets = set()
    if case.get("case_id"):
        targets.add(str(case["case_id"]))
    if case.get("task_id"):
        targets.add(str(case["task_id"]))
    return targets


def _annotation_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value) > 0
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return value is not None


def ingest_annotations_into_dataset(
    dataset_path: Path,
    *,
    annotations_path: Path,
    output_version: str | None = None,
) -> dict[str, Any]:
    dataset = _load_dataset(dataset_path)
    annotations = _load_annotation_records(annotations_path)
    cases = dataset.get("cases")
    if not isinstance(cases, list):
        cases = []

    enriched_cases: list[dict[str, Any]] = []
    annotation_count = 0
    for case in cases:
        if not isinstance(case, dict):
            continue
        matched: list[AnnotationRecord] = []
        labels = set(str(item) for item in (case.get("labels") or []) if str(item))
        targets = _annotation_targets(case)
        for annotation in annotations:
            if annotation.target_type != "dataset_case":
                continue
            if annotation.target_ref not in targets:
                continue
            matched.append(annotation)
            annotation_count += 1
            if _annotation_truthy(annotation.value):
                labels.add(annotation.label)

        enriched_case = dict(case)
        enriched_case["annotations"] = [
            annotation.model_dump(mode="json") for annotation in matched
        ]
        enriched_case["labels"] = sorted(labels)
        enriched_cases.append(enriched_case)

    version = (
        output_version
        if output_version is not None
        else str(dataset.get("version") or "v1")
    )
    return DatasetVersion(
        dataset_id=str(dataset.get("dataset_id", "")),
        version=version,
        schema_version=str(dataset.get("schema_version", "2026-04-06")),
        case_count=len(enriched_cases),
        cases=[DatasetCase.model_validate(case) for case in enriched_cases],
        source_dataset={
            "dataset_id": dataset.get("dataset_id"),
            "version": dataset.get("version"),
            "path": str(dataset_path),
        },
        source_summary={"operation": "annotation_ingestion"},
        annotation_count=annotation_count,
        created_at=datetime.now(UTC),
        frozen=True,
        split=dataset.get("split"),
    ).model_dump(mode="json")


def derive_dataset_split(
    dataset_path: Path,
    *,
    split: str,
    dataset_id: str,
    version: str,
) -> dict[str, Any]:
    dataset = _load_dataset(dataset_path)
    cases = dataset.get("cases")
    if not isinstance(cases, list):
        cases = []
    selected_cases: list[DatasetCase] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        labels = {str(item) for item in (case.get("labels") or []) if str(item)}
        if split not in labels:
            continue
        selected_cases.append(DatasetCase.model_validate(case))

    return DatasetVersion(
        dataset_id=dataset_id,
        version=version,
        schema_version=str(dataset.get("schema_version", "2026-04-06")),
        case_count=len(selected_cases),
        cases=selected_cases,
        split=split,
        source_dataset={
            "dataset_id": dataset.get("dataset_id"),
            "version": dataset.get("version"),
            "path": str(dataset_path),
        },
        source_summary={"operation": "derive_split", "split": split},
        annotation_count=sum(len(case.annotations or []) for case in selected_cases),
        created_at=datetime.now(UTC),
        frozen=True,
    ).model_dump(mode="json")


def build_dataset_promotion_target(
    dataset_path: Path,
    *,
    promoted_by: str | None,
    reason: str | None,
    split: str | None,
) -> dict[str, Any]:
    dataset = _load_dataset(dataset_path)
    case_count = int(dataset.get("case_count", 0) or 0)
    annotation_count = int(dataset.get("annotation_count", 0) or 0)
    return {
        "dataset": {
            "dataset_id": dataset.get("dataset_id"),
            "version": dataset.get("version"),
            "split": split if split is not None else dataset.get("split"),
        },
        "promoted_by": promoted_by,
        "promotion_reason": reason or "",
        "promotion_summary": {
            "case_count": case_count,
            "annotation_count": annotation_count,
            "has_annotations": annotation_count > 0,
        },
    }


def extract_failure_dataset(
    runs_root: Path,
    *,
    profile_name: str | None = None,
    project_name: str | None = None,
) -> dict[str, Any]:
    cases: list[DatasetCase] = []
    if not runs_root.exists():
        return DatasetVersion(
            dataset_id="failure-signatures",
            version="v1",
            schema_version="2026-04-06",
            case_count=0,
            cases=cases,
        ).model_dump()

    for run_dir in sorted(path for path in runs_root.iterdir() if path.is_dir()):
        if not (run_dir / "run_metadata.json").exists():
            continue
        if not (run_dir / "effective_config.json").exists():
            continue
        record = load_run_record(runs_root, run_dir.name)
        if profile_name is not None and record["profile"] != profile_name:
            continue
        if project_name is not None and record["project"] != project_name:
            continue
        for failure in load_or_extract_failure_signatures(run_dir):
            cases.append(
                DatasetCase(
                    case_id=_stable_case_id(
                        source_type="failure_signature",
                        run_id=record["run_id"],
                        task_id=failure["task_id"],
                        phase=failure["phase"],
                        step_id=failure.get("step_id"),
                    ),
                    source_type="failure_signature",
                    run_id=record["run_id"],
                    profile=record["profile"],
                    project=record["project"],
                    task_id=failure["task_id"],
                    phase=failure["phase"],
                    step_id=failure["step_id"],
                    raw_error=failure["raw_error"],
                    failure_signature=failure["signature"],
                )
            )

    return DatasetVersion(
        dataset_id="failure-signatures",
        version="v1",
        schema_version="2026-04-06",
        case_count=len(cases),
        cases=cases,
        source_summary={
            "operation": "extract_failures",
            "profile": profile_name,
            "project": project_name,
        },
        created_at=datetime.now(UTC),
    ).model_dump(mode="json")


def build_dataset_from_task_set(
    task_set_path: Path,
    *,
    dataset_id: str,
    version: str = "v1",
) -> dict[str, Any]:
    payload = json.loads(task_set_path.read_text(encoding="utf-8"))
    cases: list[DatasetCase] = []
    for task in payload.get("tasks", []):
        if not isinstance(task, dict):
            continue
        phases = task.get("phases") or []
        dataset_case = (
            task.get("dataset_case") if isinstance(task.get("dataset_case"), dict) else {}
        )
        phase_names = [
            str(phase.get("phase"))
            for phase in phases
            if isinstance(phase, dict) and phase.get("phase") is not None
        ]
        cases.append(
            DatasetCase(
                case_id=_stable_case_id(
                    source_type="task_set",
                    run_id="task-set",
                    task_id=str(task.get("task_id", "")),
                    phase=phase_names[0] if phase_names else "unknown",
                ),
                source_type="task_set",
                run_id="task-set",
                profile="task-set",
                project="task-set",
                task_id=str(task.get("task_id", "")),
                phase=phase_names[0] if phase_names else "unknown",
                raw_error="",
                failure_signature="",
                scenario=(
                    str(task["scenario"]) if task.get("scenario") is not None else None
                ),
                difficulty=(
                    str(task["difficulty"])
                    if task.get("difficulty") is not None
                    else None
                ),
                weight=(
                    float(task["weight"]) if task.get("weight") is not None else None
                ),
                expectations=(
                    task.get("expectations")
                    if isinstance(task.get("expectations"), dict)
                    else None
                ),
                phase_names=phase_names,
                query=(
                    str(dataset_case["query"])
                    if dataset_case.get("query") is not None
                    else None
                ),
                expected_paths=(
                    [str(item) for item in dataset_case.get("expected_paths", [])]
                    if isinstance(dataset_case.get("expected_paths"), list)
                    else None
                ),
                expected_rank_max=(
                    int(dataset_case["expected_rank_max"])
                    if dataset_case.get("expected_rank_max") is not None
                    else None
                ),
                expected_grounding_refs=(
                    [str(item) for item in dataset_case.get("expected_grounding_refs", [])]
                    if isinstance(dataset_case.get("expected_grounding_refs"), list)
                    else None
                ),
                expected_answer_contains=(
                    [str(item) for item in dataset_case.get("expected_answer_contains", [])]
                    if isinstance(dataset_case.get("expected_answer_contains"), list)
                    else None
                ),
            )
        )

    return DatasetVersion(
        dataset_id=dataset_id,
        version=version,
        schema_version="2026-04-06",
        case_count=len(cases),
        cases=cases,
        source_summary={"operation": "build_task_set", "task_set_path": str(task_set_path)},
        created_at=datetime.now(UTC),
    ).model_dump(mode="json")
