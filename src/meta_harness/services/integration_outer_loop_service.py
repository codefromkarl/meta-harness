from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from meta_harness.benchmark_engine import run_benchmark
from meta_harness.config_loader import merge_dicts
from meta_harness.integration_schemas import (
    CandidateHarnessPatch,
    HarnessRun,
    HarnessSpec,
    HarnessTaskRef,
    IterationResult,
)
from meta_harness.loop import (
    SearchLoopRequest,
    loop_root_path,
    run_search_loop,
)
from meta_harness.services.optimize_loop_service import build_search_loop_request
from meta_harness.services.benchmark_service import persist_benchmark_payload
from meta_harness.services.integration_benchmark_service import _resolved_reviewed_harness_spec_path
from meta_harness.services.integration_scaffold_service import scaffold_harness_payload


class _IntegrationHarnessLoopPlugin:
    plugin_id = "integration_harness"

    def __init__(
        self,
        *,
        harness_spec: HarnessSpec,
        benchmark_payload: dict[str, Any],
        failure_modes: list[str],
        next_actions: list[str],
        score_summary: dict[str, Any],
        iteration_dir: Path,
        next_round_bundle_path: Path,
        benchmark_spec_path: Path,
    ) -> None:
        self.harness_spec = harness_spec
        self.benchmark_payload = benchmark_payload
        self.failure_modes = failure_modes
        self.next_actions = next_actions
        self.score_summary = score_summary
        self.iteration_dir = iteration_dir
        self.next_round_bundle_path = next_round_bundle_path
        self.benchmark_spec_path = benchmark_spec_path

    def assemble_objective(self, **_: Any) -> dict[str, Any]:
        return {
            "kind": "integration_harness_outer_loop",
            "harness_spec_id": self.harness_spec.spec_id,
            "target_project_path": self.harness_spec.target_project_path,
        }

    def assemble_experience(self, **_: Any) -> dict[str, Any]:
        return {
            "benchmark": self.benchmark_payload,
            "failure_modes": self.failure_modes,
            "next_actions": self.next_actions,
        }

    def build_evaluation_plan(self, **_: Any) -> dict[str, Any]:
        return {
            "kind": "benchmark",
            "benchmark_spec_path": str(self.benchmark_spec_path),
            "selection_policy": "prefer_non_reference",
        }

    def summarize_iteration(
        self,
        *,
        benchmark_payload: dict[str, Any],
        selected_variant: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "score_summary": self.score_summary,
            "failure_modes": self.failure_modes,
            "next_actions": self.next_actions,
            "iteration_dir": str(self.iteration_dir),
            "next_round_input_path": str(self.next_round_bundle_path),
            "selected_variant": str(selected_variant.get("name") or ""),
            "benchmark_best_variant": benchmark_payload.get("best_variant"),
        }


class _StaticCandidateHarnessPatchProposer:
    proposer_id = "external_candidate_harness_patch"

    def __init__(
        self,
        *,
        selected_variant: dict[str, Any],
        score_summary: dict[str, Any],
    ) -> None:
        self.selected_variant = selected_variant
        self.score_summary = score_summary

    def propose(self, **_: Any) -> dict[str, Any]:
        return {
            "proposer_kind": self.proposer_id,
            "proposal": {
                "kind": "external_candidate_harness_patch_set",
                "selected_variant": str(self.selected_variant.get("name") or ""),
                "score_summary": self.score_summary,
            },
            "notes": "integration outer-loop shared loop projection",
        }


