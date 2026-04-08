from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError
from uuid import uuid4

from meta_harness.schemas import GateCondition, GatePolicy


def _resolve_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part)
            continue
        return None
    return current


def _benchmark_has_valid_variant(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    return any(isinstance(item, dict) and item for item in value)


def _resolve_condition_value(target_payload: dict[str, Any], raw_value: Any) -> Any:
    if isinstance(raw_value, dict):
        path = raw_value.get("path")
        if isinstance(path, str) and path:
            return _resolve_path(target_payload, path)
    return raw_value


def _condition_passed(
    condition: GateCondition,
    *,
    target_payload: dict[str, Any],
    evidence_refs: list[str],
) -> bool:
    if condition.kind == "evidence_run_count_gte":
        return len(evidence_refs) >= int(condition.value)

    observed = _resolve_path(target_payload, condition.path)
    expected = _resolve_condition_value(target_payload, condition.value)

    if condition.kind == "benchmark_has_valid_variant":
        return _benchmark_has_valid_variant(observed) is bool(expected)
    if condition.kind == "test_suite_passed":
        return bool(observed) is bool(expected)
    if condition.kind == "stability_flag_is":
        return observed is expected
    if condition.kind == "run_status_is":
        return observed == expected
    if condition.kind in {
        "score_metric_gte",
        "ranking_score_gte",
        "composite_delta_gte",
        "min_evidence_count",
    }:
        return isinstance(observed, (int, float)) and isinstance(expected, (int, float)) and float(observed) >= float(expected)
    if condition.kind == "score_metric_lte":
        return isinstance(observed, (int, float)) and isinstance(expected, (int, float)) and float(observed) <= float(expected)

    raise ValueError(f"unsupported gate condition kind: {condition.kind}")


def evaluate_gate_policy(
    *,
    policy: dict[str, Any] | GatePolicy,
    target_payload: dict[str, Any],
    target_type: str,
    target_ref: str,
    evidence_refs: list[str] | None = None,
    reports_root: Path | None = None,
    persist_result: bool = False,
    execute_notifications: bool = False,
) -> dict[str, Any]:
    normalized = policy if isinstance(policy, GatePolicy) else GatePolicy.model_validate(policy)
    evidence = evidence_refs or []

    passed_conditions: list[dict[str, Any]] = []
    failed_conditions: list[dict[str, Any]] = []
    for condition in normalized.conditions:
        rendered = condition.model_dump(mode="json")
        if _condition_passed(
            condition,
            target_payload=target_payload,
            evidence_refs=evidence,
        ):
            passed_conditions.append(rendered)
        else:
            failed_conditions.append(rendered)

    waived_conditions, remaining_failed = _apply_waiver_rules(
        failed_conditions=failed_conditions,
        waiver_rules=list(normalized.waiver_rules),
    )
    status = "passed" if not remaining_failed else "failed"
    if remaining_failed == [] and waived_conditions:
        status = "waived"
    notifications = _build_notifications(
        notification_rules=list(normalized.notification_rules),
        status=status,
        target_type=target_type,
        target_ref=target_ref,
        policy_id=normalized.policy_id,
    )
    if execute_notifications:
        notifications = _deliver_notifications(notifications)
    result = {
        "policy_id": normalized.policy_id,
        "policy_type": normalized.policy_type,
        "target_type": target_type,
        "target_ref": target_ref,
        "status": status,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "passed_conditions": passed_conditions,
        "failed_conditions": remaining_failed,
        "waived_conditions": waived_conditions,
        "notifications": notifications,
        "evidence_refs": evidence,
    }
    if persist_result and reports_root is not None:
        result.update(_persist_gate_result(reports_root=reports_root, payload=result))
    return result


def evaluate_gate_policy_from_paths(
    *,
    policy_path: Path,
    target_path: Path,
    target_type: str,
    target_ref: str,
    evidence_refs: list[str] | None = None,
    reports_root: Path | None = None,
    persist_result: bool = False,
    execute_notifications: bool = False,
) -> dict[str, Any]:
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    target = json.loads(target_path.read_text(encoding="utf-8"))
    return evaluate_gate_policy(
        policy=policy,
        target_payload=target,
        target_type=target_type,
        target_ref=target_ref,
        evidence_refs=evidence_refs,
        reports_root=reports_root,
        persist_result=persist_result,
        execute_notifications=execute_notifications,
    )


def _persist_gate_result(*, reports_root: Path, payload: dict[str, Any]) -> dict[str, str]:
    gate_id = (
        f"{payload['policy_id']}-{payload['target_type']}-{uuid4().hex[:8]}"
    )
    gates_root = reports_root / "gates"
    gates_root.mkdir(parents=True, exist_ok=True)
    artifact_path = gates_root / f"{gate_id}.json"
    artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    history_path = gates_root / "history.jsonl"
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({**payload, "gate_id": gate_id}))
        handle.write("\n")
    return {
        "gate_id": gate_id,
        "artifact_path": str(artifact_path.relative_to(reports_root.parent)),
        "history_path": str(history_path.relative_to(reports_root.parent)),
    }


