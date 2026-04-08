from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meta_harness.evaluators import get_evaluator
from meta_harness.schemas import EvaluatorRun, TraceEvent
from meta_harness.services.run_query_service import list_trace_events
from meta_harness.services.trace_service import grade_trace_events


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
        started_at = datetime.now(UTC)
        started_perf = time.perf_counter()
        trace_artifact = f"runs/{run_dir.name}/evaluators/{evaluator_name}.trace.jsonl"
        _append_evaluator_trace_event(
            run_dir,
            evaluator_name=evaluator_name,
            status="started",
            started_at=started_at,
        )
        try:
            report = get_evaluator(evaluator_name).evaluate(
                run_dir, evaluation_config=evaluation_config
            )
        except Exception as exc:
            _append_evaluator_trace_event(
                run_dir,
                evaluator_name=evaluator_name,
                status="failed",
                started_at=started_at,
                duration_ms=int((time.perf_counter() - started_perf) * 1000),
                error=str(exc),
            )
            raise
        trace_grade = grade_trace_events(
            run_id=run_dir.name,
            events=list_trace_events(run_dir.parent, run_dir.name),
        )
        completed_at = datetime.now(UTC)
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        profiling = _build_evaluator_profiling(run_dir, evaluator_name)
        envelope = EvaluatorRun(
            evaluator_name=evaluator_name,
            run_id=run_dir.name,
            status="completed",
            report=report,
            trace_grade=trace_grade,
            profiling=profiling,
            trace_artifact=trace_artifact,
            duration_ms=duration_ms,
            artifact_refs=[
                f"runs/{run_dir.name}/evaluators/{evaluator_name}.json",
                f"runs/{run_dir.name}/score_report.json",
            ],
            started_at=started_at,
            completed_at=completed_at,
        )
        envelope_payload = envelope.model_dump(mode="json")
        for key, value in report.items():
            envelope_payload.setdefault(key, value)
        (evaluators_dir / f"{evaluator_name}.json").write_text(
            json.dumps(envelope_payload, indent=2),
            encoding="utf-8",
        )
        _append_evaluator_trace_event(
            run_dir,
            evaluator_name=evaluator_name,
            status="completed",
            started_at=started_at,
            duration_ms=duration_ms,
            artifact_refs=envelope.artifact_refs,
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


def _build_evaluator_profiling(run_dir: Path, evaluator_name: str) -> dict[str, Any]:
    events = list_trace_events(run_dir.parent, run_dir.name)
    profiling = {
        "input_task_count": len(
            [path for path in (run_dir / "tasks").iterdir() if path.is_dir()]
        )
        if (run_dir / "tasks").exists()
        else 0,
        "input_trace_event_count": len(events),
        "completed_trace_event_count": sum(
            1 for event in events if str(event.get("status") or "") == "completed"
        ),
        "failed_trace_event_count": sum(
            1 for event in events if str(event.get("status") or "") == "failed"
        ),
    }
    if evaluator_name == "command":
        profiling["commands"] = _load_command_profiling(run_dir)
        profiling["command_count"] = len(profiling["commands"])
    return profiling


def _load_command_profiling(run_dir: Path) -> list[dict[str, Any]]:
    command_artifacts_dir = run_dir / "evaluators" / "command_artifacts"
    if not command_artifacts_dir.exists():
        return []
    commands: list[dict[str, Any]] = []
    for metadata_path in sorted(command_artifacts_dir.glob("*/metadata.json")):
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        commands.append(
            {
                "name": payload.get("name"),
                "command": payload.get("command", []),
                "returncode": payload.get("returncode"),
                "duration_ms": payload.get("duration_ms"),
                "artifact_dir": str(metadata_path.parent.resolve()),
            }
        )
    return commands


def _append_evaluator_trace_event(
    run_dir: Path,
    *,
    evaluator_name: str,
    status: str,
    started_at: datetime,
    duration_ms: int | None = None,
    artifact_refs: list[str] | None = None,
    error: str | None = None,
) -> None:
    trace_path = run_dir / "evaluators" / f"{evaluator_name}.trace.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {}
    metadata_path = run_dir / "run_metadata.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    event = TraceEvent(
        step_id=f"evaluator:{evaluator_name}:{status}",
        phase=f"evaluator.{evaluator_name}",
        status=status,
        run_id=str(metadata.get("run_id") or run_dir.name),
        task_id="__score__",
        session_ref=f"session://{str(metadata.get('run_id') or run_dir.name)}/evaluators/{evaluator_name}",
        candidate_id=(
            str(metadata["candidate_id"]) if metadata.get("candidate_id") is not None else None
        ),
        artifact_refs=artifact_refs,
        latency_ms=duration_ms,
        error=error,
        timestamp=started_at if status == "started" else datetime.now(UTC),
    )
    with trace_path.open("a", encoding="utf-8") as handle:
        handle.write(event.model_dump_json())
        handle.write("\n")
