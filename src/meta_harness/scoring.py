from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from meta_harness.evaluators import get_evaluator


def score_run(
    run_dir: Path,
    *,
    evaluator_names: list[str] | None = None,
) -> dict[str, Any]:
    effective_config = json.loads((run_dir / "effective_config.json").read_text(encoding="utf-8"))
    evaluation_config = effective_config.get("evaluation", {})
    configured_evaluators = evaluation_config.get("evaluators", ["basic"])
    selected_evaluators = evaluator_names or configured_evaluators
    unknown_evaluators = [
        name for name in selected_evaluators if name not in configured_evaluators
    ]
    if unknown_evaluators:
        raise ValueError(
            f"requested evaluators are not configured for run: {', '.join(unknown_evaluators)}"
        )

    final_report: dict[str, Any] | None = None
    evaluators_dir = run_dir / "evaluators"
    evaluators_dir.mkdir(parents=True, exist_ok=True)
    for evaluator_name in selected_evaluators:
        report = get_evaluator(evaluator_name).evaluate(run_dir, evaluation_config=evaluation_config)
        (evaluators_dir / f"{evaluator_name}.json").write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )
        if final_report is None:
            final_report = report
        else:
            final_report = _merge_reports(final_report, report)

    if final_report is None:
        raise ValueError("no evaluators configured")

    final_report["composite"] = final_report.get("composite", 0.0) + final_report.pop(
        "composite_adjustment", 0.0
    )

    (run_dir / "score_report.json").write_text(
        json.dumps(final_report, indent=2),
        encoding="utf-8",
    )
    return final_report


def _merge_reports(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
        elif key == "composite_adjustment":
            merged[key] = float(merged.get(key, 0.0)) + float(value)
        else:
            merged[key] = value
    return merged
