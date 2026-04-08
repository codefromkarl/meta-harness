from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from meta_harness.evaluator_runtime import iter_task_dirs, load_step_events


def _read_effective_config(run_dir: Path) -> dict[str, Any]:
    effective_config_path = run_dir / "effective_config.json"
    if not effective_config_path.exists():
        return {}
    payload = json.loads(effective_config_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _meta_harness_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _empty_report() -> dict[str, Any]:
    return {
        "correctness": {},
        "cost": {},
        "maintainability": {},
        "architecture": {},
        "retrieval": {},
        "human_collaboration": {},
        "capability_scores": {},
        "workflow_scores": {"white_box_findings": []},
        "probes": {},
        "composite_adjustment": 0.0,
    }


def _repo_root(run_dir: Path) -> Path:
    effective_config = _read_effective_config(run_dir)
    workspace = (effective_config.get("runtime") or {}).get("workspace") or {}
    source_repo = workspace.get("source_repo")
    if isinstance(source_repo, str) and source_repo:
        return Path(source_repo).expanduser().resolve()
    return run_dir


def _audit_config(run_dir: Path) -> dict[str, Any]:
    effective_config = _read_effective_config(run_dir)
    evaluation = effective_config.get("evaluation") or {}
    white_box_audit = evaluation.get("white_box_audit") or {}
    return white_box_audit if isinstance(white_box_audit, dict) else {}


def _resolve_audit_path(run_dir: Path, raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    search_roots = (_repo_root(run_dir), _meta_harness_root(), run_dir)
    for root in search_roots:
        resolved = (root / candidate).resolve()
        if resolved.exists():
            return resolved
    raise FileNotFoundError(f"white box audit rule file not found: {raw_path}")


def _normalize_rule_entries(payload: Any, source: str) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        payload = payload.get("rules")
    if not isinstance(payload, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        rule = dict(item)
        rule.setdefault("source", source)
        normalized.append(rule)
    return normalized


def _audit_rules(run_dir: Path, audit_config: dict[str, Any]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    rule_files = audit_config.get("rule_files")
    if isinstance(rule_files, list):
        for raw_path in rule_files:
            if not isinstance(raw_path, str) or not raw_path:
                continue
            resolved = _resolve_audit_path(run_dir, raw_path)
            payload = json.loads(resolved.read_text(encoding="utf-8"))
            rules.extend(_normalize_rule_entries(payload, str(resolved)))
    rules.extend(_normalize_rule_entries(audit_config.get("rules"), "inline"))
    return rules


def _runtime_profiling_enabled(audit_config: dict[str, Any]) -> bool:
    if not audit_config:
        return False
    profiling = audit_config.get("runtime_profiling")
    if profiling is False:
        return False
    if isinstance(profiling, dict):
        return bool(profiling.get("enabled", True))
    return True


def _runtime_profiling_top_n(audit_config: dict[str, Any]) -> int:
    profiling = audit_config.get("runtime_profiling")
    if not isinstance(profiling, dict):
        return 5
    value = profiling.get("top_n", 5)
    if not isinstance(value, (int, float)):
        return 5
    return max(1, int(value))


def _build_runtime_profile(run_dir: Path, audit_config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not _runtime_profiling_enabled(audit_config):
        return {}, {}, {}

    top_n = _runtime_profiling_top_n(audit_config)
    total_latency_ms = 0.0
    total_stdout_bytes = 0
    total_stderr_bytes = 0
    repeated_phase_count = 0
    task_profiles: list[dict[str, Any]] = []
    phase_profiles: list[dict[str, Any]] = []
    phase_latency_totals: dict[str, float] = {}
    phase_invocations: dict[str, int] = {}

    for task_dir in iter_task_dirs(run_dir):
        steps = load_step_events(task_dir)
        task_latency_ms = 0.0
        task_phase_counts: dict[str, int] = {}
        for event in steps:
            phase = str(event.get("phase") or "unknown")
            latency_ms = float(event.get("latency_ms", 0.0) or 0.0)
            task_latency_ms += latency_ms
            phase_latency_totals[phase] = phase_latency_totals.get(phase, 0.0) + latency_ms
            phase_invocations[phase] = phase_invocations.get(phase, 0) + 1
            task_phase_counts[phase] = task_phase_counts.get(phase, 0) + 1
            phase_profiles.append(
                {
                    "task_id": task_dir.name,
                    "phase": phase,
                    "latency_ms": round(latency_ms, 4),
                    "status": str(event.get("status") or ""),
                }
            )

        repeated_phase_count += sum(
            count - 1 for count in task_phase_counts.values() if count > 1
        )
        task_stdout_bytes = sum(
            path.stat().st_size for path in task_dir.glob("*.stdout.txt") if path.is_file()
        )
        task_stderr_bytes = sum(
            path.stat().st_size for path in task_dir.glob("*.stderr.txt") if path.is_file()
        )
        total_latency_ms += task_latency_ms
        total_stdout_bytes += task_stdout_bytes
        total_stderr_bytes += task_stderr_bytes
        task_profiles.append(
            {
                "task_id": task_dir.name,
                "latency_ms": round(task_latency_ms, 4),
                "step_count": len(steps),
                "stdout_bytes": task_stdout_bytes,
                "stderr_bytes": task_stderr_bytes,
            }
        )

    slow_tasks = sorted(
        task_profiles,
        key=lambda item: (-float(item["latency_ms"]), str(item["task_id"])),
    )[:top_n]
    slow_phases = sorted(
        phase_profiles,
        key=lambda item: (
            -float(item["latency_ms"]),
            str(item["task_id"]),
            str(item["phase"]),
        ),
    )[:top_n]
    phase_summary = sorted(
        (
            {
                "phase": phase,
                "invocations": count,
                "latency_ms": round(phase_latency_totals.get(phase, 0.0), 4),
            }
            for phase, count in phase_invocations.items()
        ),
        key=lambda item: (-float(item["latency_ms"]), str(item["phase"])),
    )

    runtime_profile = {
        "task_count": len(task_profiles),
        "phase_count": len(phase_profiles),
        "slow_tasks": slow_tasks,
        "slow_phases": slow_phases,
        "phase_summary": phase_summary,
    }
    cost = {
        "white_box_runtime_total_latency_ms": round(total_latency_ms, 4),
        "white_box_runtime_stdout_bytes": total_stdout_bytes,
        "white_box_runtime_stderr_bytes": total_stderr_bytes,
    }
    architecture = {
        "white_box_runtime_repeated_phase_count": repeated_phase_count,
    }
    probes = {
        "white_box.runtime.task_count": float(len(task_profiles)),
        "white_box.runtime.phase_count": float(len(phase_profiles)),
        "white_box.runtime.repeated_phase_count": float(repeated_phase_count),
        "white_box.runtime.stdout_bytes": float(total_stdout_bytes),
        "white_box.runtime.stderr_bytes": float(total_stderr_bytes),
    }
    return runtime_profile, cost, {**architecture, **probes}


def evaluate_white_box_run(run_dir: Path) -> dict[str, Any]:
    repo_root = _repo_root(run_dir)
    audit_config = _audit_config(run_dir)
    if not audit_config:
        return _empty_report()
    rules = _audit_rules(run_dir, audit_config)
    runtime_profile, runtime_cost, runtime_metrics = _build_runtime_profile(
        run_dir, audit_config
    )
    if not rules and not runtime_profile:
        return _empty_report()

    findings: list[dict[str, Any]] = []
    probes: dict[str, float] = {}
    blocker_count = 0
    warn_count = 0

    for rule in rules:
        rule_id = str(rule.get("id", "unnamed-rule"))
        globs = rule.get("path_globs")
        path_globs = [str(item) for item in globs] if isinstance(globs, list) and globs else ["**/*"]
        pattern = rule.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            continue
        compiled = re.compile(pattern)
        severity = str(rule.get("severity", "warn"))
        message = str(rule.get("message", ""))
        match_count = 0
        for path_glob in path_globs:
            for path in repo_root.glob(path_glob):
                if not path.is_file():
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                for match in compiled.finditer(text):
                    match_count += 1
                    findings.append(
                        {
                            "rule_id": rule_id,
                            "severity": severity,
                            "message": message,
                            "source": str(rule.get("source") or "inline"),
                            "path": str(path.relative_to(repo_root)),
                            "line": text[: match.start()].count("\n") + 1,
                        }
                    )
        probes[f"white_box.{rule_id}.matches"] = float(match_count)
        if match_count > 0:
            if severity == "blocker":
                blocker_count += 1
            else:
                warn_count += 1

    composite_adjustment = round((-0.25 * blocker_count) + (-0.05 * warn_count), 4)
    workflow_scores: dict[str, Any] = {"white_box_findings": findings}
    if runtime_profile:
        workflow_scores["white_box_runtime_profile"] = runtime_profile
    return {
        "correctness": {},
        "cost": runtime_cost,
        "maintainability": {},
        "architecture": {
            "white_box_rule_violation_count": blocker_count + warn_count,
            "white_box_blocker_count": blocker_count,
            "white_box_warn_count": warn_count,
            "white_box_runtime_repeated_phase_count": int(
                runtime_metrics.get("white_box_runtime_repeated_phase_count", 0)
            ),
        },
        "retrieval": {},
        "human_collaboration": {},
        "capability_scores": {},
        "workflow_scores": workflow_scores,
        "probes": {
            **probes,
            "white_box.runtime.task_count": float(
                runtime_metrics.get("white_box.runtime.task_count", 0.0)
            ),
            "white_box.runtime.phase_count": float(
                runtime_metrics.get("white_box.runtime.phase_count", 0.0)
            ),
            "white_box.runtime.repeated_phase_count": float(
                runtime_metrics.get("white_box.runtime.repeated_phase_count", 0.0)
            ),
            "white_box.runtime.stdout_bytes": float(
                runtime_metrics.get("white_box.runtime.stdout_bytes", 0.0)
            ),
            "white_box.runtime.stderr_bytes": float(
                runtime_metrics.get("white_box.runtime.stderr_bytes", 0.0)
            ),
        },
        "composite_adjustment": composite_adjustment,
    }
