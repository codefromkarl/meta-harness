from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from meta_harness.adapter_planner import plan_integration
from meta_harness.adapter_scaffolder import build_scaffold_plan
from meta_harness.contract_mapper import map_project_outputs_to_contract
from meta_harness.execution_model_inferer import infer_capability_modules, infer_execution_model
from meta_harness.integration_intake import build_integration_intent
from meta_harness.integration_schemas import HarnessSpec, IntegrationSpec, ReviewChecklist
from meta_harness.integration_review import build_review_checklist, render_review_checklist_markdown
from meta_harness.primitive_registry import load_registered_primitive_pack
from meta_harness.target_project_inspector import inspect_target_project


def analyze_integration_payload(
    *,
    config_root: Path,
    reports_root: Path,
    intent_text: str | None = None,
    target_project_path: str | Path | None = None,
    primitive_id: str | None = None,
    workflow_paths: list[str | Path] | None = None,
    user_goal: str = "",
    preferred_adapter_kind: str | None = None,
    allow_wrapper_generation: bool = True,
    allow_code_inspection: bool = True,
) -> dict[str, Any]:
    intent = build_integration_intent(
        intent_text=intent_text,
        target_project_path=target_project_path,
        primitive_id=primitive_id,
        workflow_paths=workflow_paths,
        user_goal=user_goal,
        preferred_adapter_kind=preferred_adapter_kind,
        allow_wrapper_generation=allow_wrapper_generation,
        allow_code_inspection=allow_code_inspection,
    )
    observation = inspect_target_project(intent)
    execution_model = infer_execution_model(observation)
    capability_modules = infer_capability_modules(observation, execution_model)
    harness_spec = _build_harness_spec(
        intent=intent,
        observation=observation,
        execution_model=execution_model,
        capability_modules=capability_modules,
    )
    spec: IntegrationSpec | None = None
    scaffold_plan = None
    checklist = _build_harness_review_checklist(harness_spec)
    artifact_mappings: list[object] = []
    missing_contracts: list[str] = []
    if intent.primitive_id:
        primitive_pack = load_registered_primitive_pack(config_root, intent.primitive_id)
        artifact_mappings, missing_contracts = map_project_outputs_to_contract(
            observation=observation,
            primitive_pack=primitive_pack,
        )
        spec = plan_integration(
            intent=intent,
            observation=observation,
            execution_model=execution_model,
            primitive_pack=primitive_pack,
            artifact_mappings=artifact_mappings,
            missing_contracts=missing_contracts,
        )
        scaffold_plan = build_scaffold_plan(spec)
        checklist = build_review_checklist(spec)

    report_dir = reports_root / "integration" / harness_spec.spec_id
    report_dir.mkdir(parents=True, exist_ok=True)
    intent_path = report_dir / "intent.json"
    observation_path = report_dir / "observation.json"
    harness_spec_path = report_dir / "harness_spec.json"
    spec_path = report_dir / "integration_spec.json"
    scaffold_plan_path = report_dir / "scaffold_plan.json"
    checklist_path = report_dir / "review_checklist.json"
    checklist_md_path = report_dir / "review_checklist.md"

    intent_path.write_text(json.dumps(intent.model_dump(), indent=2), encoding="utf-8")
    observation_path.write_text(json.dumps(observation.model_dump(), indent=2), encoding="utf-8")
    harness_spec_path.write_text(json.dumps(harness_spec.model_dump(), indent=2), encoding="utf-8")
    checklist_path.write_text(json.dumps(checklist.model_dump(), indent=2), encoding="utf-8")
    checklist_md_path.write_text(render_review_checklist_markdown(checklist), encoding="utf-8")
    if spec is not None and scaffold_plan is not None and checklist is not None:
        spec_path.write_text(json.dumps(spec.model_dump(), indent=2), encoding="utf-8")
        scaffold_plan_path.write_text(
            json.dumps(scaffold_plan.model_dump(), indent=2),
            encoding="utf-8",
        )

    return {
        "spec_id": harness_spec.spec_id,
        "primitive_id": intent.primitive_id,
        "target_project_path": harness_spec.target_project_path,
        "execution_model": harness_spec.execution_model.model_dump(),
        "capability_modules": list(harness_spec.capability_modules),
        "candidate_primitives": list(harness_spec.candidate_primitives),
        "observation_path": str(observation_path),
        "harness_spec_path": str(harness_spec_path),
        "integration_spec_path": str(spec_path) if spec is not None else None,
        "scaffold_plan_path": str(scaffold_plan_path) if scaffold_plan is not None else None,
        "review_checklist_path": str(checklist_md_path) if checklist is not None else None,
    }

