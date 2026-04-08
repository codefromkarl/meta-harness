from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from meta_harness.schemas import ScoreReport
from meta_harness.template_utils import _build_template_context, _resolve_template


class Evaluator:
    name = "base"

    def evaluate(
        self, run_dir: Path, evaluation_config: dict[str, Any] | None = None
    ) -> dict:
        raise NotImplementedError


class BasicEvaluator(Evaluator):
    name = "basic"

    @staticmethod
    def _calibration_adjustment(task_dir: Path) -> float:
        probe_path = task_dir / "variance_probe.stdout.txt"
        if not probe_path.exists():
            return 0.0
        raw = probe_path.read_text(encoding="utf-8").strip()
        if not raw:
            return 0.0
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return 0.0
        probes = payload.get("probes")
        if not isinstance(probes, dict):
            return 0.0
        synthetic_variance = probes.get("calibration.synthetic_variance")
        instability_trigger = probes.get("calibration.instability_trigger")
        if not isinstance(synthetic_variance, (int, float)):
            return 0.0
        if not isinstance(instability_trigger, (int, float)):
            instability_trigger = 0.0
        penalty = float(synthetic_variance) * 0.5 + float(instability_trigger) * 0.25
        return min(1.0, max(0.0, penalty))

    def evaluate(
        self, run_dir: Path, evaluation_config: dict[str, Any] | None = None
    ) -> dict:
        task_dirs = sorted(
            path for path in (run_dir / "tasks").iterdir() if path.is_dir()
        )
        trace_event_count = 0
        completed_steps = 0
        manual_interventions = 0
        calibration_penalty = 0.0

        for task_dir in task_dirs:
            steps_path = task_dir / "steps.jsonl"
            if steps_path.exists():
                for line in steps_path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    trace_event_count += 1
                    payload = json.loads(line)
                    if payload.get("status") == "completed":
                        completed_steps += 1

            intervention_path = task_dir / "intervention.json"
            if intervention_path.exists():
                payload = json.loads(intervention_path.read_text(encoding="utf-8"))
                manual_interventions += int(payload.get("manual_interventions", 0))
            calibration_penalty += self._calibration_adjustment(task_dir)

        report = ScoreReport(
            correctness={
                "task_count": len(task_dirs),
                "completed_steps": completed_steps,
            },
            cost={
                "trace_event_count": trace_event_count,
            },
            maintainability={},
            architecture={},
            retrieval={},
            human_collaboration={
                "manual_interventions": manual_interventions,
            },
            composite=max(
                0.0,
                completed_steps - (manual_interventions * 0.5) - calibration_penalty,
            ),
        )
        return report.model_dump()


class CommandEvaluator(Evaluator):
    name = "command"

    @staticmethod
    def _artifact_dir(run_dir: Path, index: int, name: str) -> Path:
        safe = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in name)
        safe = safe.strip("-") or f"evaluator-{index + 1}"
        return run_dir / "evaluators" / "command_artifacts" / f"{index + 1:02d}-{safe}"

    @staticmethod
    def _resolve_command(run_dir: Path, command: list[Any]) -> list[str]:
        effective_config_path = run_dir / "effective_config.json"
        effective_config: dict[str, Any] = {}
        source_repo: Path | None = None
        if effective_config_path.exists():
            effective_config = json.loads(
                effective_config_path.read_text(encoding="utf-8")
            )
            workspace = (effective_config.get("runtime") or {}).get("workspace") or {}
            source_repo_value = workspace.get("source_repo")
            if isinstance(source_repo_value, str) and source_repo_value:
                source_repo = Path(source_repo_value).expanduser().resolve()
        templating_context = _build_template_context(
            run_dir,
            effective_config=effective_config,
        )
        command = _resolve_template(command, templating_context)

        resolved: list[str] = []
        for index, raw_arg in enumerate(command):
            arg = str(raw_arg)
            if source_repo is None or arg.startswith("-"):
                resolved.append(arg)
                continue

            candidate = Path(arg)
            if candidate.is_absolute() or (run_dir / candidate).exists():
                resolved.append(arg)
                continue

            source_candidate = source_repo / arg
            if index == 0:
                if source_candidate.exists() and os.access(source_candidate, os.X_OK):
                    resolved.append(str(source_candidate))
                else:
                    resolved.append(arg)
                continue

            if source_candidate.exists():
                resolved.append(str(source_candidate))
            else:
                resolved.append(arg)

        return resolved

    def evaluate(
        self, run_dir: Path, evaluation_config: dict[str, Any] | None = None
    ) -> dict:
        configs = []
        if evaluation_config is not None:
            configs = evaluation_config.get("command_evaluators", [])

        maintainability: dict[str, Any] = {}
        architecture: dict[str, Any] = {}
        retrieval: dict[str, Any] = {}
        correctness: dict[str, Any] = {}
        cost: dict[str, Any] = {}
        human_collaboration: dict[str, Any] = {}
        capability_scores: dict[str, Any] = {}
        workflow_scores: dict[str, Any] = {}
        probes: dict[str, Any] = {}
        composite_adjustment = 0.0

        for index, config in enumerate(configs):
            artifact_dir = self._artifact_dir(run_dir, index, str(config["name"]))
            artifact_dir.mkdir(parents=True, exist_ok=True)
            resolved_command = self._resolve_command(run_dir, config["command"])
            started_at = time.perf_counter()
            completed = subprocess.run(
                resolved_command,
                cwd=run_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            duration_ms = round((time.perf_counter() - started_at) * 1000)
            (artifact_dir / "stdout.txt").write_text(
                completed.stdout,
                encoding="utf-8",
            )
            (artifact_dir / "stderr.txt").write_text(
                completed.stderr,
                encoding="utf-8",
            )
            (artifact_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "name": str(config["name"]),
                        "command": resolved_command,
                        "returncode": completed.returncode,
                        "duration_ms": duration_ms,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    f"command evaluator '{config['name']}' failed: {completed.stderr.strip()}"
                )

            payload = json.loads(completed.stdout.strip() or "{}")
            (artifact_dir / "payload.json").write_text(
                json.dumps(payload, indent=2),
                encoding="utf-8",
            )
            maintainability.update(payload.get("maintainability", {}))
            architecture.update(payload.get("architecture", {}))
            retrieval.update(payload.get("retrieval", {}))
            correctness.update(payload.get("correctness", {}))
            cost.update(payload.get("cost", {}))
            human_collaboration.update(payload.get("human_collaboration", {}))
            capability_scores.update(payload.get("capability_scores", {}))
            workflow_scores.update(payload.get("workflow_scores", {}))
            probes.update(payload.get("probes", {}))
            composite_adjustment += float(payload.get("composite_adjustment", 0.0))

        return {
            "correctness": correctness,
            "cost": {
                **cost,
                "command_evaluators_run": len(configs),
            },
            "maintainability": maintainability,
            "architecture": architecture,
            "retrieval": retrieval,
            "human_collaboration": human_collaboration,
            "capability_scores": capability_scores,
            "workflow_scores": workflow_scores,
            "probes": probes,
            "composite_adjustment": composite_adjustment,
        }


EVALUATORS: dict[str, type[Evaluator]] = {
    BasicEvaluator.name: BasicEvaluator,
    CommandEvaluator.name: CommandEvaluator,
}


def get_evaluator(name: str) -> Evaluator:
    evaluator_cls = EVALUATORS.get(name)
    if evaluator_cls is None:
        raise ValueError(f"unknown evaluator: {name}")
    return evaluator_cls()
