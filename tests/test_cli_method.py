from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from meta_harness.cli import app


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_transfer_assets(config_root: Path) -> None:
    write_json(
        config_root / "task_methods" / "web_scrape" / "fast_path.json",
        {
            "method_id": "web_scrape/fast_path",
            "primitive_id": "web_scrape",
            "portable_knobs": ["workflow.primitives.web_scrape.timeout_ms"],
            "default_patch": {
                "workflow": {
                    "primitives": {
                        "web_scrape": {
                            "timeout_ms": 5000,
                        }
                    }
                }
            },
        },
    )
    write_json(
        config_root / "claw_bindings" / "openclaw" / "codex" / "web_scrape.json",
        {
            "binding_id": "openclaw/codex/web_scrape",
            "claw_family": "openclaw",
            "primitive_id": "web_scrape",
            "adapter_kind": "openclaw_acp",
            "binding_patch": {
                "runtime": {
                    "binding": {
                        "binding_id": "openclaw/codex/web_scrape",
                        "agent_id": "codex",
                    }
                }
            },
        },
    )
    write_json(
        config_root / "claw_bindings" / "openclaw" / "claude" / "web_scrape.json",
        {
            "binding_id": "openclaw/claude/web_scrape",
            "claw_family": "openclaw",
            "primitive_id": "web_scrape",
            "adapter_kind": "openclaw_acp",
            "binding_patch": {
                "runtime": {
                    "binding": {
                        "binding_id": "openclaw/claude/web_scrape",
                        "agent_id": "claude",
                    }
                }
            },
        },
    )


def test_method_inspect_and_transfer_plan_cli(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    write_transfer_assets(config_root)
    runner = CliRunner()

    inspect_result = runner.invoke(
        app,
        [
            "method",
            "inspect",
            "--method-id",
            "web_scrape/fast_path",
            "--binding-id",
            "openclaw/codex/web_scrape",
            "--config-root",
            str(config_root),
        ],
    )

    assert inspect_result.exit_code == 0
    inspect_payload = json.loads(inspect_result.stdout)
    assert inspect_payload["method"]["method_id"] == "web_scrape/fast_path"
    assert inspect_payload["binding"]["binding_id"] == "openclaw/codex/web_scrape"

    plan_result = runner.invoke(
        app,
        [
            "method",
            "transfer-plan",
            "--method-id",
            "web_scrape/fast_path",
            "--source-binding-id",
            "openclaw/codex/web_scrape",
            "--target-binding-id",
            "openclaw/claude/web_scrape",
            "--config-root",
            str(config_root),
        ],
    )

    assert plan_result.exit_code == 0
    plan_payload = json.loads(plan_result.stdout)
    assert plan_payload["transfer"]["source_binding"] == "openclaw/codex/web_scrape"
    assert plan_payload["target_binding"]["binding_id"] == "openclaw/claude/web_scrape"
