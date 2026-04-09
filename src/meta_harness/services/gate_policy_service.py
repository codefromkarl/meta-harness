from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _gate_policies_root(config_root: Path) -> Path:
    return config_root / "gate_policies"


def list_gate_policies(config_root: Path) -> list[dict[str, Any]]:
    root = _gate_policies_root(config_root)
    if not root.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        items.append(
            {
                "policy_id": str(payload.get("policy_id", path.stem)),
                "policy_type": payload.get("policy_type"),
                "path": str(path),
                "enabled": payload.get("enabled", True),
            }
        )
    return items


def load_gate_policy(config_root: Path, policy_id: str) -> dict[str, Any]:
    root = _gate_policies_root(config_root)
    for path in sorted(root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("policy_id", path.stem) == policy_id:
            return payload
    raise FileNotFoundError(f"gate policy '{policy_id}' not found")


def resolve_shadow_validation_policy(
    *,
    effective_config: dict[str, Any] | None,
    evaluation_plan: dict[str, Any] | None = None,
    trigger: str,
) -> dict[str, Any]:
    effective_config = effective_config if isinstance(effective_config, dict) else {}
    evaluation_config = effective_config.get("evaluation")
    evaluation_config = evaluation_config if isinstance(evaluation_config, dict) else {}
    optimization_config = effective_config.get("optimization")
    optimization_config = (
        optimization_config if isinstance(optimization_config, dict) else {}
    )
    policy: dict[str, Any] = {}
    for source in (
        optimization_config.get("shadow_validation_policy"),
        evaluation_config.get("shadow_validation_policy"),
        evaluation_plan.get("shadow_validation_policy")
        if isinstance(evaluation_plan, dict)
        else None,
    ):
        if isinstance(source, dict):
            policy.update(source)
    triggers = policy.get("triggers")
    if isinstance(triggers, list):
        normalized_triggers = [str(item) for item in triggers if str(item).strip()]
    else:
        normalized_triggers = [trigger]
    if not normalized_triggers:
        normalized_triggers = [trigger]
    validation_command = policy.get("validation_command")
    if not isinstance(validation_command, list) and isinstance(evaluation_plan, dict):
        plan_validation_command = evaluation_plan.get("validation_command")
        if isinstance(plan_validation_command, list):
            validation_command = [str(item) for item in plan_validation_command]
    elif isinstance(validation_command, list):
        validation_command = [str(item) for item in validation_command]
    validation_workdir = policy.get("validation_workdir")
    if validation_workdir is None and isinstance(evaluation_plan, dict):
        plan_workdir = evaluation_plan.get("validation_workdir")
        if plan_workdir is not None:
            validation_workdir = str(plan_workdir)
    enabled_default = trigger in {"loop_shadow_run", "observation_auto_propose"}
    failure_behavior_default = (
        "fail_evaluation" if trigger == "loop_shadow_run" else "skip_shadow_run"
    )
    return {
        "enabled": bool(policy.get("enabled", enabled_default)),
        "trigger": trigger,
        "triggers": normalized_triggers,
        "failure_behavior": str(
            policy.get("failure_behavior") or failure_behavior_default
        ),
        "validation_command": validation_command,
        "validation_workdir": (
            str(validation_workdir) if validation_workdir is not None else None
        ),
    }


def should_trigger_shadow_validation(
    policy: dict[str, Any] | None,
    *,
    trigger: str,
) -> bool:
    if not isinstance(policy, dict):
        return False
    if not bool(policy.get("enabled")):
        return False
    triggers = policy.get("triggers")
    if isinstance(triggers, list) and triggers:
        return trigger in {str(item) for item in triggers}
    return str(policy.get("trigger") or "") == trigger
