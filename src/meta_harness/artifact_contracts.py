from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from meta_harness.schemas import DatasetVersion, EvaluatorRun, ProposalRecord


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
        next_round_context_path = iteration_dir / "next_round_context.json"
        if next_round_context_path.exists():
            next_round_context = _load_json_object(
                next_round_context_path,
                result,
                name=f"iterations/{iteration_id}/next_round_context.json",
            )
            if next_round_context is not None:
                validation_summary_path = iteration_dir / "validation_summary.json"
                if validation_summary_path.exists() and not next_round_context.get(
                    "validation_summary_path"
                ):
                    result["errors"].append(
                        f"iterations/{iteration_id}/next_round_context.json missing validation_summary_path"
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
    "proposal": _validate_proposal,
    "dataset": _validate_dataset,
    "evaluator": _validate_evaluator,
    "loop": _validate_loop,
}


if __name__ == "__main__":
    raise SystemExit(main())
