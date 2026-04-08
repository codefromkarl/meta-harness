from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from meta_harness.primitive_bridge import resolve_binding_message


@dataclass
class BindingExecutionResult:
    completed: subprocess.CompletedProcess[str]
    payload: dict[str, Any] | None = None
    token_usage: dict[str, int] | None = None
    model: str | None = None
    artifact_refs: list[str] = field(default_factory=list)
    normalized_events: list[dict[str, Any]] = field(default_factory=list)


def execute_binding(
    *,
    adapter_kind: str,
    binding: dict[str, Any],
    phase: dict[str, Any],
    workdir: Path,
    context: dict[str, Any],
    resolve_template: Callable[[Any, dict[str, Any]], Any],
    env_factory: Callable[[dict[str, Any], dict[str, Any]], dict[str, str]],
) -> BindingExecutionResult:
    if adapter_kind == "command":
        return _execute_command_binding(
            binding=binding,
            phase=phase,
            workdir=workdir,
            context=context,
            resolve_template=resolve_template,
            env_factory=env_factory,
        )
    if adapter_kind in {"openclaw_agent", "json_agent_cli"}:
        return _execute_openclaw_agent_binding(
            binding=binding,
            phase=phase,
            workdir=workdir,
            context=context,
            resolve_template=resolve_template,
            env_factory=env_factory,
        )
    raise RuntimeError(f"unsupported binding adapter: {adapter_kind}")


def _execute_command_binding(
    *,
    binding: dict[str, Any],
    phase: dict[str, Any],
    workdir: Path,
    context: dict[str, Any],
    resolve_template: Callable[[Any, dict[str, Any]], Any],
    env_factory: Callable[[dict[str, Any], dict[str, Any]], dict[str, str]],
) -> BindingExecutionResult:
    raw_command = binding.get("command")
    if raw_command is None:
        raw_command = phase["command"]
    command = resolve_template(raw_command, context)
    completed = subprocess.run(
        command,
        cwd=workdir,
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            **env_factory(binding, context),
        },
    )
    payload = None
    if bool(binding.get("parse_json_output", False)):
        payload = _parse_json_payload(completed.stdout)
    return BindingExecutionResult(
        completed=completed,
        payload=payload,
        model=_binding_model(binding),
    )


def _execute_openclaw_agent_binding(
    *,
    binding: dict[str, Any],
    phase: dict[str, Any],
    workdir: Path,
    context: dict[str, Any],
    resolve_template: Callable[[Any, dict[str, Any]], Any],
    env_factory: Callable[[dict[str, Any], dict[str, Any]], dict[str, str]],
) -> BindingExecutionResult:
    cli_command = binding.get("cli_command") or ["openclaw", "agent"]
    command = [str(item) for item in resolve_template(cli_command, context)]

    agent_id = binding.get("agent")
    if isinstance(agent_id, str) and agent_id:
        command.extend(["--agent", agent_id])

    session_id = binding.get("session_id")
    if isinstance(session_id, str) and session_id:
        command.extend(["--session-id", session_id])

    to = binding.get("to")
    if isinstance(to, str) and to:
        command.extend(["--to", to])

    message = resolve_binding_message(
        binding=binding,
        phase=phase,
        context=context,
        resolve_template=resolve_template,
    )
    command.extend(["--message", message])

    thinking = binding.get("thinking")
    if isinstance(thinking, str) and thinking:
        command.extend(["--thinking", thinking])

    verbose = binding.get("verbose")
    if isinstance(verbose, str) and verbose:
        command.extend(["--verbose", verbose])

    if bool(binding.get("local", False)):
        command.append("--local")

    timeout = binding.get("timeout")
    if isinstance(timeout, (int, float, str)) and str(timeout):
        command.extend(["--timeout", str(timeout)])

    if bool(binding.get("json", True)):
        command.append("--json")

    completed = subprocess.run(
        command,
        cwd=workdir,
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            **env_factory(binding, context),
        },
    )
    payload = _parse_json_payload(completed.stdout)
    token_usage = _extract_openclaw_token_usage(payload)
    normalized_events: list[dict[str, Any]] = []
    reply = payload.get("reply") if isinstance(payload, dict) else None
    if isinstance(reply, str) and reply.strip():
        normalized_events.append(
            {
                "phase": "assistant_reply",
                "status": "completed",
                "token_usage": token_usage,
                "model": _binding_model(binding),
            }
        )
    return BindingExecutionResult(
        completed=completed,
        payload=payload,
        token_usage=token_usage,
        model=_binding_model(binding),
        normalized_events=normalized_events,
    )


def _parse_json_payload(stdout: str) -> dict[str, Any] | None:
    raw = stdout.strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _extract_openclaw_token_usage(payload: dict[str, Any] | None) -> dict[str, int] | None:
    if not isinstance(payload, dict):
        return None
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    total = usage.get("totalTokens")
    if isinstance(total, int):
        return {"total": total}
    if isinstance(total, float):
        return {"total": int(total)}
    return None


def _binding_model(binding: dict[str, Any]) -> str | None:
    model = binding.get("model")
    if isinstance(model, str) and model:
        return model
    agent = binding.get("agent") or binding.get("agent_id")
    if isinstance(agent, str) and agent:
        return agent
    return None