def harness_outer_loop_payload(
    *,
    config_root: Path,
    reports_root: Path,
    runs_root: Path,
    candidates_root: Path,
    harness_spec_path: Path,
    profile_name: str,
    project_name: str,
    task_set_path: Path,
    candidate_harness_patches: list[dict[str, Any]],
    iteration_id: str | None = None,
    focus: str | None = None,
    run_benchmark_fn: Any = run_benchmark,
) -> dict[str, Any]:
    resolved_spec_path = _resolved_reviewed_harness_spec_path(harness_spec_path)
    spec = HarnessSpec.model_validate_json(resolved_spec_path.read_text(encoding="utf-8"))
    if not candidate_harness_patches:
        raise ValueError("outer loop requires at least one candidate harness proposal")
    report_dir = resolved_spec_path.parent
    outer_loop_root = report_dir / "outer_loop"
    outer_loop_root.mkdir(parents=True, exist_ok=True)
    history_path = outer_loop_root / "iteration_history.jsonl"
    bundle_index_path = outer_loop_root / "bundle_index.json"

    iteration_index = _next_iteration_index(history_path)
    resolved_iteration_id = iteration_id or f"iteration-{iteration_index:04d}"
    iteration_slug = _sanitize_path_segment(resolved_iteration_id)
    iteration_dir = outer_loop_root / iteration_slug
    iteration_dir.mkdir(parents=True, exist_ok=True)

    scaffold = scaffold_harness_payload(
        config_root=config_root,
        harness_spec_path=resolved_spec_path,
    )
    reference_candidate_harness = _build_reference_candidate_harness(
        spec=spec,
        iteration_id=resolved_iteration_id,
        scaffold=scaffold,
    )
    normalized_patches = [
        CandidateHarnessPatch.model_validate(candidate).model_dump()
        for candidate in candidate_harness_patches
    ]
    proposal_variants = [
        _build_candidate_harness_variant(
            spec=spec,
            iteration_id=resolved_iteration_id,
            candidate_patch=patch,
            scaffold=scaffold,
            index=index,
        )
        for index, patch in enumerate(normalized_patches, start=1)
    ]

    benchmark_spec = _build_outer_loop_benchmark_spec(
        experiment=f"harness-outer-loop-{spec.spec_id}",
        reference_candidate_harness=reference_candidate_harness,
        proposal_variants=proposal_variants,
    )
    benchmark_spec_path = iteration_dir / "benchmark_spec.json"
    benchmark_spec_path.write_text(json.dumps(benchmark_spec, indent=2), encoding="utf-8")
    benchmark_payload = run_benchmark_fn(
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        profile_name=profile_name,
        project_name=project_name,
        task_set_path=task_set_path,
        spec_path=benchmark_spec_path,
        focus=focus,
    )
    benchmark_payload = persist_benchmark_payload(
        reports_root=reports_root,
        payload=benchmark_payload,
    )

    variant_summaries = _summarize_outer_loop_variants(
        benchmark_payload=benchmark_payload,
        runs_root=runs_root,
        task_set_path=task_set_path,
    )
    best_variant = _select_benchmark_variant(variant_summaries)
    proposal_variants_only = [
        item for item in variant_summaries if not bool(item.get("is_reference"))
    ]
    best_proposal_variant = (
        _select_benchmark_variant(proposal_variants_only)
        if proposal_variants_only
        else None
    )
    selected_variant = best_proposal_variant or best_variant
    selected_run_id = selected_variant.get("best_run_id")
    selected_candidate_id = str(selected_variant.get("candidate_id") or "")
    best_candidate_id = str(best_variant.get("candidate_id") or "")
    selected_candidate_harness_id = str(
        selected_variant.get("candidate_harness_id") or selected_candidate_id
    )
    best_candidate_harness_id = str(
        best_variant.get("candidate_harness_id") or best_candidate_id
    )
    selected_candidate_set = {
        str(selected_variant.get("candidate_id") or ""),
        str(selected_variant.get("candidate_harness_id") or ""),
    }
    best_candidate_set = {
        str(best_variant.get("candidate_id") or ""),
        str(best_variant.get("candidate_harness_id") or ""),
    }
    for variant in variant_summaries:
        identifier = str(variant.get("candidate_id") or variant.get("candidate_harness_id") or "")
        if identifier and identifier in selected_candidate_set:
            variant["status"] = "selected"
        else:
            variant["status"] = "benchmarked"
        if identifier and identifier in best_candidate_set:
            variant["best_overall"] = True
        else:
            variant["best_overall"] = False

    harness_runs = [
        _build_harness_run_record(
            variant=variant,
            runs_root=runs_root,
            task_set_path=task_set_path,
            iteration_id=resolved_iteration_id,
        )
        for variant in variant_summaries
    ]
    failure_modes = _collect_failure_modes(harness_runs, runs_root=runs_root)
    score_summary = _build_outer_loop_score_summary(
        benchmark_payload=benchmark_payload,
        variant_summaries=variant_summaries,
        selected_variant=selected_variant,
        best_variant=best_variant,
        best_proposal_variant=best_proposal_variant,
        selected_run_id=selected_run_id,
    )

    next_actions = _build_next_actions(
        benchmark_payload=benchmark_payload,
        selected_variant=selected_variant,
        best_variant=best_variant,
        best_proposal_variant=best_proposal_variant,
        next_round_bundle_path=iteration_dir / "next_round_input.json",
    )
    iteration_result = IterationResult(
        iteration_id=resolved_iteration_id,
        harness_spec_id=spec.spec_id,
        selected_candidate_id=selected_candidate_id or None,
        candidate_ids=[
            str(item.get("candidate_id") or "")
            for item in variant_summaries
            if str(item.get("candidate_id") or "")
        ],
        run_ids=[
            str(run_id)
            for item in variant_summaries
            for run_id in item.get("run_ids") or []
            if str(run_id)
        ],
        score_summary=score_summary,
        failure_modes=failure_modes,
        next_actions=next_actions,
        status="completed",
    )
    current_history = _load_iteration_history(history_path) + [iteration_result.model_dump()]
    iteration_bundle = _build_next_round_bundle(
        harness_spec=spec,
        iteration_id=resolved_iteration_id,
        history=current_history,
        candidate_variants=variant_summaries,
        harness_runs=harness_runs,
        benchmark_payload=benchmark_payload,
        selected_variant=selected_variant,
        best_variant=best_variant,
        best_proposal_variant=best_proposal_variant,
        failure_modes=failure_modes,
        score_summary=score_summary,
        next_actions=next_actions,
    )
    iteration_bundle_path = iteration_dir / "iteration_bundle.json"
    next_round_bundle = _build_next_round_input(
        iteration_bundle=iteration_bundle,
        iteration_bundle_path=iteration_bundle_path,
    )

    benchmark_result_path = iteration_dir / "benchmark_result.json"
    iteration_result_path = iteration_dir / "iteration_result.json"
    next_round_bundle_path = iteration_dir / "next_round_input.json"

    benchmark_result_path.write_text(
        json.dumps(benchmark_payload, indent=2),
        encoding="utf-8",
    )
    iteration_result_path.write_text(
        iteration_result.model_dump_json(indent=2),
        encoding="utf-8",
    )
    iteration_bundle_path.write_text(
        json.dumps(iteration_bundle, indent=2),
        encoding="utf-8",
    )
    next_round_bundle_path.write_text(
        json.dumps(next_round_bundle, indent=2),
        encoding="utf-8",
    )
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(iteration_result.model_dump_json())
        handle.write("\n")
    bundle_index = _build_iteration_bundle_index(
        history=current_history,
        iteration_bundle=iteration_bundle,
        iteration_bundle_path=iteration_bundle_path,
        next_round_bundle_path=next_round_bundle_path,
    )
    bundle_index_path.write_text(
        json.dumps(bundle_index, indent=2),
        encoding="utf-8",
    )
    shared_loop_projection = _persist_shared_loop_projection(
        config_root=config_root,
        reports_root=reports_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        profile_name=profile_name,
        project_name=project_name,
        task_set_path=task_set_path,
        harness_spec=spec,
        iteration_id=resolved_iteration_id,
        iteration_dir=iteration_dir,
        benchmark_payload=benchmark_payload,
        variant_summaries=variant_summaries,
        selected_variant=selected_variant,
        score_summary=score_summary,
        next_actions=next_actions,
        failure_modes=failure_modes,
        iteration_bundle_path=iteration_bundle_path,
        next_round_bundle_path=next_round_bundle_path,
    )

    return {
        "spec_id": spec.spec_id,
        "iteration_id": resolved_iteration_id,
        "iteration_index": iteration_index,
        "harness_spec_path": str(resolved_spec_path),
        "outer_loop_root": str(outer_loop_root),
        "iteration_dir": str(iteration_dir),
        "benchmark_spec_path": str(benchmark_spec_path),
        "benchmark_result_path": str(benchmark_result_path),
        "iteration_result_path": str(iteration_result_path),
        "iteration_bundle_path": str(iteration_bundle_path),
        "bundle_index_path": str(bundle_index_path),
        "iteration_history_path": str(history_path),
        "next_round_input_path": str(next_round_bundle_path),
        "best_candidate_id": best_candidate_id or None,
        "best_candidate_harness_id": best_candidate_harness_id or None,
        "best_run_id": best_variant.get("best_run_id"),
        "selected_candidate_id": selected_candidate_id or None,
        "selected_candidate_harness_id": selected_candidate_harness_id or None,
        "selected_run_id": selected_run_id,
        "benchmark": benchmark_payload,
        "iteration_result": iteration_result.model_dump(),
        "iteration_history": current_history,
        "candidate_harnesses": variant_summaries,
        "harness_runs": [record.model_dump() for record in harness_runs],
        "iteration_bundle": iteration_bundle,
        "bundle_index": bundle_index,
        "next_round_input": next_round_bundle,
        **shared_loop_projection,
    }

