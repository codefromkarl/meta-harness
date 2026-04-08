from __future__ import annotations

from pathlib import Path
from typing import Any

import meta_harness.benchmark_helpers as _helpers

globals().update(
    {
        name: getattr(_helpers, name)
        for name in dir(_helpers)
        if not name.startswith("__")
    }
)


def run_benchmark(
    *,
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    profile_name: str,
    project_name: str,
    task_set_path: Path,
    spec_path: Path,
    focus: str | None = None,
    workspace_source_override: Path | None = None,
    effective_config_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spec = _read_json(spec_path)
    experiment = str(spec.get("experiment", spec_path.stem))
    analysis_mode = str(spec.get("analysis_mode", "parameter"))
    report = spec.get("report") or {}
    scenarios = spec.get("scenarios") or []
    task_scenarios = _extract_task_scenarios(task_set_path)
    variants = spec.get("variants") or []
    if not variants:
        raise ValueError("benchmark spec must include at least one variant")
    repeats = max(1, int(spec.get("repeats", 1)))

    baseline_name = str(spec.get("baseline") or variants[0]["name"])
    results: list[dict[str, Any]] = []
    benchmark_workspace_source = workspace_source_override
    benchmark_snapshot_dir: Path | None = None

    if benchmark_workspace_source is None:
        base_effective_config = (
            dict(effective_config_override)
            if isinstance(effective_config_override, dict)
            else load_effective_config(
                config_root=config_root,
                profile_name=profile_name,
                project_name=project_name,
            )
        )
        snapshot_root = runs_root / "_benchmark_sources"
        snapshot_root.mkdir(parents=True, exist_ok=True)
        benchmark_snapshot_dir = snapshot_root / f"{experiment}-{uuid4().hex[:12]}"
        benchmark_workspace_source = freeze_workspace_source(
            snapshot_dir=benchmark_snapshot_dir,
            effective_config=base_effective_config,
        )
    else:
        base_effective_config = (
            dict(effective_config_override)
            if isinstance(effective_config_override, dict)
            else load_effective_config(
                config_root=config_root,
                profile_name=profile_name,
                project_name=project_name,
            )
        )

    stability_policy = _stability_policy(base_effective_config)

    try:
        for variant in variants:
            variant_name = str(variant["name"])
            variant_type = str(variant.get("variant_type", "parameter"))
            hypothesis = variant.get("hypothesis")
            implementation_id = variant.get("implementation_id")
            expected_signals = variant.get("expected_signals")
            tags = variant.get("tags")
            candidate_harness = _candidate_harness_payload(variant)
            if candidate_harness is not None:
                variant_type = "harness"
                candidate_effective_config = dict(base_effective_config)
                variant_config_patch = variant.get("config_patch")
                if isinstance(variant_config_patch, dict):
                    candidate_effective_config = merge_dicts(
                        candidate_effective_config,
                        variant_config_patch,
                    )
                candidate_effective_config = _candidate_harness_effective_config(
                    base_effective_config=candidate_effective_config,
                    candidate_harness=candidate_harness,
                )
                candidate_proposal = _candidate_harness_proposal_payload(
                    experiment=experiment,
                    variant_name=variant_name,
                    candidate_harness=candidate_harness,
                )
                config_patch = None
                code_patch_path = _resolve_code_patch_path(
                    spec_path, variant.get("code_patch")
                )
            else:
                candidate_effective_config = base_effective_config
                config_patch = variant.get("config_patch")
                candidate_proposal = {
                    "strategy": "benchmark_variant",
                    "experiment": experiment,
                    "variant": variant_name,
                    "variant_type": variant_type,
                    "hypothesis": hypothesis,
                    "implementation_id": implementation_id,
                }
                code_patch_path = _resolve_code_patch_path(
                    spec_path, variant.get("code_patch")
                )
            candidate_id = create_candidate(
                candidates_root=candidates_root,
                config_root=config_root,
                profile_name=profile_name,
                project_name=project_name,
                effective_config_override=candidate_effective_config,
                config_patch=config_patch,
                code_patch_path=code_patch_path,
                notes=f"benchmark:{experiment}:{variant_name}",
                proposal=candidate_proposal,
                reuse_existing=True,
            )
            candidate = load_candidate_record(candidates_root, candidate_id)
            executions: list[dict[str, Any]] = []
            previous_run_dir: Path | None = None
            for repeat_index in range(repeats):
                execution = execute_managed_run(
                    runs_root=runs_root,
                    profile_name=profile_name,
                    project_name=project_name,
                    effective_config=candidate["effective_config"],
                    task_set_path=task_set_path,
                    candidate_id=candidate_id,
                    code_patch_path=Path(candidate["code_patch_path"])
                    if candidate.get("code_patch_path") is not None
                    else None,
                    workspace_source_override=benchmark_workspace_source,
                    run_id=_generate_run_id_with_parity(repeat_index)
                    if repeats > 1
                    else None,
                    seed_root_state_from=previous_run_dir,
                )
                executions.append(execution)
                previous_run_dir = runs_root / str(execution["run_id"])
            run_ids = [execution["run_id"] for execution in executions]
            summarized_score = _summarize_scores(
                [execution["score"] for execution in executions]
            )
            summarized_mechanism = _summarize_mechanisms(
                [_extract_run_mechanism(runs_root / run_id) for run_id in run_ids]
            )
            capability_summary = _capability_summary(
                [
                    task_result
                    for run_id in run_ids
                    for task_result in _load_task_results(runs_root / run_id)
                ]
            )
            variant_stability_policy = _stability_policy(candidate["effective_config"])

            result_item: dict[str, Any] = {
                "name": variant_name,
                "variant_type": variant_type,
                "candidate_id": candidate_id,
                "binding_id": (
                    ((candidate["effective_config"].get("runtime") or {}).get("binding") or {}).get("binding_id")
                    if isinstance(candidate.get("effective_config"), dict)
                    else None
                ),
                "run_id": executions[0]["run_id"],
                "run_ids": run_ids,
                "score": summarized_score,
                "stability": _stability_metrics(
                    [execution["score"] for execution in executions],
                    policy=variant_stability_policy,
                ),
                "mechanism": {
                    **summarized_mechanism,
                    "validation": validate_expected_signals(
                        expected_signals
                        if isinstance(expected_signals, dict)
                        else None,
                        summarized_mechanism,
                    ),
                },
                "capability_gains": capability_summary,
                "stability_policy": variant_stability_policy,
            }
            if candidate_harness is not None:
                result_item["candidate_harness"] = _candidate_harness_result_payload(
                    candidate_id=candidate_id,
                    candidate_harness=candidate_harness,
                )
            if hypothesis is not None:
                result_item["hypothesis"] = hypothesis
            if implementation_id is not None:
                result_item["implementation_id"] = implementation_id
            if expected_signals is not None:
                result_item["expected_signals"] = expected_signals
            if tags is not None:
                result_item["tags"] = tags
            if code_patch_path is not None:
                result_item["code_patch"] = str(code_patch_path)
            results.append(result_item)
    finally:
        if benchmark_snapshot_dir is not None and benchmark_snapshot_dir.exists():
            shutil.rmtree(benchmark_snapshot_dir, ignore_errors=True)

    baseline = next((item for item in results if item["name"] == baseline_name), None)
    if baseline is None:
        raise ValueError(f"baseline variant '{baseline_name}' not found")

    best_by_quality = max(
        results, key=lambda item: float((item.get("score") or {}).get("composite", 0.0))
    )["name"]
    for item in results:
        item["delta_from_baseline"] = _score_delta(
            baseline["score"],
            item["score"],
            focus=focus,
        )
        item["stability_assessment"] = _stability_assessment(
            score=item["score"],
            stability=item["stability"],
            policy=item.get("stability_policy") or stability_policy,
        )
        ranking_score, ranking_penalty, stability_penalty, cost_penalty = (
            _ranking_score(
                score=item["score"],
                baseline_score=baseline["score"],
                stability=item["stability"],
                stability_assessment=item["stability_assessment"],
                policy=item.get("stability_policy") or stability_policy,
            )
        )
        focus_tiebreak_bonus = _focus_tiebreak_bonus(
            item["delta_from_baseline"],
            focus=focus,
        )
        item["focus_tiebreak_bonus"] = focus_tiebreak_bonus
        item["ranking_score"] = _round(ranking_score + focus_tiebreak_bonus)
        item["ranking_penalty"] = ranking_penalty
        item["stability_penalty"] = stability_penalty
        item["cost_penalty"] = cost_penalty
        item["capability_gains"] = _apply_capability_deltas(
            item.get("capability_gains") or {},
            baseline.get("capability_gains") or {},
        )

    best = max(results, key=lambda item: float(item.get("ranking_score", 0.0)))
    best_by_stability = _best_by_stability(results)

    payload = {
        "experiment": experiment,
        "baseline": baseline_name,
        "analysis_mode": analysis_mode,
        "report": report,
        "scenarios": scenarios,
        "task_scenarios": task_scenarios,
        "best_by_quality": best_by_quality,
        "best_by_stability": best_by_stability,
        "best_variant": best["name"],
        "stability_policy": stability_policy,
        "repeat_count": repeats,
        "focus": focus or "all",
        "variants": results,
    }
    payload["report_summary"] = _report_summary(payload)
    return payload

def run_benchmark_suite(
    *,
    config_root: Path,
    runs_root: Path,
    candidates_root: Path,
    profile_name: str,
    project_name: str,
    task_set_path: Path,
    suite_path: Path,
    effective_config_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    suite = _read_json(suite_path)
    suite_name = str(suite.get("suite", suite_path.stem))
    benchmarks = suite.get("benchmarks") or []
    if not benchmarks:
        raise ValueError("benchmark suite must include at least one benchmark entry")

    results: list[dict[str, Any]] = []
    best_by_experiment: dict[str, str] = {}
    best_by_quality_by_experiment: dict[str, str] = {}
    best_by_stability_by_experiment: dict[str, str] = {}
    workspace_source_override: Path | None = None
    snapshot_dir: Path | None = None

    base_effective_config = (
        dict(effective_config_override)
        if isinstance(effective_config_override, dict)
        else load_effective_config(
            config_root=config_root,
            profile_name=profile_name,
            project_name=project_name,
        )
    )
    snapshot_root = runs_root / "_suite_sources"
    snapshot_root.mkdir(parents=True, exist_ok=True)
    snapshot_dir = snapshot_root / f"{suite_name}-{uuid4().hex[:12]}"
    workspace_source_override = freeze_workspace_source(
        snapshot_dir=snapshot_dir,
        effective_config=base_effective_config,
    )

    try:
        for benchmark in benchmarks:
            spec_path = Path(str(benchmark["spec"]))
            focus = benchmark.get("focus")
            benchmark_task_set = benchmark.get("task_set")
            resolved_task_set = (
                Path(str(benchmark_task_set))
                if benchmark_task_set is not None
                else task_set_path
            )
            payload = run_benchmark(
                config_root=config_root,
                runs_root=runs_root,
                candidates_root=candidates_root,
                profile_name=profile_name,
                project_name=project_name,
                task_set_path=resolved_task_set,
                spec_path=spec_path,
                focus=str(focus) if focus is not None else None,
                workspace_source_override=workspace_source_override,
                effective_config_override=base_effective_config,
            )
            results.append(payload)
            best_by_experiment[payload["experiment"]] = payload["best_variant"]
            best_by_quality_by_experiment[payload["experiment"]] = payload[
                "best_by_quality"
            ]
            best_by_stability_by_experiment[payload["experiment"]] = payload[
                "best_by_stability"
            ]
    finally:
        if snapshot_dir is not None and snapshot_dir.exists():
            shutil.rmtree(snapshot_dir, ignore_errors=True)

    return {
        "suite": suite_name,
        "benchmark_count": len(results),
        "best_by_experiment": best_by_experiment,
        "best_by_quality_by_experiment": best_by_quality_by_experiment,
        "best_by_stability_by_experiment": best_by_stability_by_experiment,
        "benchmarks": results,
        "transfer_dashboard": _transfer_dashboard(results),
    }
