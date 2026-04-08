from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from meta_harness.cli import app


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_candidate_create_promote_and_run_init_from_candidate(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"
    runs_root = tmp_path / "runs"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "java_to_rust.json",
        {"description": "workflow", "defaults": {"retrieval": {"top_k": 8}}},
    )
    write_json(
        config_root / "projects" / "voidsector.json",
        {"workflow": "java_to_rust", "overrides": {"budget": {"max_turns": 16}}},
    )
    patch_path = tmp_path / "patch.json"
    write_json(patch_path, {"budget": {"max_turns": 20}})

    runner = CliRunner()
    create_result = runner.invoke(
        app,
        [
            "candidate",
            "create",
            "--profile",
            "java_to_rust",
            "--project",
            "voidsector",
            "--config-root",
            str(config_root),
            "--candidates-root",
            str(candidates_root),
            "--config-patch",
            str(patch_path),
            "--notes",
            "increase turns",
        ],
    )

    assert create_result.exit_code == 0
    candidate_id = create_result.stdout.strip()

    candidate_dir = candidates_root / candidate_id
    metadata = json.loads((candidate_dir / "candidate.json").read_text(encoding="utf-8"))
    effective_config = json.loads((candidate_dir / "effective_config.json").read_text(encoding="utf-8"))
    assert metadata["profile"] == "java_to_rust"
    assert metadata["project"] == "voidsector"
    assert metadata["notes"] == "increase turns"
    assert effective_config["budget"]["max_turns"] == 20

    promote_result = runner.invoke(
        app,
        [
            "candidate",
            "promote",
            "--candidate-id",
            candidate_id,
            "--candidates-root",
            str(candidates_root),
            "--promoted-by",
            "tester",
            "--reason",
            "benchmark winner",
            "--evidence-run-id",
            "run-1",
            "--runs-root",
            str(runs_root),
        ],
    )
    assert promote_result.exit_code == 0

    champions = json.loads((candidates_root / "champions.json").read_text(encoding="utf-8"))
    assert champions["java_to_rust:voidsector"] == candidate_id
    champion_records = json.loads(
        (candidates_root / "champion_records.json").read_text(encoding="utf-8")
    )
    assert champion_records["java_to_rust:voidsector"]["promoted_by"] == "tester"
    assert champion_records["java_to_rust:voidsector"]["evidence_run_ids"] == ["run-1"]

    run_init_result = runner.invoke(
        app,
        [
            "run",
            "init",
            "--candidate-id",
            candidate_id,
            "--candidates-root",
            str(candidates_root),
            "--runs-root",
            str(runs_root),
        ],
    )
    assert run_init_result.exit_code == 0

    run_id = run_init_result.stdout.strip()
    run_metadata = json.loads((runs_root / run_id / "run_metadata.json").read_text(encoding="utf-8"))
    run_effective_config = json.loads(
        (runs_root / run_id / "effective_config.json").read_text(encoding="utf-8")
    )
    assert run_metadata["candidate_id"] == candidate_id
    assert run_effective_config["budget"]["max_turns"] == 20


def test_candidate_create_persists_code_patch_artifact(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )

    patch_file = tmp_path / "change.patch"
    patch_file.write_text(
        "--- a/hello.txt\n+++ b/hello.txt\n@@ -1 +1 @@\n-old\n+new\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    create_result = runner.invoke(
        app,
        [
            "candidate",
            "create",
            "--profile",
            "base",
            "--project",
            "demo",
            "--config-root",
            str(config_root),
            "--candidates-root",
            str(candidates_root),
            "--code-patch",
            str(patch_file),
            "--notes",
            "patch candidate",
        ],
    )

    assert create_result.exit_code == 0
    candidate_id = create_result.stdout.strip()

    candidate_dir = candidates_root / candidate_id
    candidate_metadata = json.loads((candidate_dir / "candidate.json").read_text(encoding="utf-8"))
    assert candidate_metadata["notes"] == "patch candidate"
    assert candidate_metadata["code_patch_artifact"] == "code.patch"
    assert (candidate_dir / "code.patch").read_text(encoding="utf-8") == patch_file.read_text(
        encoding="utf-8"
    )


def test_candidate_create_transfer_materializes_layered_transfer_candidate(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "configs"
    candidates_root = tmp_path / "candidates"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 12}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "workflow", "defaults": {}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {}},
    )
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
            "binding_patch": {"runtime": {"binding": {"agent_id": "codex"}}},
        },
    )
    write_json(
        config_root / "claw_bindings" / "openclaw" / "claude" / "web_scrape.json",
        {
            "binding_id": "openclaw/claude/web_scrape",
            "claw_family": "openclaw",
            "primitive_id": "web_scrape",
            "adapter_kind": "openclaw_acp",
            "binding_patch": {"runtime": {"binding": {"agent_id": "claude"}}},
        },
    )

    local_patch = tmp_path / "local_patch.json"
    write_json(local_patch, {"runtime": {"binding": {"approval_policy": "never"}}})

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "candidate",
            "create-transfer",
            "--profile",
            "base",
            "--project",
            "demo",
            "--config-root",
            str(config_root),
            "--candidates-root",
            str(candidates_root),
            "--method-id",
            "web_scrape/fast_path",
            "--source-binding-id",
            "openclaw/codex/web_scrape",
            "--target-binding-id",
            "openclaw/claude/web_scrape",
            "--local-patch",
            str(local_patch),
            "--notes",
            "portable transfer",
        ],
    )

    assert result.exit_code == 0
    candidate_id = result.stdout.strip()
    proposal = json.loads(
        (candidates_root / candidate_id / "proposal.json").read_text(encoding="utf-8")
    )
    effective_config = json.loads(
        (candidates_root / candidate_id / "effective_config.json").read_text(encoding="utf-8")
    )
    assert proposal["transfer"]["validated_targets"] == ["openclaw/claude/web_scrape"]
    assert effective_config["workflow"]["primitives"]["web_scrape"]["timeout_ms"] == 5000
    assert effective_config["runtime"]["binding"]["agent_id"] == "claude"
    assert effective_config["runtime"]["binding"]["approval_policy"] == "never"
