from __future__ import annotations

import json
from pathlib import Path

import pytest

from meta_harness.scoring import score_run
from meta_harness.web_scrape_evaluator import evaluate_web_scrape_run


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_steps(task_dir: Path, latency_ms: int, extra_events: list[dict] | None = None) -> None:
    events = [
        {
            "step_id": "step-1",
            "phase": "fetch",
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


def make_web_scrape_task(
    run_dir: Path,
    *,
    task_id: str = "fetch-homepage",
    success: bool = True,
    latency_ms: int = 120,
    page_html: str,
    extracted: dict,
    required_fields: list[str],
    retry_count: int = 1,
    navigation_depth: int = 2,
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
            "scenario": "web_scrape",
            "success": success,
            "completed_phases": 1 if success else 0,
            "failed_phase": None if success else "fetch",
            **({"method_id": method_id} if method_id is not None else {}),
            **({"binding_id": binding_id} if binding_id is not None else {}),
            **({"binding_payload": binding_payload} if binding_payload is not None else {}),
            **({"binding_artifacts": binding_artifacts} if binding_artifacts is not None else {}),
            "expectations": {
                "primitive_id": "web_scrape",
                "role": role,
                "required_fields": required_fields,
                "latency_budget_ms": 500,
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
    (task_dir / "page.html").write_text(page_html, encoding="utf-8")
    write_json(task_dir / "extracted.json", extracted)
    for artifact_name in binding_artifacts or []:
        write_json(task_dir / artifact_name, binding_payload or {})
    write_json(
        task_dir / "benchmark_probe.stdout.txt",
        {
            **({"fingerprints": fingerprints} if fingerprints is not None else {}),
            "probes": {
                "scrape.navigation_depth": navigation_depth,
                "scrape.retry_count": retry_count,
            }
        },
    )
    extra_events: list[dict] = []
    if binding_artifacts or token_total is not None:
        extra_events[0:0] = [
            {
                "step_id": "step-0",
                "phase": "binding_fetch",
                "status": "completed",
                "artifact_refs": binding_artifacts,
                "token_usage": {"total": token_total} if token_total is not None else None,
                "model": binding_id.split("/")[1] if isinstance(binding_id, str) and "/" in binding_id else None,
                "latency_ms": 0,
            }
        ]
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


def make_run(run_dir: Path) -> None:
    write_json(
        run_dir / "run_metadata.json",
        {"run_id": run_dir.name, "profile": "workflow", "project": "demo"},
    )


def test_evaluate_web_scrape_run_scores_quality_latency_and_probes(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-web-scrape"
    make_run(run_dir)
    make_web_scrape_task(
        run_dir,
        page_html="""
        <html>
          <body>
            <h1>Example Company</h1>
            <div>Price: $19</div>
            <div>Email: contact@example.com</div>
          </body>
        </html>
        """,
        extracted={
            "title": "Example Company",
            "price": "$19",
            "contact_email": "contact@example.com",
        },
        required_fields=["title", "price", "contact_email"],
        fingerprints={"scrape.mode": "fast"},
        expected_signals={
            "fingerprints": {"scrape.mode": "fast"},
            "probes": {"scrape.retry_count": {"max": 3}},
        },
    )

    report = evaluate_web_scrape_run(run_dir)

    assert report["correctness"]["task_success_rate"] == pytest.approx(1.0)
    assert report["correctness"]["task_grounded_success_rate"] == pytest.approx(1.0)
    assert report["cost"]["web_scrape_latency_ms"] == pytest.approx(120.0)
    assert report["capability_scores"]["web_scrape"] == {
        "success_rate": 1.0,
        "latency_ms": 120.0,
        "schema_valid_rate": 1.0,
        "field_completeness": 1.0,
        "grounded_field_rate": 1.0,
    }
    assert report["architecture"]["expected_signal_validation"] == {
        "expected_signals_satisfied": True,
        "missing_signals": [],
        "mismatch_signals": [],
    }
    assert report["workflow_scores"] == {
        "hot_path_success_rate": 1.0,
        "fallback_rate": 0.0,
    }
    assert report["probes"] == {
        "scrape.mode": "fast",
        "scrape.navigation_depth": 2.0,
        "scrape.retry_count": 1.0,
    }
    assert report["composite_adjustment"] > 0.5


def test_evaluate_web_scrape_run_penalizes_missing_and_ungrounded_fields(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-web-scrape-poor"
    make_run(run_dir)
    make_web_scrape_task(
        run_dir,
        latency_ms=980,
        page_html="""
        <html>
          <body>
            <div>Price: $19</div>
          </body>
        </html>
        """,
        extracted={
            "title": "Hallucinated Company",
            "price": "$19",
        },
        required_fields=["title", "price", "contact_email"],
        retry_count=4,
        navigation_depth=5,
        expected_signals={
            "fingerprints": {"scrape.mode": "fast"},
            "probes": {"scrape.retry_count": {"max": 3}},
        },
    )

    report = evaluate_web_scrape_run(run_dir)

    capability = report["capability_scores"]["web_scrape"]
    assert capability["success_rate"] == pytest.approx(1.0)
    assert capability["field_completeness"] == pytest.approx(2 / 3, rel=1e-3)
    assert capability["grounded_field_rate"] == pytest.approx(0.5)
    assert report["architecture"]["expected_signal_validation"] == {
        "expected_signals_satisfied": False,
        "missing_signals": ["fingerprints.scrape.mode"],
        "mismatch_signals": ["probes.scrape.retry_count"],
    }
    assert report["correctness"]["task_grounded_success_rate"] == pytest.approx(0.0)
    assert report["probes"] == {
        "scrape.navigation_depth": 5.0,
        "scrape.retry_count": 4.0,
    }
    assert report["composite_adjustment"] < 0.5


def test_score_run_executes_relative_web_scrape_script_from_source_repo(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    run_dir = tmp_path / "runs" / "run-web-pack"
    make_run(run_dir)
    make_web_scrape_task(
        run_dir,
        page_html="""
        <html>
          <body>
            <h1>Example Company</h1>
            <div>Price: $19</div>
            <div>Email: contact@example.com</div>
          </body>
        </html>
        """,
        extracted={
            "title": "Example Company",
            "price": "$19",
            "contact_email": "contact@example.com",
        },
        required_fields=["title", "price", "contact_email"],
    )
    write_json(
        run_dir / "effective_config.json",
        {
            "runtime": {
                "workspace": {
                    "source_repo": str(repo_root),
                }
            },
            "evaluation": {
                "evaluators": ["command"],
                "command_evaluators": [
                    {
                        "name": "web_scrape/core",
                        "command": ["python", "scripts/eval_web_scrape.py"],
                    }
                ],
            },
        },
    )

    report = score_run(run_dir)

    assert report["capability_scores"]["web_scrape"]["success_rate"] == pytest.approx(1.0)
    assert report["capability_scores"]["web_scrape"]["grounded_field_rate"] == pytest.approx(
        1.0
    )
    assert report["cost"]["command_evaluators_run"] == 1


def test_evaluate_web_scrape_run_reports_binding_and_method_transfer_signals(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "run-web-transfer"
    make_run(run_dir)
    make_web_scrape_task(
        run_dir,
        page_html="""
        <html>
          <body>
            <h1>Example Company</h1>
            <div>Price: $19</div>
            <div>Email: contact@example.com</div>
          </body>
        </html>
        """,
        extracted={
            "title": "Example Company",
            "price": "$19",
            "contact_email": "contact@example.com",
        },
        required_fields=["title", "price", "contact_email"],
        method_id="web_scrape/fast_path",
        binding_id="openclaw/claude/web_scrape",
        binding_payload={
            "reply": "capture complete",
            "usage": {"totalTokens": 321},
        },
        binding_artifacts=["fetch.binding_payload.json"],
        token_total=321,
        assistant_reply=True,
    )

    report = evaluate_web_scrape_run(run_dir)

    assert report["capability_scores"]["web_scrape"]["binding_payload_rate"] == pytest.approx(1.0)
    assert report["capability_scores"]["web_scrape"]["assistant_reply_rate"] == pytest.approx(1.0)
    assert report["capability_scores"]["web_scrape"]["artifact_coverage_rate"] == pytest.approx(1.0)
    assert report["capability_scores"]["web_scrape"]["binding_token_total"] == pytest.approx(321.0)
    assert report["workflow_scores"]["binding_execution_rate"] == pytest.approx(1.0)
    assert report["workflow_scores"]["method_trace_coverage_rate"] == pytest.approx(1.0)
    assert report["probes"]["web_scrape.binding_payload_present_rate"] == pytest.approx(1.0)
    assert report["probes"]["web_scrape.assistant_reply_rate"] == pytest.approx(1.0)
    assert report["probes"]["web_scrape.binding_token_total"] == pytest.approx(321.0)
