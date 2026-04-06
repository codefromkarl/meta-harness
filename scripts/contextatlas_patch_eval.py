from __future__ import annotations

import json
from pathlib import Path


def read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def read_phase_output(task_dir: Path, phase: str) -> str:
    stdout = read_text_if_exists(task_dir / f"{phase}.stdout.txt")
    stderr = read_text_if_exists(task_dir / f"{phase}.stderr.txt")
    return "\n".join(part for part in [stdout, stderr] if part)


def phase_completed(task_dir: Path, phase: str) -> bool:
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


def main() -> None:
    run_dir = Path.cwd()
    task_dirs = sorted(path for path in (run_dir / "tasks").iterdir() if path.is_dir())

    workspace_artifact = run_dir / "artifacts" / "workspace.json"
    workspace_payload = {}
    if workspace_artifact.exists():
        workspace_payload = json.loads(workspace_artifact.read_text(encoding="utf-8"))

    patch_applied = bool(
        workspace_payload.get("patch_applied") or workspace_payload.get("patch_already_present")
    )
    build_ok = False
    targeted_tests_ok = False
    profile_present = False
    memory_consistency_ok = False

    for task_dir in task_dirs:
        build_ok = build_ok or phase_completed(task_dir, "build")
        targeted_tests_ok = targeted_tests_ok or phase_completed(task_dir, "test_omc_import")

        show_profile = read_phase_output(task_dir, "show_profile")
        if "项目：" in show_profile:
            profile_present = True

        check_memory = read_phase_output(task_dir, "check_memory")
        if "memory consistency check: OK" in check_memory or "status: ok" in check_memory.lower():
            memory_consistency_ok = True

    composite_adjustment = sum(
        1.0
        for passed in [
            patch_applied,
            build_ok,
            targeted_tests_ok,
            profile_present,
            memory_consistency_ok,
        ]
        if passed
    )

    print(
        json.dumps(
            {
                "correctness": {
                    "patch_applied": patch_applied,
                    "build_ok": build_ok,
                    "targeted_tests_ok": targeted_tests_ok,
                },
                "maintainability": {
                    "profile_present": profile_present,
                    "memory_consistency_ok": memory_consistency_ok,
                },
                "composite_adjustment": composite_adjustment,
            }
        )
    )


if __name__ == "__main__":
    main()
