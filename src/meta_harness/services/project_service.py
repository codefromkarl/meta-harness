from __future__ import annotations

from pathlib import Path


def list_project_names(config_root: Path) -> list[str]:
    projects_dir = config_root / "projects"
    if not projects_dir.exists():
        return []
    return sorted(path.stem for path in projects_dir.glob("*.json"))
