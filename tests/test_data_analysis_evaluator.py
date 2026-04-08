from __future__ import annotations

import json
from pathlib import Path

import pytest

from meta_harness.data_analysis_evaluator import evaluate_data_analysis_run
from meta_harness.scoring import score_run


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_steps(task_dir: Path, latency_ms: int, extra_events: list[dict] | None = None) -> None:
    events = [
        {
            "step_id": "step-1",
            "phase": "analyze",
            "status": "completed",
            "latency_ms": latency_ms,
        }
    ]
    if extra_events:
        events.extend(extra_events)
    (task_dir / "steps.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )


def make_run(run_dir: Path) -> None:
    write_json(
        run_dir / "run_metadata.json",
        {"run_id": run_dir.name, "profile": "workflow", "project": "demo"},
    )


def make_data_analysis_task(
    run_dir: Path,
    *,
    task_id: str = "analyze-sales",
    success: bool = True,
    latency_ms: int = 140,
    report_text: str,
    summary: dict,
    required_fields: list[str],
    plan_step_count: int = 3,
    retry_count: int = 0,
    role: str = "hot_path",
    fingerprints: dict | None = None,
    expected_signals: dict | None = None,
    method_id: str | None = None,
    binding_id: str | None = None,
    binding_payload: dict | None = None,
    binding_artifacts: list[str] | None = None,
    token_total: int | None = None,
    assistant_reply: bool = False,
) -> None:
    task_dir = run_dir / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        task_dir / "task_result.json",
        {
            "task_id": task_id,
            "scenario": "data_analysis",
            "success": success,
            "completed_phases": 1 if success else 0,
            "failed_phase": None if success else "analyze",
            **({"method_id": method_id} if method_id is not None else {}),
            **({"binding_id": binding_id} if binding_id is not None else {}),
            **({"binding_payload": binding_payload} if binding_payload is not None else {}),
            **({"binding_artifacts": binding_artifacts} if binding_artifacts is not None else {}),
            "expectations": {
                "primitive_id": "data_analysis",
                "role": role,
                "required_fields": required_fields,
                "latency_budget_ms": 800,
                "quality_thresholds": {
                    "field_completeness": 0.8,
                    "grounded_field_rate": 0.75,
                },
                **(
                    {"expected_signals": expected_signals}
                    if expected_signals is not None
                    else {}
                ),
            },
        },
    )
    (task_dir / "analysis_report.md").write_text(report_text, encoding="utf-8")
    write_json(task_dir / "analysis_summary.json", summary)
    for artifact_name in binding_artifacts or []:
        write_json(task_dir / artifact_name, binding_payload or {})
    write_json(
        task_dir / "benchmark_probe.stdout.txt",
        {
            **({"fingerprints": fingerprints} if fingerprints is not None else {}),
            "probes": {
                "analysis.plan_step_count": plan_step_count,
                "analysis.retry_count": retry_count,
            },
        },
    )
    extra_events: list[dict] = []
    if binding_artifacts or token_total is not None:
        extra_events.append(
            {
                "step_id": "step-0",
                "phase": "binding_analyze",
                "status": "completed",
                "artifact_refs": binding_artifacts,
                "token_usage": {"total": token_total} if token_total is not None else None,
                "model": binding_id.split("/")[1] if isinstance(binding_id, str) and "/" in binding_id else None,
                "latency_ms": 0,
            }
        )
    if assistant_reply:
        extra_events.append(
            {
                "step_id": "step-2",
                "phase": "assistant_reply",
                "status": "completed",
                "artifact_refs": binding_artifacts,
                "token_usage": {"total": token_total} if token_total is not None else None,
                "model": binding_id.split("/")[1] if isinstance(binding_id, str) and "/" in binding_id else None,
                "latency_ms": 0,
            }
        )
    write_steps(task_dir, latency_ms=latency_ms, extra_events=extra_events)


