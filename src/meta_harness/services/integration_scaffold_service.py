from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from meta_harness.adapter_scaffolder import (
    build_harness_scaffold_plan,
    build_scaffold_plan,
    materialize_harness_scaffold,
    materialize_scaffold,
)
from meta_harness.config_loader import merge_dicts
from meta_harness.integration_schemas import HarnessSpec, IntegrationReviewResult, IntegrationSpec
from meta_harness.integration_review import (
    build_activation_record,
    build_review_result,
    render_review_checklist_markdown,
)


def scaffold_integration_payload(
    *,
    config_root: Path,
    spec_path: Path,
) -> dict[str, Any]:
    spec = IntegrationSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))
    repo_root = config_root.parent
    plan = build_scaffold_plan(spec)
    scaffold_paths = materialize_scaffold(
        spec=spec,
        plan=plan,
        repo_root=repo_root,
    )
    report_dir = spec_path.parent
    scaffold_plan_path = report_dir / "scaffold_plan.json"
    scaffold_result_path = report_dir / "scaffold_result.json"
    scaffold_plan_path.write_text(json.dumps(plan.model_dump(), indent=2), encoding="utf-8")
    payload = {
        "spec_id": spec.spec_id,
        "binding_id": plan.generated_binding_id,
        "binding_path": scaffold_paths["binding_path"],
        "wrapper_path": scaffold_paths["wrapper_path"],
        "test_path": scaffold_paths["test_path"],
        "scaffold_plan_path": str(scaffold_plan_path),
        "scaffold_result_path": str(scaffold_result_path),
    }
    scaffold_result_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload

def scaffold_harness_payload(
    *,
    config_root: Path,
    harness_spec_path: Path,
) -> dict[str, Any]:
    spec = HarnessSpec.model_validate_json(harness_spec_path.read_text(encoding="utf-8"))
    repo_root = config_root.parent
    plan = build_harness_scaffold_plan(spec)
    scaffold_paths = materialize_harness_scaffold(
        spec=spec,
        plan=plan,
        repo_root=repo_root,
    )
    report_dir = harness_spec_path.parent
    scaffold_plan_path = report_dir / "harness_scaffold_plan.json"
    scaffold_result_path = report_dir / "harness_scaffold_result.json"
    scaffold_plan_path.write_text(json.dumps(plan.model_dump(), indent=2), encoding="utf-8")
    payload = {
        "spec_id": spec.spec_id,
        "binding_id": None,
        "binding_path": None,
        "wrapper_path": scaffold_paths["wrapper_path"],
        "test_path": scaffold_paths["test_path"],
        "scaffold_plan_path": str(scaffold_plan_path),
        "scaffold_result_path": str(scaffold_result_path),
    }
    scaffold_result_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload

def review_integration_payload(
    *,
    config_root: Path,
    spec_path: Path,
    reviewer: str,
    approve_checks: list[str] | None = None,
    approve_all_checks: bool = False,
    overrides_path: Path | None = None,
    notes: str = "",
    activate_binding: bool = False,
) -> dict[str, Any]:
    spec = IntegrationSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))
    overrides = (
        json.loads(overrides_path.read_text(encoding="utf-8"))
        if overrides_path is not None
        else {}
    )
    reviewed_payload = merge_dicts(spec.model_dump(), overrides)
    reviewed_spec = IntegrationSpec.model_validate(reviewed_payload)

    repo_root = config_root.parent
    plan = build_scaffold_plan(reviewed_spec)
    scaffold_paths = materialize_scaffold(
        spec=reviewed_spec,
        plan=plan,
        repo_root=repo_root,
    )
    report_dir = spec_path.parent
    reviewed_spec_path = report_dir / "integration_spec.reviewed.json"
    review_result_path = report_dir / "review_result.json"
    review_history_path = report_dir / "review_history.jsonl"
    activation_path = report_dir / "activation.json"
    activation_patch_path = report_dir / "activation_patch.json"
    reviewed_spec_path.write_text(
        json.dumps(reviewed_spec.model_dump(), indent=2),
        encoding="utf-8",
    )

    approved = (
        list(reviewed_spec.manual_checks)
        if approve_all_checks
        else _dedupe_items(approve_checks or [])
    )
    missing = [item for item in reviewed_spec.manual_checks if item not in set(approved)]
    if activate_binding and missing:
        raise ValueError(
            "manual checks must be approved before activation: "
            + ", ".join(missing)
        )

    binding_path = Path(str(scaffold_paths["binding_path"]))
    activation_payload: dict[str, Any] | None = None
    if activate_binding:
        activation_record = build_activation_record(
            spec=reviewed_spec,
            binding_id=str(plan.generated_binding_id),
            binding_path=binding_path,
            reviewer=reviewer,
            reviewed_spec_path=reviewed_spec_path,
            review_result_path=review_result_path,
        )
        activation_payload = activation_record.model_dump()
        activation_path.write_text(json.dumps(activation_payload, indent=2), encoding="utf-8")
        _mark_binding_activated(
            binding_path=binding_path,
            reviewer=reviewer,
            approved_checks=approved,
            reviewed_spec_path=reviewed_spec_path,
            review_result_path=review_result_path,
        )
        binding_payload = json.loads(binding_path.read_text(encoding="utf-8"))
        activation_patch = binding_payload.get("binding_patch") or {}
        activation_patch_path.write_text(json.dumps(activation_patch, indent=2), encoding="utf-8")

    review_result = build_review_result(
        spec=reviewed_spec,
        reviewer=reviewer,
        approved_checks=approved,
        missing_checks=missing,
        notes=notes,
        reviewed_spec_path=reviewed_spec_path,
        binding_path=binding_path,
        activation_path=activation_path if activation_payload is not None else None,
    )
    review_result_path.write_text(
        json.dumps(review_result.model_dump(), indent=2),
        encoding="utf-8",
    )
    with review_history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(review_result.model_dump(), ensure_ascii=False) + "\n")

    return {
        "spec_id": reviewed_spec.spec_id,
        "binding_id": plan.generated_binding_id,
        "status": review_result.status,
        "approved_checks": approved,
        "missing_checks": missing,
        "reviewed_spec_path": str(reviewed_spec_path),
        "binding_path": str(binding_path),
        "review_result_path": str(review_result_path),
        "review_history_path": str(review_history_path),
        "activation_patch_path": str(activation_patch_path) if activation_payload is not None else None,
        "activation_path": str(activation_path) if activation_payload is not None else None,
    }

