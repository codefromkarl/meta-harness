from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from meta_harness.benchmark import run_benchmark_suite
from meta_harness.strategy_cards import shortlist_strategy_cards


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_pool_paths(pool: dict[str, Any], pool_path: Path) -> dict[str, Any]:
    resolved = dict(pool)
    for key in ("suite", "task_set", "summary_script"):
        if key in resolved and isinstance(resolved[key], str):
            resolved[key] = str(_resolve_pool_reference(resolved[key], pool_path))
    resolved["strategy_cards"] = [
        str(_resolve_pool_reference(str(card), pool_path))
        for card in pool.get("strategy_cards", [])
    ]
    return resolved


def _recommended_cards(
    shortlist: dict[str, Any], prefer_status: list[str]
) -> list[str]:
    ordered: list[str] = []
    groups = shortlist.get("groups") or {}
    for status in prefer_status:
        for item in groups.get(status, []):
            ordered.append(str(item["strategy_id"]))
    return ordered


def _build_commands(pool: dict[str, Any], config_root: Path) -> dict[str, list[str]]:
    return {
        "shortlist": [
            "PYTHONPATH=src",
            "python",
            "-m",
            "meta_harness.cli",
            "strategy",
            "shortlist",
            "--profile",
            str(pool["profile"]),
            "--project",
            str(pool["project"]),
            "--config-root",
            str(config_root),
            *[str(card) for card in pool.get("strategy_cards", [])],
        ],
        "benchmark_suite": [
            "PYTHONPATH=src",
            "python",
            "-m",
            "meta_harness.cli",
            "observe",
            "benchmark-suite",
            "--profile",
            str(pool["profile"]),
            "--project",
            str(pool["project"]),
            "--config-root",
            str(config_root),
            "--runs-root",
            "runs",
            "--candidates-root",
            "candidates",
            "--task-set",
            str(pool["task_set"]),
            "--suite",
            str(pool["suite"]),
        ],
        "summary": [
            "python",
            str(pool["summary_script"]),
            "<benchmark-suite-output.json>",
        ],
    }


def _resolve_pool_reference(raw_path: str, pool_path: Path) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate.resolve()
    pool_relative = (pool_path.parent / candidate).resolve()
    if pool_relative.exists():
        return pool_relative
    return (REPO_ROOT / candidate).resolve()


def _write_artifact(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)


