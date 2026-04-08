from __future__ import annotations

from pathlib import Path

from meta_harness.config_loader import load_platform_config


def _cleanup_log_retention(
    config_root: Path,
    project_name: str | None = None,
) -> int | None:
    try:
        platform_config = load_platform_config(config_root, project_name=project_name)
    except FileNotFoundError:
        return None

    archive = platform_config.get("archive")
    if not isinstance(archive, dict):
        return None
    cleanup_logs = archive.get("cleanup_logs")
    if not isinstance(cleanup_logs, dict):
        return None
    retention = cleanup_logs.get("retention")
    if retention is None:
        return None
    return int(retention)

def _archive_config(
    config_root: Path,
    project_name: str | None = None,
) -> dict[str, object]:
    try:
        platform_config = load_platform_config(config_root, project_name=project_name)
    except FileNotFoundError:
        return {}
    archive = platform_config.get("archive")
    return archive if isinstance(archive, dict) else {}

def _compaction_include_artifacts(
    config_root: Path,
    project_name: str | None,
    include_artifacts: bool | None,
) -> bool:
    if include_artifacts is not None:
        return include_artifacts
    archive = _archive_config(config_root, project_name=project_name)
    compaction = archive.get("compaction")
    if not isinstance(compaction, dict):
        return False
    return bool(compaction.get("include_artifacts", False))

def _compaction_cleanup_auxiliary_dirs(
    config_root: Path,
    project_name: str | None,
) -> bool:
    archive = _archive_config(config_root, project_name=project_name)
    compaction = archive.get("compaction")
    if not isinstance(compaction, dict):
        return True
    value = compaction.get("cleanup_auxiliary_dirs")
    if value is None:
        return True
    return bool(value)

def _compaction_compactable_statuses(
    config_root: Path,
    project_name: str | None,
) -> list[str] | None:
    archive = _archive_config(config_root, project_name=project_name)
    compaction = archive.get("compaction")
    if not isinstance(compaction, dict):
        return None
    statuses = compaction.get("compactable_statuses")
    if not isinstance(statuses, list):
        return None
    return [str(status) for status in statuses]

def _should_bootstrap_observation_optimization(
    summary: dict[str, object],
    effective_config: dict[str, object],
    *,
    auto_propose: bool,
) -> tuple[bool, str]:
    if bool(summary.get("needs_optimization")):
        return True, str(summary.get("recommended_focus", "none"))

    optimization = (
        (effective_config.get("optimization") or {})
        if isinstance(effective_config, dict)
        else {}
    )
    proposal_command = (
        optimization.get("proposal_command") if isinstance(optimization, dict) else None
    )
    latest_score = (
        summary.get("score") if isinstance(summary.get("score"), dict) else {}
    )
    latest_score = latest_score if isinstance(latest_score, dict) else {}
    if (
        auto_propose
        and proposal_command
        and not any(
            latest_score.get(section)
            for section in ("maintainability", "architecture", "retrieval")
        )
    ):
        return True, "retrieval"
    return False, str(summary.get("recommended_focus", "none"))