def review_harness_payload(
    *,
    harness_spec_path: Path,
    reviewer: str,
    approve_checks: list[str] | None = None,
    approve_all_checks: bool = False,
    overrides_path: Path | None = None,
    notes: str = "",
) -> dict[str, Any]:
    spec = HarnessSpec.model_validate_json(harness_spec_path.read_text(encoding="utf-8"))
    overrides = (
        json.loads(overrides_path.read_text(encoding="utf-8"))
        if overrides_path is not None
        else {}
    )
    reviewed_payload = merge_dicts(spec.model_dump(), overrides)
    reviewed_spec = HarnessSpec.model_validate(reviewed_payload)
    report_dir = harness_spec_path.parent
    reviewed_spec_path = report_dir / "harness_spec.reviewed.json"
    review_result_path = report_dir / "harness_review_result.json"
    review_history_path = report_dir / "harness_review_history.jsonl"
    reviewed_spec_path.write_text(json.dumps(reviewed_spec.model_dump(), indent=2), encoding="utf-8")

    approved = (
        list(reviewed_spec.manual_checks)
        if approve_all_checks
        else _dedupe_items(approve_checks or [])
    )
    missing = [item for item in reviewed_spec.manual_checks if item not in set(approved)]
    result = IntegrationReviewResult(
        spec_id=reviewed_spec.spec_id,
        reviewer=reviewer,
        status="approved" if not missing else "needs_review",
        approved_checks=approved,
        missing_checks=missing,
        notes=notes,
        reviewed_spec_path=str(reviewed_spec_path),
        binding_path=None,
        activation_path=None,
    )
    review_result_path.write_text(json.dumps(result.model_dump(), indent=2), encoding="utf-8")
    with review_history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(result.model_dump(), ensure_ascii=False) + "\n")
    return {
        "spec_id": reviewed_spec.spec_id,
        "status": result.status,
        "approved_checks": approved,
        "missing_checks": missing,
        "reviewed_spec_path": str(reviewed_spec_path),
        "review_result_path": str(review_result_path),
        "review_history_path": str(review_history_path),
        "activation_path": None,
    }

def _dedupe_items(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped

def _mark_binding_activated(
    *,
    binding_path: Path,
    reviewer: str,
    approved_checks: list[str],
    reviewed_spec_path: Path,
    review_result_path: Path,
) -> None:
    payload = json.loads(binding_path.read_text(encoding="utf-8"))
    review_payload = {
        "status": "activated",
        "reviewer": reviewer,
        "approved_checks": approved_checks,
        "reviewed_spec_path": str(reviewed_spec_path),
        "review_result_path": str(review_result_path),
    }
    payload["review"] = review_payload
    binding_patch = payload.get("binding_patch")
    if isinstance(binding_patch, dict):
        runtime = binding_patch.setdefault("runtime", {})
        if isinstance(runtime, dict):
            runtime_binding = runtime.setdefault("binding", {})
            if isinstance(runtime_binding, dict):
                runtime_binding["review"] = review_payload
    binding_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