def _build_harness_spec(
    *,
    intent: Any,
    observation: Any,
    execution_model: Any,
    capability_modules: list[str],
) -> HarnessSpec:
    spec_id = _build_harness_spec_id(intent.target_project_path)
    output_boundaries = sorted(
        {
            str(item.get("artifact_name") or "")
            for item in observation.output_candidates
            if str(item.get("artifact_name") or "")
        }
    )
    input_boundaries = sorted(
        {
            str(item.get("kind") or "")
            for item in observation.input_candidates
            if str(item.get("kind") or "")
        }
    )
    candidate_primitives = _candidate_primitives_from_harness(
        capability_modules=capability_modules,
        execution_model=execution_model,
    )
    risk_points = list(_harness_risk_points(observation=observation, execution_model=execution_model))
    return HarnessSpec(
        spec_id=spec_id,
        target_project_path=intent.target_project_path,
        execution_model=execution_model,
        capability_modules=capability_modules,
        detected_entrypoints=list(observation.detected_entrypoints),
        input_boundaries=input_boundaries,
        output_boundaries=output_boundaries,
        environment_requirements=list(observation.environment_requirements),
        risk_points=risk_points,
        manual_checks=_harness_manual_checks(observation=observation, execution_model=execution_model),
        candidate_primitives=candidate_primitives if intent.primitive_id is None else [intent.primitive_id],
        user_goal=intent.user_goal,
    )

def _build_harness_spec_id(target_project_path: str) -> str:
    name = Path(target_project_path).name.replace("_", "-").lower() or "project"
    return f"harness-{name}"

def _candidate_primitives_from_harness(
    *,
    capability_modules: list[str],
    execution_model: Any,
) -> list[str]:
    candidates: list[str] = []
    if execution_model.kind == "browser_automation":
        candidates.append("web_scrape")
    if "report_normalizer" in capability_modules:
        candidates.append("data_analysis")
    return candidates

def _harness_risk_points(*, observation: Any, execution_model: Any) -> list[str]:
    risks: list[str] = []
    if execution_model.wrapper_reason:
        risks.append(str(execution_model.wrapper_reason))
    if "service_port" in observation.environment_requirements:
        risks.append("project may depend on network service availability")
    if "browser" in observation.environment_requirements:
        risks.append("project may reference browser tooling or login state")
    if not observation.detected_entrypoints:
        risks.append("entry command could not be resolved automatically")
    return risks

def _harness_manual_checks(*, observation: Any, execution_model: Any) -> list[str]:
    checks = [
        "入口命令是否正确",
        "输出边界是否足以支持 harness 评估",
        "stdout/stderr 是否会混入不可控日志",
        "失败退出码是否稳定可判定",
        "是否需要外部服务、登录态或额外守护进程",
    ]
    if execution_model.kind == "http_job_api":
        checks.append("轮询 / 回调完成条件是否稳定")
    if "browser" in observation.environment_requirements:
        checks.append("浏览器依赖是否来自真实运行而不是文档示例")
    return checks

def _build_harness_review_checklist(spec: HarnessSpec) -> ReviewChecklist:
    return ReviewChecklist(
        spec_id=spec.spec_id,
        summary=f"Review harness draft for target `{spec.target_project_path}`.",
        risk_points=list(spec.risk_points),
        manual_checks=list(spec.manual_checks),
    )

