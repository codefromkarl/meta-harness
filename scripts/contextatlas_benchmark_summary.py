from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _read_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _render_benchmark_summary(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    if "suite" in payload:
        lines.append(f"Suite: {payload['suite']}")
        best_by_experiment = payload.get("best_by_experiment") or {}
        for experiment, winner in sorted(best_by_experiment.items()):
            lines.append(f"- {experiment}: {winner}")
        benchmarks = payload.get("benchmarks") or []
    else:
        benchmarks = [payload]
        lines.append(f"Benchmark: {payload.get('experiment', 'unknown')}")

    for benchmark in benchmarks:
        experiment = benchmark.get("experiment", "unknown")
        lines.append("")
        lines.append(f"Experiment: {experiment}")
        lines.append(f"Best Variant: {benchmark.get('best_variant', '-')}")
        lines.append(f"Best By Quality: {benchmark.get('best_by_quality', '-')}")
        lines.append(f"Best By Stability: {benchmark.get('best_by_stability', '-')}")

        if benchmark.get("best_variant") != benchmark.get("best_by_quality"):
            lines.append("Cost-sensitive winner differs from quality winner.")

        report_summary = benchmark.get("report_summary") or {}
        top_variants = report_summary.get("top_variants_by_ranking_score") or []
        for item in top_variants:
            lines.append(
                "  "
                + f"{item.get('name', '-')}: "
                + f"ranking_score={item.get('ranking_score', 0.0)} "
                + f"ranking_penalty={item.get('ranking_penalty', 0.0)} "
                + f"stability_penalty={item.get('stability_penalty', 0.0)} "
                + f"cost_penalty={item.get('cost_penalty', 0.0)} "
                + f"composite={item.get('composite', 0.0)}"
            )

    return "\n".join(lines) + "\n"


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: contextatlas_benchmark_summary.py <benchmark-payload.json>")

    payload = _read_payload(Path(sys.argv[1]))
    sys.stdout.write(_render_benchmark_summary(payload))


if __name__ == "__main__":
    main()
