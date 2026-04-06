from __future__ import annotations

from pathlib import Path


def list_profiles(config_root: Path) -> list[str]:
    profiles_dir = config_root / "profiles"
    if not profiles_dir.exists():
        return []
    return sorted(path.stem for path in profiles_dir.glob("*.json"))

