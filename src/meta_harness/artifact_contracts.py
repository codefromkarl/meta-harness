from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from meta_harness.schemas import CandidateMetadata, DatasetVersion, EvaluatorRun, ProposalRecord


def _normalize_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_unique_strings(values: Any) -> list[str]:
    normalized: list[str] = []
    if not isinstance(values, list):
        return normalized
    for item in values:
        value = _normalize_optional_string(item)
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def validate_artifact_contract(
    *,
    artifact_kind: str,
    path: Path | str,
) -> dict[str, Any]:
    resolved_path = Path(path)
    normalized_kind = artifact_kind.strip().lower()
    validator = _VALIDATORS.get(normalized_kind)
    if validator is None:
        return {
            "ok": False,
            "artifact_kind": normalized_kind,
            "path": str(resolved_path),
            "missing": [],
            "errors": [f"unsupported artifact kind: {artifact_kind}"],
        }

    result = validator(resolved_path)
    result.setdefault("artifact_kind", normalized_kind)
    result.setdefault("path", str(resolved_path))
    result.setdefault("missing", [])
    result.setdefault("errors", [])
    result["ok"] = not result["missing"] and not result["errors"]
    return result


def validate_artifact_contracts(
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    results = [
        validate_artifact_contract(
            artifact_kind=str(item["artifact_kind"]),
            path=Path(str(item["path"])),
        )
        for item in items
    ]
    return {
        "ok": all(item["ok"] for item in results),
        "items": results,
    }


def _validate_proposal(path: Path) -> dict[str, Any]:
    proposal_dir = path if path.is_dir() else path.parent
    required = ["proposal.json", "proposal_evaluation.json"]
    result = _base_result("proposal", proposal_dir, required)
    proposal_path = proposal_dir / "proposal.json"
    evaluation_path = proposal_dir / "proposal_evaluation.json"
    if proposal_path.exists():
        try:
            ProposalRecord.model_validate_json(proposal_path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - defensive
            result["errors"].append(f"proposal.json invalid: {exc}")
    if evaluation_path.exists():
        _load_json_object(evaluation_path, result, name="proposal_evaluation.json")
    return result


def _validate_dataset(path: Path) -> dict[str, Any]:
    dataset_dir = path if path.is_dir() else path.parent
    required = ["dataset.json", "manifest.json"]
    result = _base_result("dataset", dataset_dir, required)
    dataset_path = dataset_dir / "dataset.json"
    manifest_path = dataset_dir / "manifest.json"
    dataset_payload: dict[str, Any] | None = None
    manifest_payload: dict[str, Any] | None = None
    if dataset_path.exists():
        try:
            dataset_payload = DatasetVersion.model_validate_json(
                dataset_path.read_text(encoding="utf-8")
            ).model_dump(mode="json")
        except Exception as exc:  # pragma: no cover - defensive
            result["errors"].append(f"dataset.json invalid: {exc}")
    if manifest_path.exists():
        manifest_payload = _load_json_object(manifest_path, result, name="manifest.json")
    if dataset_payload is not None and manifest_payload is not None:
        for key in ("dataset_id", "version", "schema_version", "case_count"):
            if manifest_payload.get(key) != dataset_payload.get(key):
                result["errors"].append(
                    f"manifest.json mismatches dataset.json for field '{key}'"
                )
    return result


def _validate_evaluator(path: Path) -> dict[str, Any]:
    evaluator_path = path
    required = [evaluator_path.name]
    result = _base_result("evaluator", evaluator_path.parent, required)
    if evaluator_path.exists():
        try:
            EvaluatorRun.model_validate_json(evaluator_path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - defensive
            result["errors"].append(f"{evaluator_path.name} invalid: {exc}")
    return {
        **result,
        "path": str(evaluator_path),
        "required_files": [evaluator_path.name],
    }


def _validate_candidate(path: Path) -> dict[str, Any]:
    candidate_dir = path if path.is_dir() else path.parent
    required = ["candidate.json", "effective_config.json", "candidate_fingerprint.txt"]
    result = _base_result("candidate", candidate_dir, required)
    candidate_path = candidate_dir / "candidate.json"
    effective_config_path = candidate_dir / "effective_config.json"
    proposal_path = candidate_dir / "proposal.json"

    candidate_payload: dict[str, Any] | None = None
    metadata: CandidateMetadata | None = None
    if candidate_path.exists():
        candidate_payload = _load_json_object(candidate_path, result, name="candidate.json")
        try:
            metadata = CandidateMetadata.model_validate(candidate_payload or {})
        except Exception as exc:  # pragma: no cover - defensive
            result["errors"].append(f"candidate.json invalid: {exc}")
    if effective_config_path.exists():
        _load_json_object(effective_config_path, result, name="effective_config.json")
    proposal_payload = None
    if proposal_path.exists():
        proposal_payload = _load_json_object(proposal_path, result, name="proposal.json")

    if metadata is not None:
        _validate_candidate_lineage_envelope(candidate_payload, metadata, result)
        has_lineage = bool(metadata.proposal_id or metadata.iteration_id)
        if has_lineage and not metadata.source_artifacts:
            result["errors"].append(
                "candidate.json lineage metadata requires non-empty source_artifacts"
            )
        if metadata.proposal_id and metadata.proposal_id not in metadata.source_proposal_ids:
            result["errors"].append(
                "candidate.json proposal lineage requires source_proposal_ids to include proposal_id"
            )
        if metadata.iteration_id and metadata.iteration_id not in metadata.source_iteration_ids:
            result["errors"].append(
                "candidate.json iteration lineage requires source_iteration_ids to include iteration_id"
            )
        if metadata.proposal_id:
            artifact_names = {Path(item).name for item in metadata.source_artifacts}
            if "proposal.json" not in artifact_names:
                result["errors"].append(
                    "candidate.json proposal lineage requires source_artifacts to include proposal.json"
                )
            if "proposal_evaluation.json" not in artifact_names:
                result["errors"].append(
                    "candidate.json proposal lineage requires source_artifacts to include proposal_evaluation.json"
                )
        if len(metadata.source_run_ids) != len(set(metadata.source_run_ids)):
            result["errors"].append("candidate.json source_run_ids must be unique")
        if len(metadata.source_proposal_ids) != len(set(metadata.source_proposal_ids)):
            result["errors"].append("candidate.json source_proposal_ids must be unique")
        if len(metadata.source_iteration_ids) != len(set(metadata.source_iteration_ids)):
            result["errors"].append("candidate.json source_iteration_ids must be unique")
        if len(metadata.source_artifacts) != len(set(metadata.source_artifacts)):
            result["errors"].append("candidate.json source_artifacts must be unique")
        if (
            metadata.proposal_id
            and isinstance(proposal_payload, dict)
            and proposal_payload.get("proposal_id") is not None
            and str(proposal_payload.get("proposal_id")) != metadata.proposal_id
        ):
            result["errors"].append(
                "proposal.json proposal_id does not match candidate.json proposal_id"
            )
    return result


def _validate_candidate_lineage_envelope(
    candidate_payload: dict[str, Any] | None,
    metadata: CandidateMetadata,
    result: dict[str, Any],
) -> None:
    if not isinstance(candidate_payload, dict):
        return
    lineage_payload = candidate_payload.get("lineage")
    if not isinstance(lineage_payload, dict):
        return

    comparisons = [
        (
            "lineage.parent_candidate_id",
            _normalize_optional_string(lineage_payload.get("parent_candidate_id")),
            metadata.parent_candidate_id,
            "parent_candidate_id",
        ),
        (
            "lineage.proposal_id",
            _normalize_optional_string(lineage_payload.get("proposal_id")),
            metadata.proposal_id,
            "proposal_id",
        ),
        (
            "lineage.iteration_id",
            _normalize_optional_string(lineage_payload.get("iteration_id")),
            metadata.iteration_id,
            "iteration_id",
        ),
    ]
    for lineage_name, lineage_value, flat_value, flat_name in comparisons:
        if lineage_value != flat_value:
            result["errors"].append(
                f"candidate.json {lineage_name} does not match {flat_name}"
            )

    list_comparisons = [
        (
            "lineage.source_proposal_ids",
            _normalize_unique_strings(lineage_payload.get("source_proposal_ids")),
            metadata.source_proposal_ids,
            "source_proposal_ids",
        ),
        (
            "lineage.source_iteration_ids",
            _normalize_unique_strings(lineage_payload.get("source_iteration_ids")),
            metadata.source_iteration_ids,
            "source_iteration_ids",
        ),
        (
            "lineage.source_run_ids",
            _normalize_unique_strings(lineage_payload.get("source_run_ids")),
            metadata.source_run_ids,
            "source_run_ids",
        ),
        (
            "lineage.source_artifacts",
            _normalize_unique_strings(lineage_payload.get("source_artifacts")),
            metadata.source_artifacts,
            "source_artifacts",
        ),
    ]
    for lineage_name, lineage_values, flat_values, flat_name in list_comparisons:
        if lineage_values != flat_values:
            result["errors"].append(
                f"candidate.json {lineage_name} does not match {flat_name}"
            )


def _validate_loop(path: Path) -> dict[str, Any]:
    loop_dir = path
    required = ["loop.json", "iteration_history.jsonl", "iterations/"]
    result = _base_result("loop", loop_dir, required)
    summary_path = loop_dir / "loop.json"
    history_path = loop_dir / "iteration_history.jsonl"
    iterations_dir = loop_dir / "iterations"
    iteration_ids: list[str] = []
    if summary_path.exists():
        summary_payload = _load_json_object(summary_path, result, name="loop.json")
        if summary_payload is not None:
            required_keys = {
                "loop_id",
                "profile_name",
                "project_name",
                "request",
                "iteration_count",
                "stop_reason",
            }
            missing_keys = sorted(required_keys - set(summary_payload))
            if missing_keys:
                result["errors"].append(
                    f"loop.json missing required fields: {', '.join(missing_keys)}"
                )
            iterations = summary_payload.get("iterations")
            if isinstance(iterations, list):
                iteration_ids.extend(
                    str(item.get("iteration_id"))
                    for item in iterations
                    if isinstance(item, dict) and item.get("iteration_id")
                )
    if history_path.exists():
        for index, line in enumerate(history_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                result["errors"].append(f"iteration_history.jsonl line {index} invalid: {exc}")
                continue
            if not isinstance(record, dict):
                result["errors"].append(
                    f"iteration_history.jsonl line {index} must contain a JSON object"
                )
                continue
            iteration_id = record.get("iteration_id")
            if not iteration_id:
                result["errors"].append(
                    f"iteration_history.jsonl line {index} missing iteration_id"
                )
                continue
            iteration_ids.append(str(iteration_id))
    if iterations_dir.exists():
        iteration_ids.extend(path.name for path in iterations_dir.iterdir() if path.is_dir())
    normalized_ids = sorted({item for item in iteration_ids if item})
    iteration_required = [
        "iteration.json",
        "proposal_input.json",
        "proposal_output.json",
        "selected_candidate.json",
        "benchmark_summary.json",
        "validation_summary.json",
        "experience_summary.json",
        "next_round_context.json",
        "proposer_context/manifest.json",
    ]
    for iteration_id in normalized_ids:
        iteration_dir = iterations_dir / iteration_id
        if not iteration_dir.exists():
            result["missing"].append(f"iterations/{iteration_id}/")
            continue
        for filename in iteration_required:
            if not (iteration_dir / filename).exists():
                result["missing"].append(f"iterations/{iteration_id}/{filename}")
        iteration_json = iteration_dir / "iteration.json"
        if iteration_json.exists():
            iteration_payload = _load_json_object(
                iteration_json,
                result,
                name=f"iterations/{iteration_id}/iteration.json",
            )
            if iteration_payload is not None and iteration_payload.get("iteration_id") != iteration_id:
                result["errors"].append(
                    f"iterations/{iteration_id}/iteration.json iteration_id mismatch"
                )
        benchmark_summary_path = iteration_dir / "benchmark_summary.json"
        if benchmark_summary_path.exists():
            benchmark_summary = _load_json_object(
                benchmark_summary_path,
                result,
                name=f"iterations/{iteration_id}/benchmark_summary.json",
            )
            if benchmark_summary is not None:
                evaluation = benchmark_summary.get("evaluation")
                if isinstance(evaluation, dict):
                    executor = evaluation.get("executor")
                    benchmark_skipped = bool(evaluation.get("benchmark_skipped"))
                    executor_status = (
                        str(executor.get("status"))
                        if isinstance(executor, dict) and executor.get("status") is not None
                        else ""
                    )
                    if benchmark_skipped or executor_status == "validation_failed":
                        if not isinstance(evaluation.get("validation"), dict):
                            result["errors"].append(
                                f"iterations/{iteration_id}/benchmark_summary.json missing validation payload"
                            )
        validation_summary_path = iteration_dir / "validation_summary.json"
        validation_summary = None
        if validation_summary_path.exists():
            validation_summary = _load_json_object(
                validation_summary_path,
                result,
                name=f"iterations/{iteration_id}/validation_summary.json",
            )
        next_round_context_path = iteration_dir / "next_round_context.json"
        if next_round_context_path.exists():
            next_round_context = _load_json_object(
                next_round_context_path,
                result,
                name=f"iterations/{iteration_id}/next_round_context.json",
            )
            if next_round_context is not None:
                artifacts_payload = next_round_context.get("artifacts")
                if not isinstance(artifacts_payload, dict):
                    result["errors"].append(
                        f"iterations/{iteration_id}/next_round_context.json missing artifacts object"
                    )
                experience_summary_path = iteration_dir / "experience_summary.json"
                linked_experience_summary_path = next_round_context.get(
                    "experience_summary_path"
                )
                if not linked_experience_summary_path:
                    result["errors"].append(
                        f"iterations/{iteration_id}/next_round_context.json missing experience_summary_path"
                    )
                else:
                    linked_path = Path(str(linked_experience_summary_path))
                    candidate_paths = {str(linked_path)}
                    if not linked_path.is_absolute():
                        candidate_paths.add(str((iteration_dir / linked_path).resolve()))
                    else:
                        candidate_paths.add(str(linked_path.resolve()))
                    expected_paths = {
                        str(experience_summary_path),
                        str(experience_summary_path.resolve()),
                    }
                    if candidate_paths.isdisjoint(expected_paths):
                        result["errors"].append(
                            f"iterations/{iteration_id}/next_round_context.json experience_summary_path does not point to experience_summary.json"
                        )
                if validation_summary_path.exists():
                    linked_validation_summary_path = next_round_context.get(
                        "validation_summary_path"
                    )
                    if not linked_validation_summary_path:
                        result["errors"].append(
                            f"iterations/{iteration_id}/next_round_context.json missing validation_summary_path"
                        )
                    else:
                        linked_path = Path(str(linked_validation_summary_path))
                        candidate_paths = {str(linked_path)}
                        if not linked_path.is_absolute():
                            candidate_paths.add(str((iteration_dir / linked_path).resolve()))
                        else:
                            candidate_paths.add(str(linked_path.resolve()))
                        expected_paths = {
                            str(validation_summary_path),
                            str(validation_summary_path.resolve()),
                        }
                        if candidate_paths.isdisjoint(expected_paths):
                            result["errors"].append(
                                f"iterations/{iteration_id}/next_round_context.json validation_summary_path does not point to validation_summary.json"
                            )
                experience_artifact_path = (
                    artifacts_payload.get("experience_summary_json")
                    if isinstance(artifacts_payload, dict)
                    else None
                )
                if not experience_artifact_path:
                    result["errors"].append(
                        f"iterations/{iteration_id}/next_round_context.json missing artifacts.experience_summary_json"
                    )
                else:
                    linked_path = Path(str(experience_artifact_path))
                    candidate_paths = {str(linked_path)}
                    if not linked_path.is_absolute():
                        candidate_paths.add(str((iteration_dir / linked_path).resolve()))
                    else:
                        candidate_paths.add(str(linked_path.resolve()))
                    expected_paths = {
                        str(experience_summary_path),
                        str(experience_summary_path.resolve()),
                    }
                    if candidate_paths.isdisjoint(expected_paths):
                        result["errors"].append(
                            f"iterations/{iteration_id}/next_round_context.json artifacts.experience_summary_json does not point to experience_summary.json"
                        )
                benchmark_artifact_path = (
                    artifacts_payload.get("benchmark_summary_json")
                    if isinstance(artifacts_payload, dict)
                    else None
                )
                selected_candidate_artifact_path = (
                    artifacts_payload.get("selected_candidate_json")
                    if isinstance(artifacts_payload, dict)
                    else None
                )
                proposal_input_expected_path = iteration_dir / "proposal_input.json"
                proposer_context_dir_expected = iteration_dir / "proposer_context"
                proposal_output_expected_path = iteration_dir / "proposal_output.json"
                if not benchmark_artifact_path:
                    result["errors"].append(
                        f"iterations/{iteration_id}/next_round_context.json missing artifacts.benchmark_summary_json"
                    )
                else:
                    linked_path = Path(str(benchmark_artifact_path))
                    candidate_paths = {str(linked_path)}
                    benchmark_summary_expected_path = iteration_dir / "benchmark_summary.json"
                    if not linked_path.is_absolute():
                        candidate_paths.add(str((iteration_dir / linked_path).resolve()))
                    else:
                        candidate_paths.add(str(linked_path.resolve()))
                    expected_paths = {
                        str(benchmark_summary_expected_path),
                        str(benchmark_summary_expected_path.resolve()),
                    }
                    if candidate_paths.isdisjoint(expected_paths):
                        result["errors"].append(
                            f"iterations/{iteration_id}/next_round_context.json artifacts.benchmark_summary_json does not point to benchmark_summary.json"
                        )
                candidate_metadata: CandidateMetadata | None = None
                if not selected_candidate_artifact_path:
                    result["errors"].append(
                        f"iterations/{iteration_id}/next_round_context.json missing artifacts.selected_candidate_json"
                    )
                else:
                    linked_path = Path(str(selected_candidate_artifact_path))
                    candidate_paths = {str(linked_path)}
                    selected_candidate_expected_path = iteration_dir / "selected_candidate.json"
                    if not linked_path.is_absolute():
                        candidate_paths.add(str((iteration_dir / linked_path).resolve()))
                    else:
                        candidate_paths.add(str(linked_path.resolve()))
                    expected_paths = {
                        str(selected_candidate_expected_path),
                        str(selected_candidate_expected_path.resolve()),
                    }
                    if candidate_paths.isdisjoint(expected_paths):
                        result["errors"].append(
                            f"iterations/{iteration_id}/next_round_context.json artifacts.selected_candidate_json does not point to selected_candidate.json"
                        )
                    elif selected_candidate_expected_path.exists():
                        selected_candidate_payload = _load_json_object(
                            selected_candidate_expected_path,
                            result,
                            name=f"iterations/{iteration_id}/selected_candidate.json",
                        )
                        if selected_candidate_payload is not None:
                            selected_candidate_id = selected_candidate_payload.get("candidate_id")
                            selected_candidate_path = selected_candidate_payload.get("candidate_path")
                            if selected_candidate_path:
                                candidate_dir = Path(str(selected_candidate_path))
                                if not candidate_dir.is_absolute():
                                    candidate_dir = (iteration_dir / candidate_dir).resolve()
                                candidate_metadata_path = candidate_dir / "candidate.json"
                                if not candidate_metadata_path.exists():
                                    result["errors"].append(
                                        f"iterations/{iteration_id}/selected_candidate.json candidate_path does not point to candidate artifact"
                                    )
                                else:
                                    candidate_result = _validate_candidate(candidate_dir)
                                    result["missing"].extend(
                                        item
                                        for item in candidate_result["missing"]
                                        if item not in result["missing"]
                                    )
                                    result["errors"].extend(
                                        f"iterations/{iteration_id}/selected candidate artifact: {error}"
                                        for error in candidate_result["errors"]
                                    )
                                    try:
                                        candidate_metadata = CandidateMetadata.model_validate_json(
                                            candidate_metadata_path.read_text(encoding="utf-8")
                                        )
                                    except Exception:  # pragma: no cover - already reported above
                                        candidate_metadata = None
                                    if (
                                        candidate_metadata is not None
                                        and selected_candidate_id is not None
                                        and candidate_metadata.candidate_id != str(selected_candidate_id)
                                    ):
                                        result["errors"].append(
                                            f"iterations/{iteration_id}/selected_candidate.json candidate_id does not match candidate artifact"
                                        )
                                    if (
                                        candidate_metadata is not None
                                        and candidate_metadata.iteration_id is not None
                                        and candidate_metadata.iteration_id != iteration_id
                                    ):
                                        result["errors"].append(
                                            f"iterations/{iteration_id}/selected candidate artifact iteration_id does not match loop iteration"
                                        )
                                    if (
                                        candidate_metadata is not None
                                        and candidate_metadata.iteration_id == iteration_id
                                    ):
                                        selected_run_id = (
                                            str(iteration_payload.get("run_id"))
                                            if isinstance(iteration_payload, dict)
                                            and iteration_payload.get("run_id") is not None
                                            else None
                                        )
                                        if (
                                            selected_run_id is not None
                                            and selected_run_id not in candidate_metadata.source_run_ids
                                        ):
                                            result["errors"].append(
                                                f"iterations/{iteration_id}/selected candidate artifact source_run_ids missing run_id"
                                            )
                                        required_lineage_artifacts = _required_selected_candidate_lineage_artifacts(
                                            iteration_json=iteration_json,
                                            proposal_input_expected_path=proposal_input_expected_path,
                                            proposal_output_expected_path=proposal_output_expected_path,
                                            selected_candidate_expected_path=selected_candidate_expected_path,
                                            next_round_context_path=next_round_context_path,
                                            benchmark_summary_expected_path=benchmark_summary_expected_path,
                                            experience_summary_path=experience_summary_path,
                                            validation_summary_path=validation_summary_path,
                                            proposer_context_dir_expected=proposer_context_dir_expected,
                                        )
                                        for expected_path, label in required_lineage_artifacts:
                                            if str(expected_path) not in candidate_metadata.source_artifacts:
                                                result["errors"].append(
                                                    f"iterations/{iteration_id}/selected candidate artifact source_artifacts missing {label}"
                                                )
                proposal_output_artifact_path = (
                    artifacts_payload.get("proposal_output_json")
                    if isinstance(artifacts_payload, dict)
                    else None
                )
                if not proposal_output_artifact_path:
                    result["errors"].append(
                        f"iterations/{iteration_id}/next_round_context.json missing artifacts.proposal_output_json"
                    )
                else:
                    linked_path = Path(str(proposal_output_artifact_path))
                    candidate_paths = {str(linked_path)}
                    if not linked_path.is_absolute():
                        candidate_paths.add(str((iteration_dir / linked_path).resolve()))
                    else:
                        candidate_paths.add(str(linked_path.resolve()))
                    expected_paths = {
                        str(proposal_output_expected_path),
                        str(proposal_output_expected_path.resolve()),
                    }
                    if candidate_paths.isdisjoint(expected_paths):
                        result["errors"].append(
                            f"iterations/{iteration_id}/next_round_context.json artifacts.proposal_output_json does not point to proposal_output.json"
                        )
                    elif proposal_output_expected_path.exists():
                        proposal_output_payload = _load_json_object(
                            proposal_output_expected_path,
                            result,
                            name=f"iterations/{iteration_id}/proposal_output.json",
                        )
                        if (
                            candidate_metadata is not None
                            and proposal_output_payload is not None
                            and candidate_metadata.proposal_id is not None
                            and proposal_output_payload.get("proposal_id") is not None
                            and str(proposal_output_payload.get("proposal_id"))
                            != candidate_metadata.proposal_id
                        ):
                            result["errors"].append(
                                f"iterations/{iteration_id}/proposal_output.json proposal_id does not match selected candidate artifact"
                            )
                proposer_context_manifest = proposer_context_dir_expected / "manifest.json"
                if proposer_context_manifest.exists():
                    proposer_context_path = (
                        artifacts_payload.get("proposer_context")
                        if isinstance(artifacts_payload, dict)
                        else None
                    )
                    if not proposer_context_path:
                        result["errors"].append(
                            f"iterations/{iteration_id}/next_round_context.json missing artifacts.proposer_context"
                        )
                    else:
                        linked_path = Path(str(proposer_context_path))
                        candidate_paths = {str(linked_path)}
                        if not linked_path.is_absolute():
                            candidate_paths.add(str((iteration_dir / linked_path).resolve()))
                        else:
                            candidate_paths.add(str(linked_path.resolve()))
                        expected_paths = {
                            str((iteration_dir / "proposer_context")),
                            str((iteration_dir / "proposer_context").resolve()),
                        }
                        if candidate_paths.isdisjoint(expected_paths):
                            result["errors"].append(
                                f"iterations/{iteration_id}/next_round_context.json artifacts.proposer_context does not point to proposer_context"
                            )
                if validation_summary_path.exists():
                    validation_artifact_path = (
                        artifacts_payload.get("validation_summary_json")
                        if isinstance(artifacts_payload, dict)
                        else None
                    )
                    if not validation_artifact_path:
                        result["errors"].append(
                            f"iterations/{iteration_id}/next_round_context.json missing artifacts.validation_summary_json"
                        )
                    else:
                        linked_path = Path(str(validation_artifact_path))
                        candidate_paths = {str(linked_path)}
                        if not linked_path.is_absolute():
                            candidate_paths.add(str((iteration_dir / linked_path).resolve()))
                        else:
                            candidate_paths.add(str(linked_path.resolve()))
                        expected_paths = {
                            str(validation_summary_path),
                            str(validation_summary_path.resolve()),
                        }
                        if candidate_paths.isdisjoint(expected_paths):
                            result["errors"].append(
                                f"iterations/{iteration_id}/next_round_context.json artifacts.validation_summary_json does not point to validation_summary.json"
                            )
        if validation_summary is not None and benchmark_summary_path.exists():
            benchmark_summary = _load_json_object(
                benchmark_summary_path,
                result,
                name=f"iterations/{iteration_id}/benchmark_summary.json",
            )
            evaluation = (
                benchmark_summary.get("evaluation")
                if isinstance(benchmark_summary, dict)
                else None
            )
            benchmark_validation = (
                evaluation.get("validation")
                if isinstance(evaluation, dict)
                else None
            )
            if validation_summary and not isinstance(benchmark_validation, dict):
                result["errors"].append(
                    f"iterations/{iteration_id}/benchmark_summary.json missing evaluation.validation for non-empty validation_summary.json"
                )
            if isinstance(benchmark_validation, dict) and benchmark_validation != validation_summary:
                result["errors"].append(
                    f"iterations/{iteration_id}/validation_summary.json does not match benchmark_summary.json evaluation.validation"
                )
    result["iteration_ids"] = normalized_ids
    return result


def _base_result(artifact_kind: str, path: Path, required_files: list[str]) -> dict[str, Any]:
    missing: list[str] = []
    for name in required_files:
        if name.endswith("/"):
            if not (path / name[:-1]).is_dir():
                missing.append(name)
            continue
        if not (path / name).exists():
            missing.append(name)
    return {
        "artifact_kind": artifact_kind,
        "path": str(path),
        "required_files": required_files,
        "missing": missing,
        "errors": [],
    }


def _load_json_object(path: Path, result: dict[str, Any], *, name: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result["errors"].append(f"{name} invalid JSON: {exc}")
        return None
    if not isinstance(payload, dict):
        result["errors"].append(f"{name} must contain a JSON object")
        return None
    return payload


def _required_selected_candidate_lineage_artifacts(
    *,
    iteration_json: Path,
    proposal_input_expected_path: Path,
    proposal_output_expected_path: Path,
    selected_candidate_expected_path: Path,
    next_round_context_path: Path,
    benchmark_summary_expected_path: Path,
    experience_summary_path: Path,
    validation_summary_path: Path,
    proposer_context_dir_expected: Path,
) -> list[tuple[Path, str]]:
    return [
        (iteration_json, "iteration.json"),
        (proposal_input_expected_path, "proposal_input.json"),
        (proposal_output_expected_path, "proposal_output.json"),
        (selected_candidate_expected_path, "selected_candidate.json"),
        (next_round_context_path, "next_round_context.json"),
        (benchmark_summary_expected_path, "benchmark_summary.json"),
        (experience_summary_path, "experience_summary.json"),
        (validation_summary_path, "validation_summary.json"),
        (proposer_context_dir_expected, "proposer_context"),
    ]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate meta-harness artifact contracts")
    parser.add_argument(
        "--artifact",
        action="append",
        default=[],
        metavar="KIND=PATH",
        help="Artifact to validate, for example loop=reports/loops/demo-loop",
    )
    return parser.parse_args(argv)


def _parse_cli_artifacts(raw_items: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in raw_items:
        kind, separator, value = raw.partition("=")
        if not separator or not kind.strip() or not value.strip():
            raise ValueError(f"invalid --artifact value: {raw}")
        items.append({"artifact_kind": kind.strip(), "path": value.strip()})
    return items


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    items = _parse_cli_artifacts(args.artifact)
    summary = validate_artifact_contracts(items)
    print(json.dumps(summary, indent=2))
    return 0 if summary["ok"] else 1


_VALIDATORS = {
    "candidate": _validate_candidate,
    "proposal": _validate_proposal,
    "dataset": _validate_dataset,
    "evaluator": _validate_evaluator,
    "loop": _validate_loop,
}


if __name__ == "__main__":
    raise SystemExit(main())