def _build_reference_candidate_harness(
    *,
    spec: HarnessSpec,
    iteration_id: str,
    scaffold: dict[str, Any],
) -> dict[str, Any]:
    wrapper_path = str(scaffold["wrapper_path"])
    return {
        "candidate_harness_id": f"{spec.spec_id}:reference",
        "harness_spec_id": spec.spec_id,
        "iteration_id": iteration_id,
        "proposal_id": None,
        "title": "Reference scaffold",
        "summary": f"Scaffolded baseline harness for `{spec.spec_id}`.",
        "change_kind": "wrapper_patch",
        "target_files": [
            str(scaffold["wrapper_path"]),
            str(scaffold["test_path"]),
        ],
        "patch": {},
        "rationale": ["baseline scaffold"],
        "provenance": {
            "source": "scaffold_harness_payload",
            "scaffold_plan_path": str(scaffold["scaffold_plan_path"]),
            "scaffold_result_path": str(scaffold["scaffold_result_path"]),
        },
        "status": "benchmarked",
        "runtime": {
            "binding": {
                "binding_id": f"harness/{Path(spec.target_project_path).name}",
                "adapter_kind": "command",
                "command": ["python", wrapper_path, "${phase_command_json}"],
            }
        },
        "wrapper_path": wrapper_path,
        "source_artifacts": [
            str(scaffold["wrapper_path"]),
            str(scaffold["test_path"]),
            str(scaffold["scaffold_plan_path"]),
            str(scaffold["scaffold_result_path"]),
        ],
    }