def test_evaluate_data_analysis_run_scores_quality_latency_and_probes(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run-data-analysis"
    make_run(run_dir)
    make_data_analysis_task(
        run_dir,
        report_text=(
            "Revenue increased by 12%. Top region is APAC. "
            "Average order value is $42."
        ),
        summary={
            "headline": "Revenue increased by 12%",
            "top_region": "APAC",
            "average_order_value": "$42",
        },
        required_fields=["headline", "top_region", "average_order_value"],
        fingerprints={"analysis.mode": "sample_then_plan"},
        expected_signals={
            "fingerprints": {"analysis.mode": "sample_then_plan"},
            "probes": {"analysis.retry_count": {"max": 1}},
        },
    )

    report = evaluate_data_analysis_run(run_dir)

    assert report["correctness"]["task_success_rate"] == pytest.approx(1.0)
    assert report["correctness"]["task_grounded_success_rate"] == pytest.approx(1.0)
    assert report["cost"]["data_analysis_latency_ms"] == pytest.approx(140.0)
    assert report["capability_scores"]["data_analysis"] == {
        "success_rate": 1.0,
        "latency_ms": 140.0,
        "summary_valid_rate": 1.0,
        "field_completeness": 1.0,
        "grounded_field_rate": 1.0,
    }
    assert report["workflow_scores"] == {
        "hot_path_success_rate": 1.0,
        "fallback_rate": 0.0,
    }
    assert report["probes"] == {
        "analysis.mode": "sample_then_plan",
        "analysis.plan_step_count": 3.0,
        "analysis.retry_count": 0.0,
    }
    assert report["architecture"]["expected_signal_validation"] == {
        "expected_signals_satisfied": True,
        "missing_signals": [],
        "mismatch_signals": [],
    }


def test_evaluate_data_analysis_run_reports_binding_transfer_signals(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run-data-transfer"
    make_run(run_dir)
    make_data_analysis_task(
        run_dir,
        report_text=(
            "Revenue increased by 12%. Top region is APAC. "
            "Average order value is $42."
        ),
        summary={
            "headline": "Revenue increased by 12%",
            "top_region": "APAC",
            "average_order_value": "$42",
        },
        required_fields=["headline", "top_region", "average_order_value"],
        method_id="data_analysis/sample_then_plan",
        binding_id="openclaw/claude/data_analysis",
        binding_payload={"reply": "analysis complete", "usage": {"totalTokens": 210}},
        binding_artifacts=["analyze.binding_payload.json"],
        token_total=210,
        assistant_reply=True,
    )

    report = evaluate_data_analysis_run(run_dir)

    capability = report["capability_scores"]["data_analysis"]
    assert capability["binding_payload_rate"] == pytest.approx(1.0)
    assert capability["assistant_reply_rate"] == pytest.approx(1.0)
    assert capability["artifact_coverage_rate"] == pytest.approx(1.0)
    assert capability["binding_token_total"] == pytest.approx(210.0)
    assert report["workflow_scores"]["binding_execution_rate"] == pytest.approx(1.0)
    assert report["workflow_scores"]["method_trace_coverage_rate"] == pytest.approx(1.0)
    assert report["probes"]["data_analysis.binding_payload_present_rate"] == pytest.approx(1.0)
    assert report["probes"]["data_analysis.assistant_reply_rate"] == pytest.approx(1.0)
    assert report["probes"]["data_analysis.binding_token_total"] == pytest.approx(210.0)


def test_score_run_executes_relative_data_analysis_script_from_source_repo(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    run_dir = tmp_path / "runs" / "run-data-pack"
    make_run(run_dir)
    make_data_analysis_task(
        run_dir,
        report_text=(
            "Revenue increased by 12%. Top region is APAC. "
            "Average order value is $42."
        ),
        summary={
            "headline": "Revenue increased by 12%",
            "top_region": "APAC",
            "average_order_value": "$42",
        },
        required_fields=["headline", "top_region", "average_order_value"],
    )
    write_json(
        run_dir / "effective_config.json",
        {
            "runtime": {"workspace": {"source_repo": str(repo_root)}},
            "evaluation": {
                "evaluators": ["command"],
                "command_evaluators": [
                    {
                        "name": "data_analysis/core",
                        "command": ["python", "scripts/eval_data_analysis.py"],
                    }
                ],
            },
        },
    )

    report = score_run(run_dir)

    assert report["capability_scores"]["data_analysis"]["success_rate"] == pytest.approx(1.0)
    assert report["capability_scores"]["data_analysis"]["grounded_field_rate"] == pytest.approx(1.0)
    assert report["cost"]["command_evaluators_run"] == 1
