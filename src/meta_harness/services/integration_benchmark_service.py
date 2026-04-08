from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from meta_harness.adapter_scaffolder import build_scaffold_plan
from meta_harness.benchmark_engine import run_benchmark
from meta_harness.integration_review import binding_review_status, is_generated_binding_id
from meta_harness.integration_schemas import HarnessSpec, IntegrationSpec
from meta_harness.services.benchmark_service import persist_benchmark_payload
from meta_harness.services.integration_scaffold_service import scaffold_harness_payload


def benchmark_integration_payload(
    *,
    config_root: Path,
    reports_root: Path,
    runs_root: Path,
    candidates_root: Path,
    spec_path: Path,
    profile_name: str,
    project_name: str,
    task_set_path: Path,
    focus: str | None = None,
    run_benchmark_fn: Any = run_benchmark,
) -> dict[str, Any]:
    resolved_spec_path = _resolved_reviewed_spec_path(spec_path)
    spec = IntegrationSpec.model_validate_json(resolved_spec_path.read_text(encoding="utf-8"))
    binding_path = _generated_binding_path(config_root, spec)
    binding_payload = json.loads(binding_path.read_text(encoding="utf-8"))
    if is_generated_binding_id(binding_payload.get("binding_id")) and binding_review_status(binding_payload) != "activated":
        raise ValueError(f"generated binding '{binding_payload.get('binding_id')}' requires activated review before benchmark")

    report_dir = resolved_spec_path.parent
    benchmark_spec_path = report_dir / "benchmark_spec.json"
    activation_patch_path = report_dir / "activation_patch.json"
    if not activation_patch_path.exists():
        activation_patch_path.write_text(
            json.dumps(binding_payload.get("binding_patch") or {}, indent=2),
            encoding="utf-8",
        )

    experiment = f"integration-{Path(spec.target_project_path).name}-{spec.primitive_id}"
    benchmark_spec = {
        "experiment": experiment,
        "baseline": "baseline",
        "variants": [
            {"name": "baseline"},
            {
                "name": "activated_binding",
                "config_patch": binding_payload.get("binding_patch") or {},
            },
        ],
    }
    benchmark_spec_path.write_text(json.dumps(benchmark_spec, indent=2), encoding="utf-8")
    payload = run_benchmark_fn(
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        profile_name=profile_name,
        project_name=project_name,
        task_set_path=task_set_path,
        spec_path=benchmark_spec_path,
        focus=focus,
    )
    payload = persist_benchmark_payload(reports_root=reports_root, payload=payload)
    payload["benchmark_spec_path"] = str(benchmark_spec_path)
    payload["activation_patch_path"] = str(activation_patch_path)
    return payload

def benchmark_harness_payload(
    *,
    config_root: Path,
    reports_root: Path,
    runs_root: Path,
    candidates_root: Path,
    harness_spec_path: Path,
    profile_name: str,
    project_name: str,
    task_set_path: Path,
    focus: str | None = None,
    run_benchmark_fn: Any = run_benchmark,
) -> dict[str, Any]:
    resolved_spec_path = _resolved_reviewed_harness_spec_path(harness_spec_path)
    spec = HarnessSpec.model_validate_json(resolved_spec_path.read_text(encoding="utf-8"))
    report_dir = resolved_spec_path.parent
    review_result_path = report_dir / "harness_review_result.json"
    if not review_result_path.exists():
        raise ValueError("harness benchmark requires reviewed harness spec")
    review_result = json.loads(review_result_path.read_text(encoding="utf-8"))
    if str(review_result.get("status")) != "approved":
        raise ValueError("harness benchmark requires approved harness review")

    scaffold = scaffold_harness_payload(
        config_root=config_root,
        harness_spec_path=resolved_spec_path,
    )
    wrapper_path = str(scaffold["wrapper_path"])
    candidate_harness = {
        "candidate_harness_id": spec.spec_id,
        "harness_spec_id": spec.spec_id,
        "iteration_id": f"{spec.spec_id}:iteration",
        "proposal_id": f"{spec.spec_id}:proposal",
        "wrapper_path": wrapper_path,
        "source_artifacts": [
            str(resolved_spec_path),
            str(review_result_path),
            str(scaffold["scaffold_result_path"]),
            str(scaffold["test_path"]),
        ],
        "provenance": {
            "source": "integration_service",
            "review_result_path": str(review_result_path),
            "reviewed_spec_path": str(resolved_spec_path),
            "scaffold_plan_path": str(scaffold["scaffold_plan_path"]),
            "scaffold_result_path": str(scaffold["scaffold_result_path"]),
        },
        "runtime": {
            "binding": {
                "binding_id": f"harness/{Path(spec.target_project_path).name}",
                "adapter_kind": "command",
                "command": ["python", wrapper_path, "${phase_command_json}"],
            }
        },
    }
    benchmark_spec_path = report_dir / "harness_benchmark_spec.json"
    experiment = f"harness-{Path(spec.target_project_path).name}"
    benchmark_spec = {
        "experiment": experiment,
        "baseline": "baseline",
        "variants": [
            {"name": "baseline"},
            {
                "name": "candidate_harness",
                "variant_type": "harness",
                "candidate_harness": candidate_harness,
            },
        ],
    }
    benchmark_spec_path.write_text(json.dumps(benchmark_spec, indent=2), encoding="utf-8")
    payload = run_benchmark_fn(
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        profile_name=profile_name,
        project_name=project_name,
        task_set_path=task_set_path,
        spec_path=benchmark_spec_path,
        focus=focus,
        effective_config_override={
            "runtime": {"workspace": {"source_repo": spec.target_project_path}},
            "evaluation": {"evaluators": ["basic"]},
        },
    )
    payload = persist_benchmark_payload(reports_root=reports_root, payload=payload)
    payload["benchmark_spec_path"] = str(benchmark_spec_path)
    payload["wrapper_path"] = wrapper_path
    return payload

def _resolved_reviewed_spec_path(spec_path: Path) -> Path:
    reviewed = spec_path.parent / "integration_spec.reviewed.json"
    return reviewed if reviewed.exists() else spec_path

def _resolved_reviewed_harness_spec_path(spec_path: Path) -> Path:
    reviewed = spec_path.parent / "harness_spec.reviewed.json"
    return reviewed if reviewed.exists() else spec_path

def _generated_binding_path(config_root: Path, spec: IntegrationSpec) -> Path:
    plan = build_scaffold_plan(spec)
    if not plan.files_to_create:
        raise FileNotFoundError("missing scaffold plan for generated binding")
    return config_root.parent / plan.files_to_create[0]
