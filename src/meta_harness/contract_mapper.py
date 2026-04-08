from __future__ import annotations

from pathlib import Path

from meta_harness.integration_schemas import ArtifactMapping, ProjectObservation
from meta_harness.schemas import PrimitivePack


def map_project_outputs_to_contract(
    *,
    observation: ProjectObservation,
    primitive_pack: PrimitivePack,
) -> tuple[list[ArtifactMapping], list[str]]:
    bridge = primitive_pack.output_contract.get("bridge")
    writes = bridge.get("artifact_writes") if isinstance(bridge, dict) else []
    targets = [
        str(item.get("path"))
        for item in writes
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    ]
    if not targets:
        targets = list(primitive_pack.evaluation_contract.artifact_requirements)

    mappings: list[ArtifactMapping] = []
    missing: list[str] = []
    for target in targets:
        mapping = _find_mapping(target, observation)
        if mapping is None:
            missing.append(target)
            continue
        mappings.append(mapping)
    return mappings, missing


def _find_mapping(target_artifact: str, observation: ProjectObservation) -> ArtifactMapping | None:
    target_name = Path(target_artifact).name
    direct_match = None
    html_candidate = None
    transform_candidate = None
    transform_score = -1.0
    for candidate in observation.output_candidates:
        source_path = str(candidate.get("path") or "")
        source_name = str(candidate.get("artifact_name") or Path(source_path).name)
        source_kind = str(candidate.get("kind") or "")
        if source_name == target_name:
            direct_match = ArtifactMapping(
                source_artifact=source_path,
                target_artifact=target_artifact,
                transform="passthrough",
                confidence=0.98,
            )
            break
        if target_name == "page.html" and source_name.endswith(".html"):
            html_candidate = ArtifactMapping(
                source_artifact=source_path,
                target_artifact=target_artifact,
                transform="passthrough",
                confidence=0.84,
            )
        if target_name == "extracted.json" and source_name.endswith(".json"):
            score = 0.6
            if source_kind == "declared_output":
                score += 0.25
            elif source_kind == "existing_output":
                score += 0.2
            if "/outputs/" in source_path or "\\outputs\\" in source_path:
                score += 0.1
            if score > transform_score:
                transform_score = score
                transform_candidate = ArtifactMapping(
                    source_artifact=source_path,
                    target_artifact=target_artifact,
                    transform=f"map {source_name} fields into primitive extracted payload",
                    confidence=round(min(score, 0.95), 2),
                )
    return direct_match or html_candidate or transform_candidate
