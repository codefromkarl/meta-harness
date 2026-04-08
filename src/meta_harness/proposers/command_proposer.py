from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from meta_harness.proposers.base import ProposalEnvelope
from meta_harness.template_utils import (
    _build_template_context,
    _normalize_template_paths,
    _resolve_template,
)


def run_proposal_command(
    command: list[str],
    payload: dict[str, Any],
    effective_config: dict[str, Any],
) -> dict[str, Any]:
    optimization_config = effective_config.get("optimization", {})
    workdir = optimization_config.get("proposal_workdir")
    if workdir is None:
        workdir = (
            effective_config.get("runtime", {}).get("workspace", {}).get("source_repo")
        )
    if workdir is None:
        workdir = "."
    templating_context = _build_template_context(
        Path(str(workdir)).expanduser(),
        effective_config=effective_config,
    )
    _normalize_template_paths(templating_context)
    resolved_workdir = Path(
        str(_resolve_template(str(workdir), templating_context))
    ).expanduser()
    resolved_command = [
        str(item)
        for item in _resolve_template(command, templating_context)
    ]

    completed = subprocess.run(
        resolved_command,
        cwd=resolved_workdir,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"proposal command failed: {completed.stderr.strip() or completed.stdout.strip()}"
        )

    try:
        return json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("proposal command returned invalid JSON") from exc


@dataclass(slots=True)
class CommandProposer:
    proposer_id: str = "command"
    command: list[str] | None = None
    workdir: Path | None = None
    extra_payload: dict[str, Any] = field(default_factory=dict)

    def propose(
        self,
        *,
        objective: dict[str, Any],
        experience: dict[str, Any],
        constraints: dict[str, Any],
    ) -> ProposalEnvelope:
        command = self.command or constraints.get("proposal_command")
        if not command:
            raise ValueError("command proposer requires a proposal command")

        effective_config = dict(constraints.get("effective_config") or {})
        payload = {
            "profile": constraints.get("profile_name"),
            "project": constraints.get("project_name"),
            "effective_config": effective_config,
            "matching_runs": experience.get("matching_runs", []),
            "failure_records": experience.get("failure_records", []),
            "objective": objective,
            "experience": experience,
            **self.extra_payload,
        }
        generated = run_proposal_command(
            command=[str(item) for item in command],
            payload=payload,
            effective_config=effective_config,
        )
        proposal = generated.get("proposal") if isinstance(generated.get("proposal"), dict) else {}
        return {
            "proposer_kind": "command",
            "proposal": proposal,
            "config_patch": generated.get("config_patch")
            if isinstance(generated.get("config_patch"), dict)
            else None,
            "code_patch": str(generated["code_patch"]) if generated.get("code_patch") is not None else None,
            "notes": str(generated.get("notes", "optimizer proposal from command")),
            "source_run_ids": [
                str(record.get("run_id"))
                for record in experience.get("matching_runs", [])
                if str(record.get("run_id") or "")
            ],
        }
