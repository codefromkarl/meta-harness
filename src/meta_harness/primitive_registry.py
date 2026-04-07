from __future__ import annotations

from pathlib import Path

from meta_harness.schemas import PrimitivePack


def load_primitive_pack(path: Path) -> PrimitivePack:
    return PrimitivePack.model_validate_json(path.read_text(encoding="utf-8"))


def list_primitive_packs(config_root: Path) -> list[str]:
    primitive_dir = config_root / "primitives"
    if not primitive_dir.exists():
        return []
    return sorted(
        load_primitive_pack(path).primitive_id
        for path in primitive_dir.glob("*.json")
        if path.is_file()
    )


def load_registered_primitive_pack(config_root: Path, primitive_id: str) -> PrimitivePack:
    primitive_dir = config_root / "primitives"
    if not primitive_dir.exists():
        raise FileNotFoundError(f"primitive pack '{primitive_id}' not found")

    direct_path = primitive_dir / f"{primitive_id}.json"
    if direct_path.exists():
        return load_primitive_pack(direct_path)

    for path in primitive_dir.glob("*.json"):
        if not path.is_file():
            continue
        payload = load_primitive_pack(path)
        if payload.primitive_id == primitive_id:
            return payload

    raise FileNotFoundError(f"primitive pack '{primitive_id}' not found")