def _build_candidate_harness_variant(
    *,
    spec: HarnessSpec,
    iteration_id: str,
    candidate_patch: dict[str, Any],
    scaffold: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    proposal_id = str(
        candidate_patch.get("candidate_id")
        or candidate_patch.get("proposal_id")
        or f"{spec.spec_id}:proposal-{index:02d}"
    )
    candidate_harness_id = str(
        candidate_patch.get("candidate_harness_id")
        or proposal_id
    )
    runtime_patch: dict[str, Any] = {}
    patch_payload = candidate_patch.get("patch")
    if isinstance(patch_payload, dict):
        runtime_patch = dict(patch_payload.get("runtime") or {}) if isinstance(patch_payload.get("runtime"), dict) else {}
    config_patch = _candidate_config_patch(candidate_patch)
    runtime = _candidate_runtime_payload(candidate_patch, scaffold, proposal_id)

    candidate_harness = {
        "candidate_harness_id": candidate_harness_id,
        "harness_spec_id": spec.spec_id,
        "iteration_id": iteration_id,
        "proposal_id": proposal_id,
        "title": str(candidate_patch.get("title") or ""),
        "summary": str(candidate_patch.get("summary") or ""),
        "change_kind": str(candidate_patch.get("change_kind") or "wrapper_patch"),
        "target_files": [
            str(item)
            for item in candidate_patch.get("target_files") or []
            if str(item)
        ],
        "patch": dict(candidate_patch.get("patch") or {}),
        "rationale": [
            str(item)
            for item in candidate_patch.get("rationale") or []
            if str(item)
        ],
        "provenance": dict(candidate_patch.get("provenance") or {}),
        "status": str(candidate_patch.get("status") or "proposed"),
        "config_patch": config_patch,
        "runtime": runtime,
    }
    if runtime_patch:
        candidate_harness["runtime"] = merge_dicts(runtime, runtime_patch)
    return candidate_harness

def _candidate_config_patch(candidate_patch: dict[str, Any]) -> dict[str, Any]:
    patch_payload = candidate_patch.get("patch")
    if not isinstance(patch_payload, dict):
        return {}
    config_patch = {
        key: value for key, value in patch_payload.items() if key != "runtime"
    }
    if isinstance(patch_payload.get("config_patch"), dict):
        config_patch = merge_dicts(config_patch, patch_payload["config_patch"])
    return config_patch

def _candidate_runtime_payload(
    candidate_patch: dict[str, Any],
    scaffold: dict[str, Any],
    proposal_id: str,
) -> dict[str, Any]:
    wrapper_path = str(candidate_patch.get("wrapper_path") or scaffold["wrapper_path"])
    runtime_binding = {
        "binding_id": str(
            candidate_patch.get("binding_id")
            or f"harness/{proposal_id.replace(':', '-')}"
        ),
        "adapter_kind": "command",
        "command": ["python", wrapper_path, "${phase_command_json}"],
    }
    patch_payload = candidate_patch.get("patch")
    if isinstance(patch_payload, dict):
        runtime_patch = patch_payload.get("runtime")
        if isinstance(runtime_patch, dict):
            runtime_binding = merge_dicts(runtime_binding, runtime_patch.get("binding") if isinstance(runtime_patch.get("binding"), dict) else runtime_patch)
    return {"binding": runtime_binding}

def _build_outer_loop_benchmark_spec(
    *,
    experiment: str,
    reference_candidate_harness: dict[str, Any],
    proposal_variants: list[dict[str, Any]],
) -> dict[str, Any]:
    variants = [
        {
            "name": "reference",
            "variant_type": "harness",
            "candidate_harness": reference_candidate_harness,
            "is_reference": True,
        }
    ]
    for candidate in proposal_variants:
        variants.append(
            {
                "name": str(
                    candidate.get("candidate_harness_id")
                    or candidate.get("proposal_id")
                    or candidate.get("title")
                    or "candidate"
                ),
                "variant_type": "harness",
                "candidate_harness": candidate,
                "is_reference": False,
            }
        )
    return {
        "experiment": experiment,
        "baseline": "reference",
        "variants": variants,
    }

def _summarize_outer_loop_variants(
    *,
    benchmark_payload: dict[str, Any],
    runs_root: Path,
    task_set_path: Path,
) -> list[dict[str, Any]]:
    task_refs = _build_task_refs(task_set_path)
    baseline_name = str(benchmark_payload.get("baseline") or "")
    summaries: list[dict[str, Any]] = []
    for variant in benchmark_payload.get("variants") or []:
        if not isinstance(variant, dict):
            continue
        candidate_harness = dict(variant.get("candidate_harness") or {})
        variant_name = str(
            variant.get("name") or candidate_harness.get("candidate_harness_id") or "candidate"
        )
        is_reference = bool(variant.get("is_reference")) or (
            bool(baseline_name) and variant_name == baseline_name
        )
        run_ids = [str(run_id) for run_id in variant.get("run_ids") or [] if str(run_id)]
        best_run_id = _select_best_run_id(runs_root=runs_root, run_ids=run_ids)
        summary = {
            "name": variant_name,
            "variant_type": str(variant.get("variant_type") or "harness"),
            "candidate_id": str(variant.get("candidate_id") or ""),
            "candidate_harness_id": str(
                candidate_harness.get("candidate_harness_id")
                or candidate_harness.get("candidate_id")
                or variant.get("candidate_id")
                or ""
            ),
            "harness_spec_id": str(candidate_harness.get("harness_spec_id") or ""),
            "proposal_id": candidate_harness.get("proposal_id"),
            "iteration_id": candidate_harness.get("iteration_id"),
            "title": str(candidate_harness.get("title") or ""),
            "summary": str(candidate_harness.get("summary") or ""),
            "change_kind": str(candidate_harness.get("change_kind") or "wrapper_patch"),
            "target_files": list(candidate_harness.get("target_files") or []),
            "patch": dict(candidate_harness.get("patch") or {}),
            "rationale": list(candidate_harness.get("rationale") or []),
            "wrapper_path": candidate_harness.get("wrapper_path"),
            "source_artifacts": list(candidate_harness.get("source_artifacts") or []),
            "provenance": dict(candidate_harness.get("provenance") or {}),
            "status": "benchmarked",
            "is_reference": is_reference,
            "score": dict(variant.get("score") or {}),
            "stability": dict(variant.get("stability") or {}),
            "ranking_score": float(variant.get("ranking_score", 0.0) or 0.0),
            "run_id": variant.get("run_id"),
            "run_ids": run_ids,
            "best_run_id": best_run_id,
            "best_run": _load_run_snapshot(runs_root, best_run_id, task_refs) if best_run_id is not None else None,
            "best_run_status": _load_run_status(runs_root, best_run_id) if best_run_id is not None else None,
            "failure_modes": _collect_failure_modes_for_variant(runs_root, run_ids),
        }
        summaries.append(summary)
    return summaries

def _build_task_refs(task_set_path: Path) -> list[HarnessTaskRef]:
    task_set = json.loads(task_set_path.read_text(encoding="utf-8"))
    task_refs: list[HarnessTaskRef] = []
    for task in task_set.get("tasks", []):
        if not isinstance(task, dict):
            continue
        phases = task.get("phases") or []
        phase = phases[0] if phases and isinstance(phases[0], dict) else {}
        task_refs.append(
            HarnessTaskRef(
                task_id=str(task.get("task_id") or ""),
                phase=str(phase.get("phase") or task.get("task_id") or "task"),
                command=[str(item) for item in phase.get("command") or [] if str(item)],
                workdir=str(task.get("workdir")) if task.get("workdir") is not None else None,
                expectations=dict(task.get("expectations") or {}),
            )
        )
    return task_refs

def _build_harness_run_record(
    *,
    variant: dict[str, Any],
    runs_root: Path,
    task_set_path: Path,
    iteration_id: str,
) -> HarnessRun:
    run_id = variant.get("best_run_id") or variant.get("run_id")
    task_refs = _build_task_refs(task_set_path)
    score = _load_score_report(runs_root, str(run_id)) if run_id is not None else {}
    artifact_refs = _collect_run_artifact_refs(runs_root, str(run_id)) if run_id is not None else []
    trace_refs = _collect_run_trace_refs(runs_root, str(run_id)) if run_id is not None else []
    status = "failed" if _load_run_status(runs_root, str(run_id)) == "failed" else "completed"
    return HarnessRun(
        run_id=str(run_id) if run_id is not None else "",
        candidate_id=str(variant.get("candidate_id") or ""),
        harness_spec_id=str(variant.get("harness_spec_id") or ""),
        iteration_id=iteration_id,
        wrapper_path=str(variant.get("wrapper_path")) if variant.get("wrapper_path") is not None else None,
        task_refs=task_refs,
        score=score,
        trace_refs=trace_refs,
        artifact_refs=artifact_refs,
        status=status,
    )

def _build_outer_loop_score_summary(
    *,
    benchmark_payload: dict[str, Any],
    variant_summaries: list[dict[str, Any]],
    selected_variant: dict[str, Any],
    best_variant: dict[str, Any],
    best_proposal_variant: dict[str, Any] | None,
    selected_run_id: str | None,
) -> dict[str, Any]:
    return {
        "best_candidate": {
            "candidate_id": best_variant.get("candidate_id"),
            "candidate_harness_id": best_variant.get("candidate_harness_id"),
            "variant_name": best_variant.get("name"),
            "run_id": best_variant.get("best_run_id"),
            "score": dict(best_variant.get("score") or {}),
            "ranking_score": best_variant.get("ranking_score"),
        },
        "best_proposal_candidate": (
            {
                "candidate_id": best_proposal_variant.get("candidate_id"),
                "candidate_harness_id": best_proposal_variant.get("candidate_harness_id"),
                "variant_name": best_proposal_variant.get("name"),
                "run_id": best_proposal_variant.get("best_run_id"),
                "score": dict(best_proposal_variant.get("score") or {}),
                "ranking_score": best_proposal_variant.get("ranking_score"),
            }
            if best_proposal_variant is not None
            else None
        ),
        "selected_candidate": {
            "candidate_id": selected_variant.get("candidate_id"),
            "candidate_harness_id": selected_variant.get("candidate_harness_id"),
            "variant_name": selected_variant.get("name"),
            "run_id": selected_run_id,
            "score": dict(selected_variant.get("score") or {}),
            "ranking_score": selected_variant.get("ranking_score"),
        },
        "best_run_id": best_variant.get("best_run_id"),
        "selected_run_id": selected_run_id,
        "reference_candidate": next(
            (
                {
                    "candidate_id": item.get("candidate_id"),
                    "candidate_harness_id": item.get("candidate_harness_id"),
                    "variant_name": item.get("name"),
                    "run_id": item.get("best_run_id"),
                    "score": dict(item.get("score") or {}),
                    "ranking_score": item.get("ranking_score"),
                }
                for item in variant_summaries
                if item.get("is_reference")
            ),
            None,
        ),
        "benchmark": {
            "best_variant": benchmark_payload.get("best_variant"),
            "best_by_quality": benchmark_payload.get("best_by_quality"),
            "best_by_stability": benchmark_payload.get("best_by_stability"),
            "report_summary": benchmark_payload.get("report_summary"),
        },
        "selection_criteria": [
            "benchmark ranking_score",
            "benchmark stability",
            "best run composite score",
        ],
        "variant_count": len(variant_summaries),
    }

def _build_next_round_bundle(
    *,
    harness_spec: HarnessSpec,
    iteration_id: str,
    history: list[dict[str, Any]],
    candidate_variants: list[dict[str, Any]],
    harness_runs: list[HarnessRun],
    benchmark_payload: dict[str, Any],
    selected_variant: dict[str, Any],
    best_variant: dict[str, Any],
    best_proposal_variant: dict[str, Any] | None,
    failure_modes: list[str],
    score_summary: dict[str, Any],
    next_actions: list[str],
) -> dict[str, Any]:
    run_lookup = _build_harness_run_lookup(harness_runs)
    selected_candidate_harness = {
        "candidate_harness_id": selected_variant.get("candidate_harness_id"),
        "candidate_id": selected_variant.get("candidate_id"),
        "proposal_id": selected_variant.get("proposal_id"),
        "iteration_id": selected_variant.get("iteration_id"),
        "wrapper_path": selected_variant.get("wrapper_path"),
        "source_artifacts": list(selected_variant.get("source_artifacts") or []),
        "provenance": dict(selected_variant.get("provenance") or {}),
        "status": "selected",
    }
    candidate_harnesses = []
    for item in candidate_variants:
        harness_run = _lookup_harness_run(
            run_lookup,
            candidate_id=str(item.get("candidate_id") or ""),
            candidate_harness_id=str(item.get("candidate_harness_id") or ""),
        )
        failure_samples = _collect_failure_samples_for_variant(
            harness_run=harness_run,
            variant=item,
        )
        candidate_harnesses.append(
            {
                "candidate_harness_id": item.get("candidate_harness_id"),
                "candidate_id": item.get("candidate_id"),
                "proposal_id": item.get("proposal_id"),
                "iteration_id": item.get("iteration_id"),
                "variant_name": item.get("name"),
                "variant_type": item.get("variant_type"),
                "candidate_definition": {
                    "title": item.get("title"),
                    "summary": item.get("summary"),
                    "change_kind": item.get("change_kind"),
                    "target_files": list(item.get("target_files") or []),
                    "patch": dict(item.get("patch") or {}),
                    "rationale": list(item.get("rationale") or []),
                },
                "status": item.get("status"),
                "is_reference": item.get("is_reference"),
                "score": dict(item.get("score") or {}),
                "stability": dict(item.get("stability") or {}),
                "ranking_score": item.get("ranking_score"),
                "run_id": item.get("run_id"),
                "run_ids": list(item.get("run_ids") or []),
                "best_run_id": item.get("best_run_id"),
                "best_run": item.get("best_run"),
                "trace_refs": list(harness_run.trace_refs) if harness_run is not None else [],
                "artifact_refs": list(harness_run.artifact_refs) if harness_run is not None else [],
                "failure_modes": list(item.get("failure_modes") or []),
                "failure_samples": failure_samples,
                "wrapper_path": item.get("wrapper_path"),
                "source_artifacts": list(item.get("source_artifacts") or []),
                "provenance": dict(item.get("provenance") or {}),
            }
        )
    bundle = {
        "kind": "harness_iteration_bundle",
        "spec_id": harness_spec.spec_id,
        "iteration_id": iteration_id,
        "history": history,
        "candidate_harnesses": candidate_harnesses,
        "selected_candidate_harness": selected_candidate_harness,
        "best_candidate_harness": {
            "candidate_harness_id": best_variant.get("candidate_harness_id"),
            "candidate_id": best_variant.get("candidate_id"),
            "variant_name": best_variant.get("name"),
            "best_run_id": best_variant.get("best_run_id"),
            "score": dict(best_variant.get("score") or {}),
            "ranking_score": best_variant.get("ranking_score"),
        },
        "best_proposal_candidate_harness": (
            {
                "candidate_harness_id": best_proposal_variant.get("candidate_harness_id"),
                "candidate_id": best_proposal_variant.get("candidate_id"),
                "variant_name": best_proposal_variant.get("name"),
                "best_run_id": best_proposal_variant.get("best_run_id"),
                "score": dict(best_proposal_variant.get("score") or {}),
                "ranking_score": best_proposal_variant.get("ranking_score"),
            }
            if best_proposal_variant is not None
            else None
        ),
        "harness_runs": [record.model_dump() for record in harness_runs],
        "benchmark": {
            "experiment": benchmark_payload.get("experiment"),
            "best_variant": benchmark_payload.get("best_variant"),
            "best_by_quality": benchmark_payload.get("best_by_quality"),
            "best_by_stability": benchmark_payload.get("best_by_stability"),
            "report_summary": benchmark_payload.get("report_summary"),
        },
        "failure_modes": failure_modes,
        "score_summary": score_summary,
        "summary": {
            "selected_candidate_id": selected_variant.get("candidate_id"),
            "selected_candidate_harness_id": selected_variant.get("candidate_harness_id"),
            "best_candidate_id": best_variant.get("candidate_id"),
            "best_candidate_harness_id": best_variant.get("candidate_harness_id"),
            "failure_mode_count": len(failure_modes),
            "next_actions": list(next_actions),
        },
        "proposer_input": {
            "iteration_id": iteration_id,
            "harness_spec_id": harness_spec.spec_id,
            "summary": {
                "selected_candidate_id": selected_variant.get("candidate_id"),
                "selected_candidate_harness_id": selected_variant.get("candidate_harness_id"),
                "best_candidate_id": best_variant.get("candidate_id"),
                "best_candidate_harness_id": best_variant.get("candidate_harness_id"),
                "failure_modes": failure_modes,
                "next_actions": list(next_actions),
            },
            "selected_candidate_harness": selected_candidate_harness,
            "candidate_harnesses": candidate_harnesses,
            "history": history,
            "failure_modes": failure_modes,
            "score_summary": score_summary,
            "bundle_kind": "next_round_proposer_input",
        },
    }
    return bundle

def _build_next_round_input(
    *,
    iteration_bundle: dict[str, Any],
    iteration_bundle_path: Path,
) -> dict[str, Any]:
    proposer_input = dict(iteration_bundle.get("proposer_input") or {})
    proposer_input["kind"] = "next_round_proposer_input"
    proposer_input["bundle_path"] = str(iteration_bundle_path)
    proposer_input["bundle_kind"] = str(iteration_bundle.get("kind") or "harness_iteration_bundle")
    proposer_input["selected_candidate_harness"] = dict(
        iteration_bundle.get("selected_candidate_harness") or {}
    )
    proposer_input["best_candidate_harness"] = dict(
        iteration_bundle.get("best_candidate_harness") or {}
    )
    proposer_input["iteration_summary"] = dict(iteration_bundle.get("summary") or {})
    return proposer_input


def _persist_shared_loop_projection(
    *,
    config_root: Path,
    reports_root: Path,
    runs_root: Path,
    candidates_root: Path,
    profile_name: str,
    project_name: str,
    task_set_path: Path,
    harness_spec: HarnessSpec,
    iteration_id: str,
    iteration_dir: Path,
    benchmark_payload: dict[str, Any],
    variant_summaries: list[dict[str, Any]],
    selected_variant: dict[str, Any],
    score_summary: dict[str, Any],
    next_actions: list[str],
    failure_modes: list[str],
    iteration_bundle_path: Path,
    next_round_bundle_path: Path,
) -> dict[str, str]:
    requested_loop_id = (
        f"harness-outer-loop-{harness_spec.spec_id}-{_sanitize_path_segment(iteration_id)}"
    )
    benchmark_spec_path = iteration_dir / "benchmark_spec.json"
    request = build_search_loop_request(
        config_root=config_root,
        runs_root=runs_root,
        candidates_root=candidates_root,
        profile_name=profile_name,
        project_name=project_name,
        task_set_path=task_set_path,
        loop_id=requested_loop_id,
        plugin_id="integration_harness",
        proposer_id="external_candidate_harness_patch",
        reports_root=reports_root,
        max_iterations=1,
        focus=str(benchmark_payload.get("focus") or "all"),
        evaluation_mode="benchmark",
    )
    loop_summary = run_search_loop(
        request,
        task_plugin=_IntegrationHarnessLoopPlugin(
            harness_spec=harness_spec,
            benchmark_payload=benchmark_payload,
            failure_modes=failure_modes,
            next_actions=next_actions,
            score_summary=score_summary,
            iteration_dir=iteration_dir,
            next_round_bundle_path=next_round_bundle_path,
            benchmark_spec_path=benchmark_spec_path,
        ),
        proposer=_StaticCandidateHarnessPatchProposer(
            selected_variant=selected_variant,
            score_summary=score_summary,
        ),
        benchmark_fn=lambda **_: {
            **benchmark_payload,
            "variants": variant_summaries,
        },
        reports_root=reports_root,
    )
    resolved_loop_id = str(loop_summary.loop_id or request.loop_id or requested_loop_id)
    loop_dir = Path(str(loop_summary.loop_dir or loop_root_path(reports_root, resolved_loop_id)))
    loop_summary_path = loop_dir / "loop.json"
    iteration_path = ""
    if loop_summary.iterations:
        iteration_path = str(
            loop_summary.iterations[0].artifacts.get("iteration_json") or ""
        )
    return {
        "loop_id": resolved_loop_id,
        "loop_dir": str(loop_dir),
        "loop_summary_path": str(loop_summary_path),
        "loop_iteration_path": iteration_path,
    }

def _build_harness_run_lookup(
    harness_runs: list[HarnessRun],
) -> dict[str, HarnessRun]:
    lookup: dict[str, HarnessRun] = {}
    for harness_run in harness_runs:
        candidate_id = str(harness_run.candidate_id or "")
        if candidate_id:
            lookup[candidate_id] = harness_run
    return lookup

def _lookup_harness_run(
    run_lookup: dict[str, HarnessRun],
    *,
    candidate_id: str,
    candidate_harness_id: str,
) -> HarnessRun | None:
    return run_lookup.get(candidate_id) or run_lookup.get(candidate_harness_id)

def _collect_failure_samples_for_variant(
    *,
    harness_run: HarnessRun | None,
    variant: dict[str, Any],
) -> list[dict[str, Any]]:
    if harness_run is None:
        return []
    samples: list[dict[str, Any]] = []
    best_run = variant.get("best_run")
    if isinstance(best_run, dict):
        task_refs = list(best_run.get("task_refs") or [])
        trace_refs = list(best_run.get("trace_refs") or [])
        for task_ref in task_refs:
            if not isinstance(task_ref, dict):
                continue
            samples.append(
                {
                    "run_id": best_run.get("run_id"),
                    "task_id": task_ref.get("task_id"),
                    "phase": task_ref.get("phase"),
                    "trace_refs": trace_refs,
                }
            )
    if not samples and harness_run.trace_refs:
        samples.append(
            {
                "run_id": harness_run.run_id,
                "task_id": None,
                "phase": None,
                "trace_refs": list(harness_run.trace_refs),
            }
        )
    return samples

def _build_iteration_bundle_index(
    *,
    history: list[dict[str, Any]],
    iteration_bundle: dict[str, Any],
    iteration_bundle_path: Path,
    next_round_bundle_path: Path,
) -> dict[str, Any]:
    iterations = [
        {
            "iteration_id": str(item.get("iteration_id") or ""),
            "selected_candidate_id": item.get("selected_candidate_id"),
            "status": item.get("status"),
        }
        for item in history
    ]
    return {
        "kind": "harness_iteration_bundle_index",
        "spec_id": iteration_bundle.get("spec_id"),
        "latest_iteration_id": iteration_bundle.get("iteration_id"),
        "latest_bundle_path": str(iteration_bundle_path),
        "latest_next_round_input_path": str(next_round_bundle_path),
        "iteration_count": len(iterations),
        "iterations": iterations,
    }

def _build_next_actions(
    *,
    benchmark_payload: dict[str, Any],
    selected_variant: dict[str, Any],
    best_variant: dict[str, Any],
    best_proposal_variant: dict[str, Any] | None,
    next_round_bundle_path: Path,
) -> list[str]:
    actions: list[str] = [
        f"load next proposer input from {next_round_bundle_path}",
    ]
    if best_proposal_variant is not None and best_proposal_variant.get("candidate_id") != best_variant.get("candidate_id"):
        actions.append(
            f"refine candidate {best_proposal_variant.get('candidate_id')} against best candidate {best_variant.get('candidate_id')}"
        )
    elif selected_variant.get("candidate_id") == best_variant.get("candidate_id"):
        actions.append(f"promote selected candidate {selected_variant.get('candidate_id')}")
    if benchmark_payload.get("best_variant") == "reference":
        actions.append("reference scaffold remains the strongest baseline")
    return actions

def _load_iteration_history(history_path: Path) -> list[dict[str, Any]]:
    if not history_path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in history_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        records.append(json.loads(line))
    return records

def _next_iteration_index(history_path: Path) -> int:
    return len(_load_iteration_history(history_path)) + 1

def _sanitize_path_segment(value: str) -> str:
    sanitized = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in value.strip()
    )
    return sanitized.strip("-") or "iteration"

