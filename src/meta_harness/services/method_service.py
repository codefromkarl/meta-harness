from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from meta_harness.transfer import inspect_method_binding, plan_method_transfer


def inspect_method_binding_payload(
    *,
    config_root: Path,
    method_id: str,
    binding_id: str,
) -> dict[str, Any]:
    return inspect_method_binding(
        config_root=config_root,
        method_id=method_id,
        binding_id=binding_id,
    )


def plan_method_transfer_payload(
    *,
    config_root: Path,
    method_id: str,
    source_binding_id: str,
    target_binding_id: str,
    method_patch_path: Path | None = None,
    binding_patch_path: Path | None = None,
    local_patch_path: Path | None = None,
) -> dict[str, Any]:
    method_patch = (
        json.loads(method_patch_path.read_text(encoding="utf-8"))
        if method_patch_path is not None
        else None
    )
    binding_patch = (
        json.loads(binding_patch_path.read_text(encoding="utf-8"))
        if binding_patch_path is not None
        else None
    )
    local_patch = (
        json.loads(local_patch_path.read_text(encoding="utf-8"))
        if local_patch_path is not None
        else None
    )
    return plan_method_transfer(
        config_root=config_root,
        method_id=method_id,
        source_binding_id=source_binding_id,
        target_binding_id=target_binding_id,
        method_patch=method_patch,
        binding_patch=binding_patch,
        local_patch=local_patch,
    )
