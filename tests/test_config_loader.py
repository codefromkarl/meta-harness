from pathlib import Path
import json

from meta_harness.config_loader import load_effective_config, load_platform_config


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_load_effective_config_merges_platform_profile_and_project(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    write_json(
        config_root / "platform.json",
        {
            "budget": {"max_turns": 12, "max_tokens": 120000},
            "retrieval": {"top_k": 8},
        },
    )
    write_json(
        config_root / "profiles" / "java_to_rust.json",
        {
            "description": "Java to Rust workflow",
            "defaults": {
                "retrieval": {"top_k": 12, "chunk_size": 1200},
                "tools": ["rg", "cargo"],
            },
        },
    )
    write_json(
        config_root / "projects" / "voidsector.json",
        {
            "workflow": "java_to_rust",
            "overrides": {
                "budget": {"max_turns": 16},
                "style": {"naming": "idiomatic-rust"},
            },
        },
    )

    effective = load_effective_config(
        config_root=config_root,
        profile_name="java_to_rust",
        project_name="voidsector",
    )

    assert effective["budget"] == {"max_turns": 16, "max_tokens": 120000}
    assert effective["retrieval"] == {"top_k": 12, "chunk_size": 1200}
    assert effective["tools"] == ["rg", "cargo"]
    assert effective["style"] == {"naming": "idiomatic-rust"}


def test_load_platform_config_can_merge_project_overrides(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    write_json(
        config_root / "platform.json",
        {
            "archive": {
                "cleanup_logs": {"retention": 10},
                "compaction": {"include_artifacts": False},
            }
        },
    )
    write_json(
        config_root / "projects" / "demo.json",
        {
            "workflow": "base",
            "overrides": {
                "archive": {
                    "cleanup_logs": {"retention": 3},
                    "compaction": {"include_artifacts": True},
                }
            },
        },
    )

    platform = load_platform_config(config_root, project_name="demo")

    assert platform["archive"]["cleanup_logs"]["retention"] == 3
    assert platform["archive"]["compaction"]["include_artifacts"] is True
