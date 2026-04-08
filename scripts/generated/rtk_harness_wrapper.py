from __future__ import annotations

import json
import subprocess
from pathlib import Path

TARGET_PROJECT_PATH = Path("/home/yuanzhi/Develop/tools/rtk")
ENTRY_COMMAND = [
  "cargo",
  "run",
  "--"
]
CAPABILITY_MODULES = [
  "artifact_producer",
  "command_proxy",
  "output_filter",
  "report_normalizer",
  "tooling_wrapper"
]


def main() -> int:
    # TODO: harness-first wrapper draft.
    # Review and specialize by capability modules before activation.
    completed = subprocess.run(
        ENTRY_COMMAND,
        cwd=TARGET_PROJECT_PATH,
        capture_output=True,
        text=True,
        check=False,
    )
    payload = {
        "command_proxy": True,
        "capability_modules": CAPABILITY_MODULES,
        "stdout_preview": (completed.stdout or "")[:800],
        "stderr_preview": (completed.stderr or "")[:800],
        "exit_code": completed.returncode,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
