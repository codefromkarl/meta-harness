from __future__ import annotations

from typing import Any

from meta_harness.evaluator_runtime import (
    average_numeric,
    iter_task_dirs,
    load_benchmark_probe,
    load_task_result,
    read_json_if_exists,
    task_total_latency_ms,
)


def _round(value: float) -> float:
    return round(float(value), 4)


def _normalize_text(text: str) -> str:
    return " ".join(text.casefold().split())


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _find_dataset_observation(probe_payload: dict[str, Any], query: str) -> dict[str, Any]:
    validation = probe_payload.get("validation")
    if not isinstance(validation, dict):
        return {}
    dataset_cases = validation.get("dataset_cases")
    if not isinstance(dataset_cases, list):
        return {}
    for item in dataset_cases:
        if not isinstance(item, dict):
            continue
        if str(item.get("query", "")) == query:
            return item
    return {}


def _parse_cli_retrieval_paths(task_dir) -> tuple[str, list[str]]:
    payload = read_json_if_exists(task_dir / "cli_retrieval_probe.stdout.txt")
    if not isinstance(payload, dict):
        return "", []
    text = payload.get("text")
    text = str(text) if isinstance(text, str) else ""
    paths: list[str] = []
    in_top_files = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("### Top Files"):
            in_top_files = True
            continue
        if in_top_files and line.startswith("### "):
            break
        if not in_top_files:
            continue
        if not line.startswith("- "):
            continue
        candidate = line[2:].strip().strip("`")
        if candidate:
            paths.append(candidate)
    return text, paths


def _parse_mcp_retrieval_artifact(task_dir) -> tuple[str, list[str], list[str]]:
    payload = read_json_if_exists(task_dir / "mcp_retrieval_probe.stdout.txt")
    if not isinstance(payload, dict):
        return "", [], []
    text = payload.get("text")
    text = str(text) if isinstance(text, str) else ""
    top_files = payload.get("topFiles")
    top_files = [str(item) for item in top_files] if isinstance(top_files, list) else []
    grounding_refs = payload.get("groundingRefs")
    grounding_refs = (
        [str(item) for item in grounding_refs]
        if isinstance(grounding_refs, list)
        else []
    )
    return text, top_files, grounding_refs


