from __future__ import annotations

import json
from pathlib import Path

from meta_harness.transfer import (
    create_transfer_candidate,
    inspect_method_binding,
    plan_method_transfer,
)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_base_config(config_root: Path) -> None:
    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {"evaluation": {"evaluators": ["basic"]}}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {"runtime": {"workspace": {"source_repo": "."}}}},
    )


def write_transfer_assets(config_root: Path) -> None:
    write_json(
        config_root / "task_methods" / "web_scrape" / "fast_path.json",
        {
            "method_id": "web_scrape/fast_path",
            "primitive_id": "web_scrape",
            "description": "Prefer lower latency navigation on stable pages.",
            "portable_knobs": [
                "workflow.primitives.web_scrape.timeout_ms",
                "workflow.primitives.web_scrape.retry_limit",
                "workflow.primitives.web_scrape.wait_strategy",
            ],
            "default_patch": {
                "workflow": {
                    "primitives": {
                        "web_scrape": {
                            "timeout_ms": 5000,
                            "retry_limit": 1,
                            "wait_strategy": "domcontentloaded",
                        }
                    }
                }
            },
            "expected_signals": {
                "fingerprints": {"scrape.mode": "fast"},
                "probes": {"scrape.retry_count": {"max": 1}},
            },
            "success_metrics": ["field_completeness", "grounded_field_rate", "latency_ms"],
            "tags": ["latency"],
        },
    )
    write_json(
        config_root / "claw_bindings" / "openclaw" / "codex" / "web_scrape.json",
        {
            "binding_id": "openclaw/codex/web_scrape",
            "claw_family": "openclaw",
            "primitive_id": "web_scrape",
            "adapter_kind": "openclaw_acp",
            "method_mapping": {
                "timeout_ms": "session.timeout_ms",
                "retry_limit": "tool.browser.retry_limit",
                "wait_strategy": "tool.browser.wait_strategy",
            },
            "binding_patch": {
                "runtime": {
                    "binding": {
                        "binding_id": "openclaw/codex/web_scrape",
                        "agent_id": "codex",
                        "tool_profile": "browser-heavy",
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
            "method_mapping": {
                "timeout_ms": "session.timeout_ms",
                "retry_limit": "tool.browser.retry_limit",
                "wait_strategy": "tool.browser.wait_strategy",
            },
            "binding_patch": {
                "runtime": {
                    "binding": {
                        "binding_id": "openclaw/claude/web_scrape",
                        "agent_id": "claude",
                        "tool_profile": "browser-heavy",
                    }
                }
            },
        },
    )


def test_inspect_method_binding_reports_method_and_binding_metadata(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    write_transfer_assets(config_root)

    payload = inspect_method_binding(
        config_root=config_root,
        method_id="web_scrape/fast_path",
        binding_id="openclaw/codex/web_scrape",
    )

    assert payload["method"]["method_id"] == "web_scrape/fast_path"
    assert payload["method"]["primitive_id"] == "web_scrape"
    assert payload["binding"]["binding_id"] == "openclaw/codex/web_scrape"
    assert payload["binding"]["adapter_kind"] == "openclaw_acp"


def test_plan_method_transfer_separates_portable_and_binding_scopes(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    write_transfer_assets(config_root)

    payload = plan_method_transfer(
        config_root=config_root,
        method_id="web_scrape/fast_path",
        source_binding_id="openclaw/codex/web_scrape",
        target_binding_id="openclaw/claude/web_scrape",
    )

    assert payload["method_id"] == "web_scrape/fast_path"
    assert payload["transfer"]["scope"] == "portable_first"
    assert payload["transfer"]["source_binding"] == "openclaw/codex/web_scrape"
    assert payload["target_binding"]["binding_id"] == "openclaw/claude/web_scrape"
    assert payload["method_patch"]["workflow"]["primitives"]["web_scrape"]["timeout_ms"] == 5000
    assert payload["binding_patch"]["runtime"]["binding"]["agent_id"] == "claude"
    assert payload["effective_patch"]["runtime"]["binding"]["binding_id"] == "openclaw/claude/web_scrape"


def test_create_transfer_candidate_builds_effective_config_and_proposal_layers(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"
    write_base_config(config_root)
    write_transfer_assets(config_root)

    candidate_id = create_transfer_candidate(
        config_root=config_root,
        candidates_root=candidates_root,
        profile_name="base",
        project_name="demo",
        method_id="web_scrape/fast_path",
        source_binding_id="openclaw/codex/web_scrape",
        target_binding_id="openclaw/claude/web_scrape",
        local_patch={"runtime": {"binding": {"approval_policy": "never"}}},
        notes="portable transfer",
    )

    candidate_dir = candidates_root / candidate_id
    proposal = json.loads((candidate_dir / "proposal.json").read_text(encoding="utf-8"))
    effective_config = json.loads((candidate_dir / "effective_config.json").read_text(encoding="utf-8"))

    assert proposal["strategy"] == "method_transfer"
    assert proposal["layers"]["method_patch"]["workflow"]["primitives"]["web_scrape"]["wait_strategy"] == "domcontentloaded"
    assert proposal["layers"]["binding_patch"]["runtime"]["binding"]["agent_id"] == "claude"
    assert proposal["layers"]["local_patch"]["runtime"]["binding"]["approval_policy"] == "never"
    assert proposal["transfer"]["validated_targets"] == ["openclaw/claude/web_scrape"]
    assert effective_config["workflow"]["primitives"]["web_scrape"]["retry_limit"] == 1
    assert effective_config["runtime"]["binding"]["agent_id"] == "claude"
    assert effective_config["runtime"]["binding"]["approval_policy"] == "never"
