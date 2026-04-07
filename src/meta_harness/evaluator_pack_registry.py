from __future__ import annotations

from pathlib import Path

from meta_harness.schemas import EvaluatorPack


def load_evaluator_pack(path: Path) -> EvaluatorPack:
    return EvaluatorPack.model_validate_json(path.read_text(encoding="utf-8"))


def list_evaluator_packs(config_root: Path) -> list[str]:
    pack_dir = config_root / "evaluator_packs"
    if not pack_dir.exists():
        return []
    return sorted(
        load_evaluator_pack(path).pack_id
        for path in pack_dir.glob("*.json")
        if path.is_file()
    )


def load_registered_evaluator_pack(config_root: Path, pack_id: str) -> EvaluatorPack:
    pack_dir = config_root / "evaluator_packs"
    if not pack_dir.exists():
        raise FileNotFoundError(f"evaluator pack '{pack_id}' not found")

    direct_name = pack_id.replace("/", "_")
    direct_path = pack_dir / f"{direct_name}.json"
    if direct_path.exists():
        return load_evaluator_pack(direct_path)

    for path in pack_dir.glob("*.json"):
        if not path.is_file():
            continue
        payload = load_evaluator_pack(path)
        if payload.pack_id == pack_id:
            return payload

    raise FileNotFoundError(f"evaluator pack '{pack_id}' not found")