def _render_summary(benchmark_payload: dict[str, Any], summary_script: Path) -> str:
    completed = __import__("subprocess").run(
        ["python", str(summary_script), str(benchmark_payload)],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


def _derive_experiment_conclusion(benchmark: dict[str, Any]) -> dict[str, Any]:
    best_variant = str(benchmark.get("best_variant", ""))
    best_by_quality = str(benchmark.get("best_by_quality", ""))
    best_by_stability = str(benchmark.get("best_by_stability", ""))
    if best_variant == best_by_quality == best_by_stability:
        status = "recommend_adopt"
        reason = "quality, stability and ranking winner are aligned"
    elif best_variant == best_by_stability and best_variant != best_by_quality:
        status = "review_cost_tradeoff"
        reason = "cost-sensitive winner differs from quality winner"
    else:
        status = "investigate_further"
        reason = "quality, stability and ranking winners are not aligned"

    return {
        "experiment": benchmark.get("experiment"),
        "best_variant": best_variant,
        "best_by_quality": best_by_quality,
        "best_by_stability": best_by_stability,
        "status": status,
        "reason": reason,
    }


def _derive_overall_status(experiments: list[dict[str, Any]]) -> str:
    statuses = {item.get("status") for item in experiments}
    if statuses == {"recommend_adopt"}:
        return "recommend_adopt"
    if "investigate_further" in statuses:
        return "investigate_further"
    return "review_cost_tradeoff"


def _build_conclusion_payload(
    *,
    pool_name: str,
    benchmark_payload: dict[str, Any],
) -> dict[str, Any]:
    experiments = [
        _derive_experiment_conclusion(item)
        for item in benchmark_payload.get("benchmarks", [])
    ]
    return {
        "pool": pool_name,
        "overall_status": _derive_overall_status(experiments),
        "experiments": experiments,
    }


def _render_markdown_report(
    *,
    pool_name: str,
    summary_text: str,
    conclusion_payload: dict[str, Any],
) -> str:
    title = pool_name.replace("_", " ").replace("-", " ").title()
    lines = [
        f"# {title}",
        "",
        f"overall_status: {conclusion_payload['overall_status']}",
        "",
        "## Experiments",
    ]
    for item in conclusion_payload.get("experiments", []):
        lines.extend(
            [
                f"- {item['experiment']}: {item['status']}",
                f"  best_variant={item['best_variant']}",
                f"  best_by_quality={item['best_by_quality']}",
                f"  best_by_stability={item['best_by_stability']}",
                f"  reason={item['reason']}",
            ]
        )
    lines.extend(["", "## Summary", "", summary_text.rstrip(), ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pool", required=True, help="Strategy pool manifest path")
    parser.add_argument(
        "--config-root",
        default="configs",
        help="Config root path used for compatibility checks",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Emit shortlist and planned commands without executing benchmark",
    )
    parser.add_argument("--runs-root", default="runs", help="Runs root path")
    parser.add_argument(
        "--candidates-root", default="candidates", help="Candidates root path"
    )
    parser.add_argument(
        "--output-dir",
        default="reports/contextatlas_first_pass",
        help="Directory for generated benchmark outputs",
    )
    args = parser.parse_args()

    pool_path = Path(args.pool).resolve()
    pool = _resolve_pool_paths(_read_json(pool_path), pool_path)
    config_root = Path(args.config_root).resolve()

    shortlist = shortlist_strategy_cards(
        strategy_card_paths=[Path(path) for path in pool.get("strategy_cards", [])],
        config_root=config_root,
        profile_name=str(pool["profile"]),
        project_name=str(pool["project"]),
    )
    decision_policy = pool.get("decision_policy") or {}
    prefer_status = [
        str(item) for item in decision_policy.get("prefer_status", ["executable"])
    ]
    payload = {
        "pool": pool["name"],
        "shortlist": shortlist,
        "recommended_cards": _recommended_cards(shortlist, prefer_status),
        "commands": _build_commands(pool, config_root),
    }

    if args.dry_run:
        print(json.dumps(payload))
        return

    runs_root = Path(args.runs_root).resolve()
    candidates_root = Path(args.candidates_root).resolve()
    output_dir = Path(args.output_dir).resolve()

    benchmark_payload = run_benchmark_suite(
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        profile_name=str(pool["profile"]),
        project_name=str(pool["project"]),
        task_set_path=Path(str(pool["task_set"])),
        suite_path=Path(str(pool["suite"])),
    )

    suite_output_path = output_dir / f"{pool['name']}_benchmark_suite.json"
    suite_output_file = _write_artifact(
        suite_output_path, json.dumps(benchmark_payload, indent=2)
    )
    summary_script = Path(str(pool["summary_script"]))
    summary_text = _render_summary(suite_output_path, summary_script)
    summary_output_path = output_dir / f"{pool['name']}_summary.txt"
    summary_output_file = _write_artifact(summary_output_path, summary_text)
    conclusion_payload = _build_conclusion_payload(
        pool_name=str(pool["name"]),
        benchmark_payload=benchmark_payload,
    )
    conclusion_output_path = output_dir / f"{pool['name']}_conclusion.json"
    conclusion_output_file = _write_artifact(
        conclusion_output_path, json.dumps(conclusion_payload, indent=2)
    )
    report_output_path = output_dir / f"{pool['name']}_report.md"
    report_output_file = _write_artifact(
        report_output_path,
        _render_markdown_report(
            pool_name=str(pool["name"]),
            summary_text=summary_text,
            conclusion_payload=conclusion_payload,
        ),
    )

    payload["executed"] = True
    payload["artifacts"] = {
        "benchmark_suite_output": suite_output_file,
        "summary_output": summary_output_file,
        "conclusion_output": conclusion_output_file,
        "report_output": report_output_file,
    }
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
