from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_cli_and_api_modules_import_without_circular_dependency() -> None:
    import meta_harness.api.app as api_app_module
    import meta_harness.cli as cli_module

    assert api_app_module.create_app is not None
    assert cli_module.app is not None


def test_cli_module_executes_typer_entrypoint(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    runs_root = tmp_path / "runs"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "meta_harness.cli",
            "run",
            "init",
            "--profile",
            "demo_public",
            "--project",
            "demo_public",
            "--config-root",
            str(repo_root / "configs"),
            "--runs-root",
            str(runs_root),
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    run_id = completed.stdout.strip()
    assert run_id
    assert (runs_root / run_id / "run_metadata.json").exists()