def _select_benchmark_variant(variants: list[dict[str, Any]]) -> dict[str, Any]:
    if not variants:
        raise ValueError("outer loop benchmark returned no variants")
    return max(
        variants,
        key=lambda item: (
            float(item.get("ranking_score", 0.0)),
            float((item.get("score") or {}).get("composite", 0.0)),
            float((item.get("stability") or {}).get("composite_range", 0.0)),
        ),
    )

def _select_best_run_id(*, runs_root: Path, run_ids: list[str]) -> str | None:
    if not run_ids:
        return None
    scored: list[tuple[tuple[float, float, float], str]] = []
    for run_id in run_ids:
        score = _load_score_report(runs_root, run_id)
        stability = score.get("stability") if isinstance(score.get("stability"), dict) else {}
        scored.append(
            (
                (
                    float(score.get("composite", 0.0)),
                    float((stability or {}).get("composite_range", 0.0)),
                    float((stability or {}).get("composite_stddev", 0.0)),
                ),
                run_id,
            )
        )
    scored.sort(reverse=True)
    return scored[0][1]

def _load_score_report(runs_root: Path, run_id: str) -> dict[str, Any]:
    score_path = runs_root / run_id / "score_report.json"
    if not score_path.exists():
        return {}
    return json.loads(score_path.read_text(encoding="utf-8"))