def evaluate_retrieval_dataset_run(run_dir) -> dict[str, Any]:
    relevant_tasks: list[dict[str, Any]] = []
    for task_dir in iter_task_dirs(run_dir):
        task_result = load_task_result(task_dir)
        dataset_case = task_result.get("dataset_case")
        if not isinstance(dataset_case, dict) or not dataset_case:
            continue
        relevant_tasks.append(
            {
                "task_dir": task_dir,
                "task_result": task_result,
                "dataset_case": dataset_case,
            }
        )

    if not relevant_tasks:
        return {
            "correctness": {},
            "cost": {},
            "capability_scores": {},
            "workflow_scores": {},
            "probes": {},
            "composite_adjustment": 0.0,
        }

    hit_rates: list[float] = []
    path_coverages: list[float] = []
    rank_satisfied: list[float] = []
    grounding_coverages: list[float] = []
    answer_match_rates: list[float] = []
    latency_values: list[float] = []
    success_rates: list[float] = []

    for item in relevant_tasks:
        task_dir = item["task_dir"]
        task_result = item["task_result"]
        dataset_case = item["dataset_case"]
        query = str(dataset_case.get("query", ""))
        observation = _find_dataset_observation(load_benchmark_probe(task_dir), query)
        cli_text, cli_returned_paths = _parse_cli_retrieval_paths(task_dir)
        mcp_text, mcp_returned_paths, mcp_grounding_refs = _parse_mcp_retrieval_artifact(
            task_dir
        )

        expected_paths = _string_list(dataset_case.get("expected_paths"))
        expected_grounding_refs = _string_list(dataset_case.get("expected_grounding_refs"))
        expected_answer_contains = _string_list(dataset_case.get("expected_answer_contains"))
        expected_rank_max = dataset_case.get("expected_rank_max")
        expected_rank_max = int(expected_rank_max) if isinstance(expected_rank_max, (int, float)) else None

        artifact_returned_paths = mcp_returned_paths or cli_returned_paths
        returned_paths = artifact_returned_paths or _string_list(observation.get("returnedPaths"))
        matched_paths = _string_list(observation.get("matchedPaths"))
        if artifact_returned_paths:
            matched_paths = [path for path in expected_paths if path in returned_paths]
        if not matched_paths:
            matched_paths = [path for path in expected_paths if path in returned_paths]
        best_rank = None
        if artifact_returned_paths and matched_paths and returned_paths:
            ranks = [
                returned_paths.index(path) + 1
                for path in matched_paths
                if path in returned_paths
            ]
            if ranks:
                best_rank = min(ranks)
        if best_rank is None:
            raw_best_rank = observation.get("bestRank")
            best_rank = int(raw_best_rank) if isinstance(raw_best_rank, (int, float)) else None
        observed_grounding_refs = mcp_grounding_refs or _string_list(observation.get("groundingRefs"))
        answer_text = mcp_text or cli_text or str(observation.get("answerText", ""))
        normalized_answer = _normalize_text(answer_text)

        matched_expected_paths = [path for path in expected_paths if path in matched_paths]
        path_coverage = (
            len(matched_expected_paths) / len(expected_paths) if expected_paths else 0.0
        )
        hit_rate = 1.0 if matched_expected_paths else 0.0
        rank_ok = (
            1.0
            if matched_expected_paths
            and (expected_rank_max is None or (best_rank is not None and best_rank <= expected_rank_max))
            else 0.0
        )
        grounding_coverage = (
            sum(1 for ref in expected_grounding_refs if ref in observed_grounding_refs)
            / len(expected_grounding_refs)
            if expected_grounding_refs
            else 0.0
        )
        answer_match_rate = (
            sum(1 for token in expected_answer_contains if _normalize_text(token) in normalized_answer)
            / len(expected_answer_contains)
            if expected_answer_contains
            else 0.0
        )

        success_rates.append(1.0 if bool(task_result.get("success")) else 0.0)
        hit_rates.append(hit_rate)
        path_coverages.append(path_coverage)
        rank_satisfied.append(rank_ok)
        grounding_coverages.append(grounding_coverage)
        answer_match_rates.append(answer_match_rate)
        latency_values.append(task_total_latency_ms(task_dir))

    task_success_rate = average_numeric(success_rates)
    hit_rate = average_numeric(hit_rates)
    path_coverage_rate = average_numeric(path_coverages)
    rank_satisfied_rate = average_numeric(rank_satisfied)
    grounding_coverage_rate = average_numeric(grounding_coverages)
    answer_match_rate = average_numeric(answer_match_rates)
    latency_ms = average_numeric(latency_values)

    quality_score = (
        hit_rate * 0.3
        + path_coverage_rate * 0.25
        + rank_satisfied_rate * 0.2
        + grounding_coverage_rate * 0.15
        + answer_match_rate * 0.1
    )
    composite_adjustment = _round((quality_score * 0.8) + (task_success_rate * 0.2) - 0.35)

    return {
        "correctness": {
            "retrieval_dataset_hit_rate": hit_rate,
            "retrieval_dataset_rank_satisfied_rate": rank_satisfied_rate,
            "retrieval_dataset_grounding_coverage_rate": grounding_coverage_rate,
            "retrieval_dataset_answer_match_rate": answer_match_rate,
        },
        "cost": {
            "retrieval_dataset_latency_ms": latency_ms,
        },
        "capability_scores": {
            "retrieval_dataset": {
                "success_rate": task_success_rate,
                "path_coverage_rate": path_coverage_rate,
                "latency_ms": latency_ms,
                "grounding_coverage_rate": grounding_coverage_rate,
                "answer_match_rate": answer_match_rate,
            }
        },
        "workflow_scores": {},
        "probes": {
            "retrieval_dataset.case_count": float(len(relevant_tasks)),
        },
        "composite_adjustment": composite_adjustment,
    }
