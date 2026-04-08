from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any
from datetime import datetime, timezone
from uuid import uuid4

_DEFAULT_CLEANUP_LOG_RETENTION = 10


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _benchmark_family(experiment: str | None) -> str | None:
    if not experiment:
        return None
    prefix = "benchmark_"
    if experiment.startswith(prefix):
        return experiment[len(prefix) :]
    return experiment


def _load_candidate_lookup(candidates_root: Path | None) -> dict[str, dict[str, Any]]:
    if candidates_root is None or not candidates_root.exists():
        return {}
    lookup: dict[str, dict[str, Any]] = {}
    for candidate_dir in sorted(
        path for path in candidates_root.iterdir() if path.is_dir()
    ):
        metadata_path = candidate_dir / "candidate.json"
        if not metadata_path.exists():
            continue
        metadata = _read_json(metadata_path)
        proposal_path = candidate_dir / "proposal.json"
        proposal = _read_json(proposal_path) if proposal_path.exists() else None
        lookup[str(metadata.get("candidate_id", candidate_dir.name))] = {
            "metadata": metadata,
            "proposal": proposal,
        }
    return lookup


def build_run_index(
    runs_root: Path, *, candidates_root: Path | None = None
) -> dict[str, Any]:
    candidate_lookup = _load_candidate_lookup(candidates_root)
    runs: list[dict[str, Any]] = []
    for run_dir in sorted(path for path in runs_root.iterdir() if path.is_dir()):
        metadata_path = run_dir / "run_metadata.json"
        effective_config_path = run_dir / "effective_config.json"
        if not metadata_path.exists() or not effective_config_path.exists():
            continue
        metadata = _read_json(metadata_path)
        score_path = run_dir / "score_report.json"
        score = _read_json(score_path) if score_path.exists() else None

        task_results = []
        tasks_dir = run_dir / "tasks"
        if tasks_dir.exists():
            for task_dir in sorted(
                path for path in tasks_dir.iterdir() if path.is_dir()
            ):
                task_result_path = task_dir / "task_result.json"
                if task_result_path.exists():
                    task_results.append(_read_json(task_result_path))

        success_flags = [bool(item.get("success")) for item in task_results]
        if task_results and all(success_flags) and score is not None:
            status = "valid"
            tags = ["scored", "successful"]
        elif task_results and not any(success_flags) and score is None:
            status = "failed"
            tags = ["failed"]
        elif task_results and not all(success_flags):
            status = "partial"
            tags = ["partial"]
            if score is not None:
                tags.insert(0, "scored")
        else:
            status = "unknown"
            tags = []

        runs.append(
            {
                "run_id": run_dir.name,
                "profile": metadata.get("profile"),
                "project": metadata.get("project"),
                "candidate_id": metadata.get("candidate_id"),
                "created_at": metadata.get("created_at"),
                "status": status,
                "tags": tags,
                "composite": score.get("composite")
                if isinstance(score, dict)
                else None,
                "experiment": (
                    (
                        (
                            candidate_lookup.get(str(metadata.get("candidate_id")))
                            or {}
                        ).get("proposal")
                        or {}
                    ).get("experiment")
                    if metadata.get("candidate_id") is not None
                    else None
                ),
                "variant": (
                    (
                        (
                            candidate_lookup.get(str(metadata.get("candidate_id")))
                            or {}
                        ).get("proposal")
                        or {}
                    ).get("variant")
                    if metadata.get("candidate_id") is not None
                    else None
                ),
            }
        )

    for item in runs:
        item["benchmark_family"] = _benchmark_family(item.get("experiment"))

    latest_valid_by_experiment: dict[str, str] = {}
    current_recommended_run_by_experiment: dict[str, str] = {}
    valid_runs_by_experiment: dict[str, list[dict[str, Any]]] = {}
    valid_runs_by_variant: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in runs:
        experiment = item.get("experiment")
        if item.get("status") != "valid" or not experiment:
            continue
        valid_runs_by_experiment.setdefault(str(experiment), []).append(item)
        variant = item.get("variant")
        if isinstance(variant, str) and variant:
            valid_runs_by_variant.setdefault((str(experiment), variant), []).append(
                item
            )
    for experiment, items in valid_runs_by_experiment.items():
        latest = max(items, key=lambda item: str(item.get("created_at") or ""))
        latest_valid_by_experiment[experiment] = str(latest["run_id"])
        best = max(
            items,
            key=lambda item: (
                float(item.get("composite") or 0.0),
                str(item.get("created_at") or ""),
            ),
        )
        current_recommended_run_by_experiment[experiment] = str(best["run_id"])

    for (_, _), items in valid_runs_by_variant.items():
        if len(items) < 2:
            continue
        latest = max(items, key=lambda item: str(item.get("created_at") or ""))
        for item in items:
            if item["run_id"] == latest["run_id"]:
                continue
            item["status"] = "superseded"
            item["superseded_by_run_id"] = latest["run_id"]

    payload = {
        "summary": {
            "total_runs": len(runs),
            "valid_runs": sum(1 for item in runs if item["status"] == "valid"),
            "failed_runs": sum(1 for item in runs if item["status"] == "failed"),
            "partial_runs": sum(1 for item in runs if item["status"] == "partial"),
        },
        "latest_valid_by_experiment": latest_valid_by_experiment,
        "current_recommended_run_by_experiment": current_recommended_run_by_experiment,
        "runs": runs,
    }
    (runs_root / "_index.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    return payload


def build_candidate_index(
    candidates_root: Path, *, runs_root: Path | None = None
) -> dict[str, Any]:
    champions_path = candidates_root / "champions.json"
    champions = _read_json(champions_path) if champions_path.exists() else {}
    champion_ids = set(champions.values()) if isinstance(champions, dict) else set()
    run_lookup: dict[str, list[str]] = {}
    if runs_root is not None and runs_root.exists():
        for run_dir in sorted(path for path in runs_root.iterdir() if path.is_dir()):
            metadata_path = run_dir / "run_metadata.json"
            if not metadata_path.exists():
                continue
            metadata = _read_json(metadata_path)
            candidate_id = metadata.get("candidate_id")
            if not candidate_id:
                continue
            run_lookup.setdefault(str(candidate_id), []).append(str(run_dir.name))

    candidates: list[dict[str, Any]] = []
    for candidate_dir in sorted(
        path for path in candidates_root.iterdir() if path.is_dir()
    ):
        metadata_path = candidate_dir / "candidate.json"
        effective_config_path = candidate_dir / "effective_config.json"
        if not metadata_path.exists() or not effective_config_path.exists():
            continue
        metadata = _read_json(metadata_path)
        proposal_path = candidate_dir / "proposal.json"
        proposal = _read_json(proposal_path) if proposal_path.exists() else None

        candidate_id = str(metadata.get("candidate_id", candidate_dir.name))
        tags: list[str] = []
        status = "exploratory"
        if (
            isinstance(proposal, dict)
            and proposal.get("strategy") == "benchmark_variant"
        ):
            tags.append("benchmark")
            status = "benchmark"
        if candidate_id in champion_ids:
            tags.append("champion")
            status = "champion"

        candidates.append(
            {
                "candidate_id": candidate_id,
                "profile": metadata.get("profile"),
                "project": metadata.get("project"),
                "notes": metadata.get("notes"),
                "created_at": metadata.get("created_at"),
                "status": status,
                "tags": tags,
                "experiment": proposal.get("experiment")
                if isinstance(proposal, dict)
                else None,
                "benchmark_family": _benchmark_family(
                    proposal.get("experiment") if isinstance(proposal, dict) else None
                ),
                "variant": proposal.get("variant")
                if isinstance(proposal, dict)
                else None,
                "proposal": proposal,
                "run_ids": run_lookup.get(candidate_id, []),
            }
        )

    latest_champion_by_project = dict(champions) if isinstance(champions, dict) else {}
    current_recommended_candidate_by_experiment: dict[str, str] = {}
    benchmark_candidates_by_variant: dict[tuple[str, str], list[dict[str, Any]]] = {}
    benchmark_candidates_by_experiment: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        experiment = item.get("experiment")
        variant = item.get("variant")
        if item.get("status") not in {"benchmark", "champion"} or not experiment:
            continue
        benchmark_candidates_by_experiment.setdefault(str(experiment), []).append(item)
        if isinstance(variant, str) and variant:
            benchmark_candidates_by_variant.setdefault(
                (str(experiment), variant), []
            ).append(item)

    for experiment, items in benchmark_candidates_by_experiment.items():
        best = max(
            items,
            key=lambda item: (
                len(item.get("run_ids") or []),
                str(item.get("created_at") or ""),
                str(item.get("candidate_id") or ""),
            ),
        )
        current_recommended_candidate_by_experiment[experiment] = str(
            best["candidate_id"]
        )

    for (_, _), items in benchmark_candidates_by_variant.items():
        if len(items) < 2:
            continue
        latest = max(
            items,
            key=lambda item: (
                str(item.get("created_at") or ""),
                str(item.get("candidate_id") or ""),
            ),
        )
        for item in items:
            if item["candidate_id"] == latest["candidate_id"]:
                continue
            item["status"] = "superseded"
            item["superseded_by_candidate_id"] = latest["candidate_id"]
            if "superseded" not in item["tags"]:
                item["tags"].append("superseded")

    payload = {
        "summary": {
            "total_candidates": len(candidates),
            "champion_candidates": sum(
                1 for item in candidates if item["status"] == "champion"
            ),
            "benchmark_candidates": sum(
                "benchmark" in item["tags"] for item in candidates
            ),
        },
        "latest_champion_by_project": latest_champion_by_project,
        "current_recommended_candidate_by_experiment": current_recommended_candidate_by_experiment,
        "candidates": candidates,
    }
    (candidates_root / "_index.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    return payload


def run_current_view(
    runs_root: Path, *, candidates_root: Path | None = None
) -> dict[str, Any]:
    payload = build_run_index(runs_root, candidates_root=candidates_root)
    return {
        "current_recommended_run_by_experiment": payload.get(
            "current_recommended_run_by_experiment", {}
        )
    }


def run_archive_view(
    runs_root: Path, *, candidates_root: Path | None = None
) -> dict[str, Any]:
    payload = build_run_index(runs_root, candidates_root=candidates_root)
    runs = payload.get("runs", [])
    return {
        "superseded_runs": sorted(
            item["run_id"] for item in runs if item.get("status") == "superseded"
        ),
        "failed_runs": sorted(
            item["run_id"] for item in runs if item.get("status") == "failed"
        ),
        "partial_runs": sorted(
            item["run_id"] for item in runs if item.get("status") == "partial"
        ),
    }


def _select_runs(
    runs: list[dict[str, Any]],
    *,
    experiment: str | None = None,
    benchmark_family: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for item in runs:
        if experiment is not None and item.get("experiment") != experiment:
            continue
        if (
            benchmark_family is not None
            and item.get("benchmark_family") != benchmark_family
        ):
            continue
        if status is not None and item.get("status") != status:
            continue
        selected.append(item)
    status_order = {"superseded": 0, "failed": 1, "partial": 2}
    return sorted(
        selected,
        key=lambda item: (
            status_order.get(str(item.get("status")), 99),
            str(item.get("created_at") or ""),
            str(item.get("run_id") or ""),
        ),
    )


def candidate_current_view(
    candidates_root: Path, *, runs_root: Path | None = None
) -> dict[str, Any]:
    payload = build_candidate_index(candidates_root, runs_root=runs_root)
    return {
        "current_recommended_candidate_by_experiment": payload.get(
            "current_recommended_candidate_by_experiment", {}
        )
    }


def candidate_archive_view(
    candidates_root: Path, *, runs_root: Path | None = None
) -> dict[str, Any]:
    payload = build_candidate_index(candidates_root, runs_root=runs_root)
    candidates = payload.get("candidates", [])
    return {
        "superseded_candidates": sorted(
            item["candidate_id"]
            for item in candidates
            if item.get("status") == "superseded"
        )
    }


def _select_candidates(
    candidates: list[dict[str, Any]],
    *,
    experiment: str | None = None,
    benchmark_family: str | None = None,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for item in candidates:
        if experiment is not None and item.get("experiment") != experiment:
            continue
        if (
            benchmark_family is not None
            and item.get("benchmark_family") != benchmark_family
        ):
            continue
        selected.append(item)
    return selected


def archive_runs(
    runs_root: Path,
    *,
    archive_root: Path,
    candidates_root: Path | None = None,
    cleanup_log_retention: int | None = None,
    dry_run: bool = False,
    experiment: str | None = None,
    benchmark_family: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    index_payload = build_run_index(runs_root, candidates_root=candidates_root)
    selected_runs = _select_runs(
        [
            item
            for item in index_payload.get("runs", [])
            if item.get("status") in {"superseded", "failed"}
        ],
        experiment=experiment,
        benchmark_family=benchmark_family,
        status=status,
    )
    archived: list[str] = []
    target_records: list[dict[str, Any]] = []
    archive_runs_root = archive_root / "runs"
    archive_runs_root.mkdir(parents=True, exist_ok=True)
    for item in selected_runs:
        run_id = item["run_id"]
        source = runs_root / run_id
        if not source.exists():
            continue
        archive_path = archive_runs_root / run_id
        if not dry_run:
            shutil.move(str(source), str(archive_path))
        archived.append(run_id)
        target_records.append(
            {
                "target_id": run_id,
                "target_type": "run",
                "status": item.get("status"),
                "experiment": item.get("experiment"),
                "benchmark_family": item.get("benchmark_family"),
                "variant": item.get("variant"),
                "source_path": str(source),
                "archive_path": str(archive_path),
            }
        )
    manifest_id = _write_cleanup_log(
        archive_root,
        operation="run.archive",
        targets=archived,
        target_records=target_records,
        dry_run=dry_run,
        target_type="run",
        source_root=runs_root,
        filters={
            "experiment": experiment,
            "benchmark_family": benchmark_family,
            "status": status,
        },
        retention=cleanup_log_retention,
    )
    return {"dry_run": dry_run, "archived_runs": archived, "manifest_id": manifest_id}


def prune_runs(
    runs_root: Path,
    *,
    candidates_root: Path | None = None,
    archive_root: Path = Path("archive"),
    cleanup_log_retention: int | None = None,
    dry_run: bool = False,
    experiment: str | None = None,
    benchmark_family: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    index_payload = build_run_index(runs_root, candidates_root=candidates_root)
    selected_runs = _select_runs(
        [
            item
            for item in index_payload.get("runs", [])
            if item.get("status") in {"superseded", "failed"}
        ],
        experiment=experiment,
        benchmark_family=benchmark_family,
        status=status,
    )
    deleted: list[str] = []
    target_records: list[dict[str, Any]] = []
    for item in selected_runs:
        run_id = item["run_id"]
        path = runs_root / run_id
        if not path.exists():
            continue
        if not dry_run:
            shutil.rmtree(path)
        deleted.append(run_id)
        target_records.append(
            {
                "target_id": run_id,
                "target_type": "run",
                "status": item.get("status"),
                "experiment": item.get("experiment"),
                "benchmark_family": item.get("benchmark_family"),
                "variant": item.get("variant"),
                "source_path": str(path),
                "archive_path": None,
            }
        )
    manifest_id = _write_cleanup_log(
        archive_root,
        operation="run.prune",
        targets=deleted,
        target_records=target_records,
        dry_run=dry_run,
        target_type="run",
        source_root=runs_root,
        filters={
            "experiment": experiment,
            "benchmark_family": benchmark_family,
            "status": status,
        },
        retention=cleanup_log_retention,
    )
    return {"dry_run": dry_run, "deleted_runs": deleted, "manifest_id": manifest_id}


def archive_candidates(
    candidates_root: Path,
    *,
    archive_root: Path,
    runs_root: Path | None = None,
    cleanup_log_retention: int | None = None,
    dry_run: bool = False,
    experiment: str | None = None,
    benchmark_family: str | None = None,
) -> dict[str, Any]:
    index_payload = build_candidate_index(candidates_root, runs_root=runs_root)
    selected_candidates = _select_candidates(
        [
            item
            for item in index_payload.get("candidates", [])
            if item.get("status") == "superseded"
        ],
        experiment=experiment,
        benchmark_family=benchmark_family,
    )
    archived: list[str] = []
    target_records: list[dict[str, Any]] = []
    archive_candidates_root = archive_root / "candidates"
    archive_candidates_root.mkdir(parents=True, exist_ok=True)
    for item in selected_candidates:
        candidate_id = item["candidate_id"]
        source = candidates_root / candidate_id
        if not source.exists():
            continue
        archive_path = archive_candidates_root / candidate_id
        if not dry_run:
            shutil.move(str(source), str(archive_path))
        archived.append(candidate_id)
        target_records.append(
            {
                "target_id": candidate_id,
                "target_type": "candidate",
                "status": item.get("status"),
                "experiment": item.get("experiment"),
                "benchmark_family": item.get("benchmark_family"),
                "variant": item.get("variant"),
                "source_path": str(source),
                "archive_path": str(archive_path),
            }
        )
    manifest_id = _write_cleanup_log(
        archive_root,
        operation="candidate.archive",
        targets=archived,
        target_records=target_records,
        dry_run=dry_run,
        target_type="candidate",
        source_root=candidates_root,
        filters={
            "experiment": experiment,
            "benchmark_family": benchmark_family,
            "status": None,
        },
        retention=cleanup_log_retention,
    )
    return {
        "dry_run": dry_run,
        "archived_candidates": archived,
        "manifest_id": manifest_id,
    }


def prune_candidates(
    candidates_root: Path,
    *,
    runs_root: Path | None = None,
    archive_root: Path = Path("archive"),
    cleanup_log_retention: int | None = None,
    dry_run: bool = False,
    experiment: str | None = None,
    benchmark_family: str | None = None,
) -> dict[str, Any]:
    index_payload = build_candidate_index(candidates_root, runs_root=runs_root)
    selected_candidates = _select_candidates(
        [
            item
            for item in index_payload.get("candidates", [])
            if item.get("status") == "superseded"
        ],
        experiment=experiment,
        benchmark_family=benchmark_family,
    )
    deleted: list[str] = []
    target_records: list[dict[str, Any]] = []
    for item in selected_candidates:
        candidate_id = item["candidate_id"]
        path = candidates_root / candidate_id
        if not path.exists():
            continue
        if not dry_run:
            shutil.rmtree(path)
        deleted.append(candidate_id)
        target_records.append(
            {
                "target_id": candidate_id,
                "target_type": "candidate",
                "status": item.get("status"),
                "experiment": item.get("experiment"),
                "benchmark_family": item.get("benchmark_family"),
                "variant": item.get("variant"),
                "source_path": str(path),
                "archive_path": None,
            }
        )
    manifest_id = _write_cleanup_log(
        archive_root,
        operation="candidate.prune",
        targets=deleted,
        target_records=target_records,
        dry_run=dry_run,
        target_type="candidate",
        source_root=candidates_root,
        filters={
            "experiment": experiment,
            "benchmark_family": benchmark_family,
            "status": None,
        },
        retention=cleanup_log_retention,
    )
    return {
        "dry_run": dry_run,
        "deleted_candidates": deleted,
        "manifest_id": manifest_id,
    }


def _write_cleanup_log(
    archive_root: Path,
    *,
    operation: str,
    targets: list[str],
    target_records: list[dict[str, Any]],
    dry_run: bool,
    target_type: str,
    source_root: Path,
    filters: dict[str, Any],
    retention: int | None = None,
) -> str:
    logs_root = archive_root / "cleanup_logs"
    logs_root.mkdir(parents=True, exist_ok=True)
    manifest_id = f"{uuid4().hex[:12]}.json"
    manifest_payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operation": operation,
        "target_type": target_type,
        "targets": targets,
        "target_records": target_records,
        "dry_run": dry_run,
        "source_root": str(source_root),
        "archive_root": str(archive_root),
        "filters": filters,
    }
    (logs_root / manifest_id).write_text(
        json.dumps(manifest_payload, indent=2), encoding="utf-8"
    )
    with (logs_root / "cleanup_log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps({"manifest_id": manifest_id, **manifest_payload}) + "\n"
        )
    _enforce_cleanup_log_retention(logs_root, max_entries=retention)
    return manifest_id


def _enforce_cleanup_log_retention(
    logs_root: Path,
    *,
    max_entries: int | None = None,
) -> None:
    if max_entries is None:
        max_entries = _DEFAULT_CLEANUP_LOG_RETENTION
    log_path = logs_root / "cleanup_log.jsonl"
    if max_entries <= 0:
        retained_entries: list[dict[str, Any]] = []
    elif log_path.exists():
        retained_entries = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ][-max_entries:]
    else:
        retained_entries = []

    retained_manifest_ids = {
        str(entry.get("manifest_id"))
        for entry in retained_entries
        if entry.get("manifest_id")
    }

    if log_path.exists():
        content = ""
        if retained_entries:
            content = "\n".join(
                json.dumps(entry, ensure_ascii=False) for entry in retained_entries
            ) + "\n"
        log_path.write_text(content, encoding="utf-8")

    for manifest_path in logs_root.glob("*.json"):
        if manifest_path.name == "cleanup_log.jsonl":
            continue
        if manifest_path.name in retained_manifest_ids:
            continue
        manifest_path.unlink()
