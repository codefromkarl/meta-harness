from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
from typing import Any

from meta_harness.catalog import build_run_index


def _parse_created_at(raw: Any) -> datetime:
    if not raw:
        return datetime.min.replace(tzinfo=UTC)
    text = str(raw).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)


def _filter_runs(
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
    return sorted(
        selected,
        key=lambda item: (
            str(item.get("status") or ""),
            _parse_created_at(item.get("created_at")),
            str(item.get("run_id") or ""),
        ),
    )


def _retained_run_ids(
    runs: list[dict[str, Any]],
    *,
    latest_valid_by_experiment: dict[str, str],
    current_recommended_run_by_experiment: dict[str, str],
) -> set[str]:
    retained = {
        str(run_id)
        for run_id in (
            list(latest_valid_by_experiment.values())
            + list(current_recommended_run_by_experiment.values())
        )
        if run_id
    }

    runs_by_scope: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in runs:
        scope = (str(item.get("profile") or ""), str(item.get("project") or ""))
        runs_by_scope.setdefault(scope, []).append(item)

    for items in runs_by_scope.values():
        latest = max(
            items,
            key=lambda item: (
                _parse_created_at(item.get("created_at")),
                str(item.get("run_id") or ""),
            ),
        )
        best = max(
            items,
            key=lambda item: (
                float(item.get("composite") or 0.0),
                _parse_created_at(item.get("created_at")),
                str(item.get("run_id") or ""),
            ),
        )
        retained.add(str(latest.get("run_id") or ""))
        retained.add(str(best.get("run_id") or ""))

    retained.discard("")
    return retained


def _is_compactable(item: dict[str, Any], retained_run_ids: set[str]) -> bool:
    status = str(item.get("status") or "")
    run_id = str(item.get("run_id") or "")
    if status in {"superseded", "failed", "partial"}:
        return True
    return status == "valid" and run_id not in retained_run_ids


def _delete_artifact_payloads(artifacts_dir: Path) -> list[str]:
    removed: list[str] = []
    if not artifacts_dir.exists():
        return removed
    for path in sorted(artifacts_dir.iterdir()):
        if path.name in {"workspace.json", "compaction.json"}:
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed.append(f"artifacts/{path.name}")
    return removed


def _write_compaction_marker(run_dir: Path, removed: list[str]) -> None:
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "compaction.json").write_text(
        json.dumps({"removed": removed}, indent=2),
        encoding="utf-8",
    )


def _remove_tree_if_exists(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        return True
    return True


def compact_runs(
    runs_root: Path,
    *,
    candidates_root: Path | None = None,
    dry_run: bool = False,
    experiment: str | None = None,
    benchmark_family: str | None = None,
    status: str | None = None,
    include_artifacts: bool = False,
    compactable_statuses: list[str] | None = None,
    cleanup_auxiliary_dirs: bool = True,
) -> dict[str, Any]:
    if not runs_root.exists():
        return {"dry_run": dry_run, "compacted_runs": []}

    index_payload = build_run_index(runs_root, candidates_root=candidates_root)
    runs = index_payload.get("runs", [])
    allowed_statuses = set(compactable_statuses or ["valid", "superseded", "failed", "partial"])
    retained_run_ids = _retained_run_ids(
        runs,
        latest_valid_by_experiment=index_payload.get("latest_valid_by_experiment", {}),
        current_recommended_run_by_experiment=index_payload.get(
            "current_recommended_run_by_experiment", {}
        ),
    )
    selected_runs = _filter_runs(
        [
            item
            for item in runs
            if _is_compactable(item, retained_run_ids)
            and str(item.get("status") or "") in allowed_statuses
        ],
        experiment=experiment,
        benchmark_family=benchmark_family,
        status=status,
    )

    compacted_runs: list[dict[str, Any]] = []
    for item in selected_runs:
        run_id = str(item.get("run_id") or "")
        run_dir = runs_root / run_id
        removed: list[str] = []
        workspace_dir = run_dir / "workspace"
        if workspace_dir.exists():
            if not dry_run:
                removed_workspace = _remove_tree_if_exists(workspace_dir)
            else:
                removed_workspace = True
            if removed_workspace:
                removed.append("workspace")

        if include_artifacts:
            artifacts_removed = _delete_artifact_payloads(run_dir / "artifacts")
            if dry_run:
                artifacts_dir = run_dir / "artifacts"
                artifacts_removed = []
                if artifacts_dir.exists():
                    for path in sorted(artifacts_dir.iterdir()):
                        if path.name in {"workspace.json", "compaction.json"}:
                            continue
                        artifacts_removed.append(f"artifacts/{path.name}")
            else:
                removed.extend(artifacts_removed)

            if dry_run:
                removed.extend(artifacts_removed)

        if not removed:
            continue
        if not dry_run:
            _write_compaction_marker(run_dir, removed)
        compacted_runs.append({"run_id": run_id, "removed": removed})

    compacted_auxiliary_dirs: list[str] = []
    if cleanup_auxiliary_dirs:
        for name in ("_benchmark_sources", "_suite_sources"):
            path = runs_root / name
            if not path.exists():
                continue
            if not dry_run:
                _remove_tree_if_exists(path)
            compacted_auxiliary_dirs.append(name)

    payload = {
        "dry_run": dry_run,
        "compacted_runs": compacted_runs,
    }
    if compacted_auxiliary_dirs:
        payload["compacted_auxiliary_dirs"] = compacted_auxiliary_dirs
    return payload
