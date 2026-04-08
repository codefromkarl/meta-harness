from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_openclaw_demo_assets_are_present_and_parseable() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    paths = [
        repo_root / "scripts" / "bootstrap.sh",
        repo_root / "scripts" / "demo_openclaw_websearch_analysis.sh",
        repo_root / "configs" / "profiles" / "demo_openclaw.json",
        repo_root / "configs" / "projects" / "demo_openclaw.json",
        repo_root / "configs" / "benchmarks" / "demo_openclaw_websearch_analysis.json",
        repo_root / "task_sets" / "demo" / "openclaw_websearch_analysis.json",
        repo_root / "demo" / "openclaw_websearch_analysis" / "README.md",
        repo_root / "demo" / "openclaw_websearch_analysis" / "scripts" / "normalize_web_result.py",
        repo_root / "demo" / "openclaw_websearch_analysis" / "scripts" / "normalize_analysis_result.py",
        repo_root / "demo" / "openclaw_websearch_analysis" / "sources" / "tool_a_pricing.html",
        repo_root / "demo" / "openclaw_websearch_analysis" / "sources" / "tool_b_pricing.html",
        repo_root / "demo" / "openclaw_websearch_analysis" / "sources" / "tool_c_pricing.html",
    ]

    for path in paths:
        assert path.exists(), path

    for script in [
        repo_root / "scripts" / "bootstrap.sh",
        repo_root / "scripts" / "demo_openclaw_websearch_analysis.sh",
    ]:
        completed = subprocess.run(
            ["bash", "-n", str(script)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr

    for payload_path in [
        repo_root / "configs" / "profiles" / "demo_openclaw.json",
        repo_root / "configs" / "projects" / "demo_openclaw.json",
        repo_root / "configs" / "benchmarks" / "demo_openclaw_websearch_analysis.json",
        repo_root / "task_sets" / "demo" / "openclaw_websearch_analysis.json",
    ]:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
