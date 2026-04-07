from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from meta_harness.schemas import ScoreReport


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

        for config in configs:
            completed = subprocess.run(
                config["command"],
                cwd=run_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    f"command evaluator '{config['name']}' failed: {completed.stderr.strip()}"
                )

            payload = json.loads(completed.stdout.strip() or "{}")
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