def _load_task_results(run_dir: Path) -> list[dict[str, Any]]:
    tasks_dir = run_dir / "tasks"
    if not tasks_dir.exists():
        return []
    results: list[dict[str, Any]] = []
    for task_dir in sorted(path for path in tasks_dir.iterdir() if path.is_dir()):
        path = task_dir / "task_result.json"
        if path.exists():
            results.append(json.loads(path.read_text(encoding="utf-8")))
    return results

def _load_run_status(runs_root: Path, run_id: str) -> str | None:
    task_results = _load_task_results(runs_root / run_id)
    if not task_results:
        return None
    return "failed" if any(not bool(item.get("success")) for item in task_results) else "completed"

def _load_run_snapshot(
    runs_root: Path,
    run_id: str,
    task_refs: list[HarnessTaskRef],
) -> dict[str, Any]:
    score = _load_score_report(runs_root, run_id)
    return {
        "run_id": run_id,
        "status": _load_run_status(runs_root, run_id),
        "score": score,
        "task_refs": [task_ref.model_dump() for task_ref in task_refs],
        "trace_refs": _collect_run_trace_refs(runs_root, run_id),
        "artifact_refs": _collect_run_artifact_refs(runs_root, run_id),
    }

def _collect_run_trace_refs(runs_root: Path, run_id: str) -> list[str]:
    run_dir = runs_root / run_id
    trace_refs: list[str] = []
    tasks_dir = run_dir / "tasks"
    if not tasks_dir.exists():
        return trace_refs
    for task_dir in sorted(path for path in tasks_dir.iterdir() if path.is_dir()):
        steps_path = task_dir / "steps.jsonl"
        if steps_path.exists():
            trace_refs.append(str(steps_path))
    return trace_refs

