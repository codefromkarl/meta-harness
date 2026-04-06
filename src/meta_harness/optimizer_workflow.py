from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Protocol


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _read_phase_output(task_dir: Path, phase: str) -> str:
    stdout = _read_text_if_exists(task_dir / f"{phase}.stdout.txt")
    stderr = _read_text_if_exists(task_dir / f"{phase}.stderr.txt")
    return "\n".join(part for part in [stdout, stderr] if part).strip()


def _extract_catalog_stats(output: str) -> dict[str, int]:
    module_match = re.search(r'"moduleCount"\s*:\s*(\d+)', output)
    scope_match = re.search(r'"scopeCount"\s*:\s*(\d+)', output)
    stats: dict[str, int] = {}
    if module_match:
        stats["module_count"] = int(module_match.group(1))
    if scope_match:
        stats["scope_count"] = int(scope_match.group(1))
    return stats


def _phase_completed(task_dir: Path, phase: str) -> bool:
    steps_path = task_dir / "steps.jsonl"
    if not steps_path.exists():
        return False
    for line in steps_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if payload.get("phase") == phase and payload.get("status") == "completed":
            return True
    return False


class RunContextStrategy(Protocol):
    def collect_run_context(self, run_dir: Path) -> dict[str, Any]: ...


class DefaultRunContextStrategy:
    def collect_run_context(self, run_dir: Path) -> dict[str, Any]:
        return {}


class ContextAtlasRunContextStrategy:
    def collect_run_context(self, run_dir: Path) -> dict[str, Any]:
        tasks_dir = run_dir / "tasks"
        contextatlas: dict[str, Any] = {
            "profile_present": False,
            "memory_consistency_ok": False,
            "targeted_tests_ok": False,
        }

        if not tasks_dir.exists():
            return {"contextatlas": contextatlas}

        for task_dir in sorted(path for path in tasks_dir.iterdir() if path.is_dir()):
            show_profile = _read_phase_output(task_dir, "show_profile")
            if "项目：" in show_profile:
                contextatlas["profile_present"] = True
            source_match = re.search(r"描述：Imported from ([^\n]+)", show_profile)
            if source_match:
                contextatlas["latest_profile_source"] = source_match.group(1).strip()
            updated_match = re.search(r"最后更新：([^\n]+)", show_profile)
            if updated_match:
                contextatlas["latest_profile_updated_at"] = updated_match.group(
                    1
                ).strip()

            check_memory = _read_phase_output(task_dir, "check_memory")
            if (
                "memory consistency check: OK" in check_memory
                or "status: ok" in check_memory.lower()
            ):
                contextatlas["memory_consistency_ok"] = True
            catalog_stats = _extract_catalog_stats(check_memory)
            if catalog_stats:
                contextatlas["catalog_stats"] = catalog_stats

            test_output = _read_phase_output(task_dir, "test_omc_import")
            lowered_test_output = test_output.lower()
            if _phase_completed(task_dir, "test_omc_import") or (
                "pass" in lowered_test_output and "fail 0" in lowered_test_output
            ):
                contextatlas["targeted_tests_ok"] = True

            health_output = _read_phase_output(task_dir, "health_check").strip()
            if health_output.startswith("{") and health_output.endswith("}"):
                try:
                    payload = json.loads(health_output)
                except json.JSONDecodeError:
                    payload = {}
                snapshots = payload.get("snapshots") or []
                if snapshots:
                    snapshot = snapshots[0]
                    contextatlas["snapshot_ready"] = bool(
                        snapshot.get("hasCurrentSnapshot")
                    )
                    contextatlas["vector_index_ready"] = bool(
                        snapshot.get("hasVectorIndex")
                    )
                    contextatlas["db_integrity_ok"] = (
                        snapshot.get("dbIntegrity") == "ok"
                    )

        return {"contextatlas": contextatlas}


def get_run_context_strategy(profile_name: str) -> RunContextStrategy:
    if profile_name.startswith("contextatlas_"):
        return ContextAtlasRunContextStrategy()
    return DefaultRunContextStrategy()
