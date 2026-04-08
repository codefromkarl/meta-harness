from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from meta_harness.integration_schemas import (
    ArtifactMapping,
    ExecutionModel,
    IntegrationIntent,
    IntegrationSpec,
    ProjectObservation,
)
from meta_harness.schemas import PrimitivePack

_BASE_MANUAL_CHECKS = [
    "入口命令是否正确",
    "输出是否真的是最终业务结果",
    "是否依赖登录态 / 浏览器 / 服务端口",
    "stdout 是否会混入日志",
    "reply schema 是否真稳定",
    "probe 值是否能真实反映执行过程",
    "失败退出码是否可用于自动判断",
]


def plan_integration(
    *,
    intent: IntegrationIntent,
    observation: ProjectObservation,
    execution_model: ExecutionModel,
    primitive_pack: PrimitivePack,
    artifact_mappings: list[ArtifactMapping],
    missing_contracts: list[str],
) -> IntegrationSpec:
    primitive_id = intent.primitive_id
    if not primitive_id:
        raise ValueError("primitive_id is required to build integration spec")

    risk_points = _build_risk_points(
        observation=observation,
        execution_model=execution_model,
        missing_contracts=missing_contracts,
    )
    return IntegrationSpec(
        spec_id=_build_spec_id(intent.target_project_path, primitive_id),
        target_project_path=intent.target_project_path,
        primitive_id=primitive_id,
        execution_model=execution_model,
        binding_patch=_build_binding_patch(execution_model, primitive_id),
        wrapper_plan=_build_wrapper_plan(execution_model, artifact_mappings, missing_contracts),
        artifact_mappings=artifact_mappings,
        missing_contracts=missing_contracts,
        risk_points=risk_points,
        manual_checks=_build_manual_checks(observation, execution_model),
    )


def _build_spec_id(target_project_path: str, primitive_id: str) -> str:
    slug = Path(target_project_path).name.replace("_", "-").lower() or "project"
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"{primitive_id}-{slug}-{timestamp}"


def _build_binding_patch(execution_model: ExecutionModel, primitive_id: str) -> dict[str, object]:
    execution: dict[str, object] = {}
    if execution_model.entry_command:
        execution["command"] = execution_model.entry_command
    if primitive_id:
        execution["bridge_contract"] = "primitive_output"
    return {
        "adapter_kind": "command",
        "primitive_id": primitive_id,
        "execution": execution,
    }


def _build_wrapper_plan(
    execution_model: ExecutionModel,
    artifact_mappings: list[ArtifactMapping],
    missing_contracts: list[str],
) -> dict[str, object]:
    return {
        "required": execution_model.needs_wrapper,
        "reason": execution_model.wrapper_reason,
        "normalize_from": [item.source_artifact for item in artifact_mappings],
        "missing_contracts": missing_contracts,
    }


def _build_risk_points(
    *,
    observation: ProjectObservation,
    execution_model: ExecutionModel,
    missing_contracts: list[str],
) -> list[str]:
    risks: list[str] = []
    if missing_contracts:
        risks.append(f"primitive contract artifacts missing: {', '.join(missing_contracts)}")
    if execution_model.needs_wrapper and execution_model.wrapper_reason:
        risks.append(execution_model.wrapper_reason)
    if "service_port" in observation.environment_requirements:
        risks.append("target project appears to depend on an active local or remote service port")
    if "browser" in observation.environment_requirements:
        risks.append("target project may depend on browser automation or logged-in state")
    if "stdout_print" in observation.logging_patterns:
        risks.append("stdout logging may pollute structured adapter output")
    return risks


def _build_manual_checks(
    observation: ProjectObservation,
    execution_model: ExecutionModel,
) -> list[str]:
    checks = list(_BASE_MANUAL_CHECKS)
    if execution_model.kind == "browser_automation":
        checks.append("浏览器上下文是否需要复用登录态")
    if "secrets" in observation.environment_requirements:
        checks.append("运行前是否需要补充 API key / token / cookies")
    return checks
