from __future__ import annotations

from pathlib import Path

from meta_harness.registry import list_profiles


def list_profile_names(config_root: Path) -> list[str]:
    return list_profiles(config_root)
