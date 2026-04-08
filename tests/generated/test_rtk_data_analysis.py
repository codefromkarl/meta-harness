from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.mark.skip(reason="Generated integration draft requires manual review before activation")
def test_generated_integration_draft_matches_spec() -> None:
    binding = json.loads(Path("configs/claw_bindings/generated/rtk_data_analysis.json").read_text(encoding="utf-8"))
    assert binding["primitive_id"] == "data_analysis"
    assert binding["binding_id"].startswith("generated/")
    wrapper_path = Path("scripts/generated/rtk_data_analysis_wrapper.py")
    if str(wrapper_path):
        assert wrapper_path.exists()