def _collect_run_artifact_refs(runs_root: Path, run_id: str) -> list[str]:
    run_dir = runs_root / run_id
    artifact_refs: list[str] = []
    score_path = run_dir / "score_report.json"
    if score_path.exists():
        artifact_refs.append(str(score_path))
    workspace_path = run_dir / "artifacts" / "workspace.json"
    if workspace_path.exists():
        artifact_refs.append(str(workspace_path))
    tasks_dir = run_dir / "tasks"
    if tasks_dir.exists():
        for task_dir in sorted(path for path in tasks_dir.iterdir() if path.is_dir()):
            task_result_path = task_dir / "task_result.json"
            if task_result_path.exists():
                artifact_refs.append(str(task_result_path))
    return artifact_refs

def _collect_failure_modes(
    harness_runs: list[HarnessRun],
    *,
    runs_root: Path,
) -> list[str]:
    modes: list[str] = []
    for harness_run in harness_runs:
        run_id = harness_run.run_id
        task_results = _load_task_results(runs_root / run_id)
        for task_result in task_results:
            failed_phase = task_result.get("failed_phase")
            if isinstance(failed_phase, str) and failed_phase and failed_phase not in modes:
                modes.append(failed_phase)
            failed_assertion = task_result.get("failed_assertion")
            if isinstance(failed_assertion, dict):
                kind = failed_assertion.get("kind")
                if isinstance(kind, str) and kind and kind not in modes:
                    modes.append(kind)
            error = task_result.get("error")
            if isinstance(error, str) and error and error not in modes:
                modes.append(error)
    return modes

def _collect_failure_modes_for_variant(
    runs_root: Path,
    run_ids: list[str],
) -> list[str]:
    modes: list[str] = []
    for run_id in run_ids:
        task_results = _load_task_results(runs_root / run_id)
        for task_result in task_results:
            failed_phase = task_result.get("failed_phase")
            if isinstance(failed_phase, str) and failed_phase and failed_phase not in modes:
                modes.append(failed_phase)
            failed_assertion = task_result.get("failed_assertion")
            if isinstance(failed_assertion, dict):
                kind = failed_assertion.get("kind")
                if isinstance(kind, str) and kind and kind not in modes:
                    modes.append(kind)
            error = task_result.get("error")
            if isinstance(error, str) and error and error not in modes:
                modes.append(error)
    return modes