def list_gate_results(
    *,
    reports_root: Path,
    policy_id: str | None = None,
    target_type: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    gates_root = reports_root / "gates"
    if not gates_root.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(gates_root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        gate_id = path.stem
        if policy_id is not None and payload.get("policy_id") != policy_id:
            continue
        if target_type is not None and payload.get("target_type") != target_type:
            continue
        if status is not None and payload.get("status") != status:
            continue
        items.append(
            {
                **payload,
                "gate_id": gate_id,
                "artifact_path": str(path.relative_to(reports_root.parent)),
            }
        )
    return sorted(
        items,
        key=lambda item: (
            str(item.get("evaluated_at") or ""),
            str(item.get("gate_id") or ""),
        ),
        reverse=True,
    )


def load_gate_result(*, reports_root: Path, gate_id: str) -> dict[str, Any]:
    path = reports_root / "gates" / f"{gate_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"gate result '{gate_id}' not found")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        **payload,
        "gate_id": gate_id,
        "artifact_path": str(path.relative_to(reports_root.parent)),
        "history_path": str((reports_root / "gates" / "history.jsonl").relative_to(reports_root.parent)),
    }


def list_gate_history(
    *,
    reports_root: Path,
    policy_id: str | None = None,
    target_type: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    history_path = reports_root / "gates" / "history.jsonl"
    if not history_path.exists():
        return []
    items: list[dict[str, Any]] = []
    for line in history_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if policy_id is not None and payload.get("policy_id") != policy_id:
            continue
        if target_type is not None and payload.get("target_type") != target_type:
            continue
        if status is not None and payload.get("status") != status:
            continue
        items.append(payload)
    return sorted(
        items,
        key=lambda item: (
            str(item.get("evaluated_at") or ""),
            str(item.get("gate_id") or ""),
        ),
        reverse=True,
    )


def _apply_waiver_rules(
    *,
    failed_conditions: list[dict[str, Any]],
    waiver_rules: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not failed_conditions or not waiver_rules:
        return [], failed_conditions

    remaining_failed: list[dict[str, Any]] = []
    waived_conditions: list[dict[str, Any]] = []
    for condition in failed_conditions:
        matched_rule = next(
            (
                rule
                for rule in waiver_rules
                if _waiver_rule_matches(condition=condition, rule=rule)
            ),
            None,
        )
        if matched_rule is None:
            remaining_failed.append(condition)
            continue
        waived_conditions.append(
            {
                **condition,
                "reason": matched_rule.get("reason", ""),
                "waived_by": matched_rule.get("waived_by"),
                "expires_at": matched_rule.get("expires_at"),
            }
        )
    return waived_conditions, remaining_failed


def _waiver_rule_matches(*, condition: dict[str, Any], rule: dict[str, Any]) -> bool:
    match_kind = rule.get("match_kind")
    if isinstance(match_kind, str) and match_kind and condition.get("kind") != match_kind:
        return False
    expires_at = rule.get("expires_at")
    if isinstance(expires_at, str) and expires_at:
        if datetime.fromisoformat(expires_at) < datetime.now(UTC):
            return False
    return True


def _build_notifications(
    *,
    notification_rules: list[dict[str, Any]],
    status: str,
    target_type: str,
    target_ref: str,
    policy_id: str,
) -> list[dict[str, Any]]:
    notifications: list[dict[str, Any]] = []
    for rule in notification_rules:
        trigger_statuses = rule.get("trigger_statuses")
        if isinstance(trigger_statuses, list) and trigger_statuses and status not in trigger_statuses:
            continue
        template = str(rule.get("template") or "gate {status} for {target_ref}")
        notifications.append(
            {
                "channel": rule.get("channel"),
                "target": rule.get("target"),
                "headers": dict(rule.get("headers") or {}),
                "status": status,
                "policy_id": policy_id,
                "target_type": target_type,
                "target_ref": target_ref,
                "message": template.format(
                    status=status,
                    policy_id=policy_id,
                    target_type=target_type,
                    target_ref=target_ref,
                ),
            }
        )
    return notifications


def _deliver_notifications(
    notifications: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    delivered: list[dict[str, Any]] = []
    for item in notifications:
        payload = dict(item)
        channel = str(item.get("channel") or "")
        target = str(item.get("target") or "")
        headers = {
            str(key): str(value)
            for key, value in dict(item.get("headers") or {}).items()
        }
        try:
            if channel == "slack_webhook":
                body = {"text": str(item.get("message") or "")}
            else:
                body = {
                    "message": str(item.get("message") or ""),
                    "status": item.get("status"),
                    "policy_id": item.get("policy_id"),
                    "target_type": item.get("target_type"),
                    "target_ref": item.get("target_ref"),
                }
            result = _post_json(url=target, payload=body, headers=headers)
            payload["delivery"] = {
                "ok": 200 <= int(result["status_code"]) < 300,
                "status_code": result["status_code"],
                "response": result.get("body"),
            }
        except Exception as exc:
            payload["delivery"] = {
                "ok": False,
                "status_code": None,
                "error": str(exc),
            }
        delivered.append(payload)
    return delivered


def _post_json(
    *,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout_sec: float = 5.0,
) -> dict[str, Any]:
    encoded = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=encoded,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout_sec) as response:
            body = response.read().decode("utf-8")
            return {
                "status_code": response.getcode(),
                "body": json.loads(body) if body else None,
            }
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        return {
            "status_code": exc.code,
            "body": json.loads(body) if body else None,
        }
    except URLError as exc:
        raise ConnectionError(str(exc.reason)) from exc
