from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from meta_harness.benchmark import run_benchmark, run_benchmark_suite
from meta_harness.compaction import compact_runs


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


def observe_benchmark_payload(
    *,
    profile_name: str,
    project_name: str,
    task_set_path: Path,
    spec_path: Path,
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
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
    return payload


def observe_benchmark_suite_payload(
    *,
    profile_name: str,
    project_name: str,
    task_set_path: Path,
    suite_path: Path,
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
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
    return payload
