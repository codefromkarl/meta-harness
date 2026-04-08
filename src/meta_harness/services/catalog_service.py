from __future__ import annotations

from pathlib import Path
from typing import Any

from meta_harness.catalog import (
    archive_candidates,
    archive_runs,
    build_candidate_index,
    build_run_index,
    candidate_archive_view,
    candidate_current_view,
    prune_candidates,
    prune_runs,
    run_archive_view,
    run_current_view,
)


def build_run_index_payload(
    *,
    runs_root: Path,
    candidates_root: Path | None = None,
) -> dict[str, Any]:
    return build_run_index(runs_root, candidates_root=candidates_root)


def build_candidate_index_payload(
    *,
    candidates_root: Path,
    runs_root: Path | None = None,
) -> dict[str, Any]:
    return build_candidate_index(candidates_root, runs_root=runs_root)


def run_current_view_payload(
    *,
    runs_root: Path,
    candidates_root: Path | None = None,
) -> dict[str, Any]:
    return run_current_view(runs_root, candidates_root=candidates_root)


def run_archive_view_payload(
    *,
    runs_root: Path,
    candidates_root: Path | None = None,
) -> dict[str, Any]:
    return run_archive_view(runs_root, candidates_root=candidates_root)


def candidate_current_view_payload(
    *,
    candidates_root: Path,
    runs_root: Path | None = None,
) -> dict[str, Any]:
    return candidate_current_view(candidates_root, runs_root=runs_root)


def candidate_archive_view_payload(
    *,
    candidates_root: Path,
    runs_root: Path | None = None,
) -> dict[str, Any]:
    return candidate_archive_view(candidates_root, runs_root=runs_root)


def archive_runs_payload(
    *,
    runs_root: Path,
    archive_root: Path,
    candidates_root: Path | None = None,
    cleanup_log_retention: int | None = None,
    dry_run: bool = False,
    experiment: str | None = None,
    benchmark_family: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    return archive_runs(
        runs_root,
        archive_root=archive_root,
        candidates_root=candidates_root,
        cleanup_log_retention=cleanup_log_retention,
        dry_run=dry_run,
        experiment=experiment,
        benchmark_family=benchmark_family,
        status=status,
    )


def prune_runs_payload(
    *,
    runs_root: Path,
    archive_root: Path,
    candidates_root: Path | None = None,
    cleanup_log_retention: int | None = None,
    dry_run: bool = False,
    experiment: str | None = None,
    benchmark_family: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    return prune_runs(
        runs_root,
        candidates_root=candidates_root,
        archive_root=archive_root,
        cleanup_log_retention=cleanup_log_retention,
        dry_run=dry_run,
        experiment=experiment,
        benchmark_family=benchmark_family,
        status=status,
    )


def archive_candidates_payload(
    *,
    candidates_root: Path,
    archive_root: Path,
    runs_root: Path | None = None,
    cleanup_log_retention: int | None = None,
    dry_run: bool = False,
    experiment: str | None = None,
    benchmark_family: str | None = None,
) -> dict[str, Any]:
    return archive_candidates(
        candidates_root,
        archive_root=archive_root,
        runs_root=runs_root,
        cleanup_log_retention=cleanup_log_retention,
        dry_run=dry_run,
        experiment=experiment,
        benchmark_family=benchmark_family,
    )


def prune_candidates_payload(
    *,
    candidates_root: Path,
    archive_root: Path,
    runs_root: Path | None = None,
    cleanup_log_retention: int | None = None,
    dry_run: bool = False,
    experiment: str | None = None,
    benchmark_family: str | None = None,
) -> dict[str, Any]:
    return prune_candidates(
        candidates_root,
        runs_root=runs_root,
        archive_root=archive_root,
        cleanup_log_retention=cleanup_log_retention,
        dry_run=dry_run,
        experiment=experiment,
        benchmark_family=benchmark_family,
    )
