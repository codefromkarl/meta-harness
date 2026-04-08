from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from meta_harness.benchmark_engine import run_benchmark, run_benchmark_suite
from meta_harness.compaction import compact_runs


def _artifact_path_for_report(*, reports_root: Path, output_path: Path) -> str:
    return str(output_path.relative_to(reports_root.parent))


def write_benchmark_report(*, reports_root: Path, payload: dict[str, Any]) -> Path:
    experiment = str(payload["experiment"])
    output_path = reports_root / "benchmarks" / f"{experiment}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def write_benchmark_suite_report(*, reports_root: Path, payload: dict[str, Any]) -> Path:
    suite = str(payload["suite"])
    output_path = reports_root / "benchmark-suites" / f"{suite}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def persist_benchmark_payload(
    *,
    reports_root: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    artifact_path = payload.get("artifact_path")
    if isinstance(artifact_path, str) and artifact_path:
        return payload

    if "suite" in payload:
        output_path = write_benchmark_suite_report(reports_root=reports_root, payload=payload)
    else:
        output_path = write_benchmark_report(reports_root=reports_root, payload=payload)

    result = dict(payload)
    result["artifact_path"] = _artifact_path_for_report(
        reports_root=reports_root,
        output_path=output_path,
    )
    return result


def observe_benchmark_payload(
    *,
    profile_name: str,
    project_name: str,
    task_set_path: Path,
    spec_path: Path,
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    reports_root: Path = Path("reports"),
    focus: str | None = None,
    auto_compact_runs: bool = True,
    include_artifacts: bool = False,
    compactable_statuses: list[str] | None = None,
    cleanup_auxiliary_dirs: bool = True,
    compact_runs_fn: Callable[..., dict[str, Any]] = compact_runs,
) -> dict[str, Any]:
    payload = run_benchmark(
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        profile_name=profile_name,
        project_name=project_name,
        task_set_path=task_set_path,
        spec_path=spec_path,
        focus=focus,
    )
    if auto_compact_runs:
        payload["run_compaction"] = compact_runs_fn(
            runs_root,
            candidates_root=candidates_root,
            include_artifacts=include_artifacts,
            compactable_statuses=compactable_statuses,
            cleanup_auxiliary_dirs=cleanup_auxiliary_dirs,
        )
    return persist_benchmark_payload(reports_root=reports_root, payload=payload)


def observe_benchmark_suite_payload(
    *,
    profile_name: str,
    project_name: str,
    task_set_path: Path,
    suite_path: Path,
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    reports_root: Path = Path("reports"),
    auto_compact_runs: bool = True,
    include_artifacts: bool = False,
    compactable_statuses: list[str] | None = None,
    cleanup_auxiliary_dirs: bool = True,
    compact_runs_fn: Callable[..., dict[str, Any]] = compact_runs,
) -> dict[str, Any]:
    payload = run_benchmark_suite(
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        profile_name=profile_name,
        project_name=project_name,
        task_set_path=task_set_path,
        suite_path=suite_path,
    )
    if auto_compact_runs:
        payload["run_compaction"] = compact_runs_fn(
            runs_root,
            candidates_root=candidates_root,
            include_artifacts=include_artifacts,
            compactable_statuses=compactable_statuses,
            cleanup_auxiliary_dirs=cleanup_auxiliary_dirs,
        )
    return persist_benchmark_payload(reports_root=reports_root, payload=payload)
