from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class RunContextStrategy(Protocol):
    def collect_run_context(self, run_dir: Path) -> dict[str, Any]: ...


class DefaultRunContextStrategy:
    def collect_run_context(self, run_dir: Path) -> dict[str, Any]:
        return {}


def get_run_context_strategy(profile_name: str) -> RunContextStrategy:
    return DefaultRunContextStrategy()
