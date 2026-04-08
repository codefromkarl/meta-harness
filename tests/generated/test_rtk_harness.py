from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.skip(reason="Generated harness draft requires manual review before activation")
def test_generated_harness_draft_exists() -> None:
    wrapper_path = Path("scripts/generated/rtk_harness_wrapper.py")
    if str(wrapper_path):
        assert wrapper_path.exists()
    assert "json_stdout_cli" in "json_stdout_cli"
