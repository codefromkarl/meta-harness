from pathlib import Path
import json

from typer.testing import CliRunner

from meta_harness.cli import app


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_run_init_creates_run_archive_with_effective_config(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    runs_root = tmp_path / "runs"

    write_json(config_root / "platform.json", {"budget": {"max_turns": 10}})
    write_json(
        config_root / "profiles" / "base.json",
        {"description": "Base workflow", "defaults": {"tools": ["rg"]}},
    )
    write_json(
        config_root / "projects" / "demo.json",
        {"workflow": "base", "overrides": {"budget": {"max_turns": 14}}},
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "init",
            "--profile",
            "base",
            "--project",
            "demo",
            "--config-root",
            str(config_root),
            "--runs-root",
            str(runs_root),
        ],
    )

    assert result.exit_code == 0

    run_id = result.stdout.strip()
    run_dir = runs_root / run_id

    assert run_dir.exists()
    assert (run_dir / "tasks").is_dir()
    assert (run_dir / "artifacts").is_dir()

    metadata = json.loads((run_dir / "run_metadata.json").read_text(encoding="utf-8"))
    effective_config = json.loads((run_dir / "effective_config.json").read_text(encoding="utf-8"))

    assert metadata["profile"] == "base"
    assert metadata["project"] == "demo"
    assert effective_config["budget"] == {"max_turns": 14}
    assert effective_config["tools"] == ["rg"]
