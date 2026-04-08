from __future__ import annotations

from pathlib import Path
from typing import Any

from meta_harness.scoring import score_run


def score_run_record(
    *,
    runs_root: Path,
    run_id: str,
    evaluator_names: list[str] | None = None,
) -> dict[str, Any]:
    return score_run(
        runs_root / run_id,
        evaluator_names=evaluator_names,
    )
