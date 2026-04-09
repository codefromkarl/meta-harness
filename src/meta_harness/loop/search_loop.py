from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

from meta_harness.archive import load_run_record
from meta_harness.candidates import (
    backfill_candidate_lineage,
    create_candidate,
    load_candidate_record,
)
from meta_harness.config_loader import load_effective_config
from meta_harness.loop.experience import assemble_experience_context
from meta_harness.loop.iteration_store import (
    append_iteration_history,
    candidate_lineage_artifact_paths,
    iteration_path,
    loop_root_path,
    write_iteration_artifact,
    write_loop_summary,
)
from meta_harness.loop.proposer_context import prepare_proposer_context
from meta_harness.loop.schemas import (
    LoopIterationArtifact,
    LoopSummary,
    ProposerProtocol,
    SearchLoopRequest,
    SelectionResult,
    StopDecision,
    TaskPluginProtocol,
)
from meta_harness.loop.selection import select_best_result
from meta_harness.loop.selection import score_from_evaluation_result
from meta_harness.loop.stopping import decide_stop
from meta_harness.proposals import create_proposal_record, materialize_candidate_from_proposal
from meta_harness.proposers import rank_proposals
from meta_harness.scoring import score_run
from meta_harness.optimizer_shadow import shadow_run_candidate
from meta_harness.benchmark_engine import run_benchmark
from meta_harness.services.gate_policy_service import (
    resolve_shadow_validation_policy,
    should_trigger_shadow_validation,
)


def run_search_loop(
    request: SearchLoopRequest,
    *,
    task_plugin: TaskPluginProtocol,
    proposer: ProposerProtocol | None = None,
    benchmark_fn: Any = run_benchmark,
    shadow_run_fn: Any = shadow_run_candidate,
    reports_root: Path | None = None,
    proposals_root: Path | None = None,
) -> LoopSummary:
    experience_query = request.experience_query
    effective_config = load_effective_config(
        config_root=request.config_root,
        profile_name=request.profile_name,
        project_name=request.project_name,
    )
    objective = _build_objective(
        request=request,
        task_plugin=task_plugin,
        effective_config=effective_config,
    )
    proposer = proposer or _default_proposer()
    loop_id = request.loop_id or f"{request.profile_name}-{request.project_name}-{uuid4().hex[:8]}"
    loop_dir = loop_root_path(reports_root or (request.reports_root or request.runs_root.parent / "reports"), loop_id)
    loop_dir.mkdir(parents=True, exist_ok=True)

    current_best: SelectionResult | None = None
    iterations: list[LoopIterationArtifact] = []
    no_improvement_count = 0
    stop_reason = "max iterations reached"
    best_score = 0.0
    best_candidate_id: str | None = None
    best_run_id: str | None = None
    score_history: list[float] = []

    for iteration_index in range(1, request.max_iterations + 1):
        iteration_id = f"{loop_id}-{iteration_index:04d}"
        iteration_dir = iteration_path(loop_dir, iteration_id)
        iteration_dir.mkdir(parents=True, exist_ok=True)
        plugin_experience_query = _call_optional(
            task_plugin,
            "build_experience_query",
            objective=objective,
            effective_config=effective_config,
        )
        resolved_experience_query = _resolve_experience_query(
            request_query=experience_query.model_dump() if experience_query is not None else {},
            plugin_query=plugin_experience_query,
        )
        experience = assemble_experience_context(
            runs_root=request.runs_root,
            candidates_root=request.candidates_root,
            profile_name=request.profile_name,
            project_name=request.project_name,
            objective=objective,
            max_history=int(resolved_experience_query.get("max_history", 25) or 25),
            history_sources=resolved_experience_query.get("history_sources"),
            best_k=resolved_experience_query.get("best_k"),
            focus=resolved_experience_query.get("focus"),
            dedupe_failure_families=bool(
                resolved_experience_query.get("dedupe_failure_families", False)
            ),
        )
        plugin_experience = _call_optional(
            task_plugin,
            "assemble_experience",
            runs_root=request.runs_root,
            candidates_root=request.candidates_root,
            selected_runs=experience.get("matching_runs", []),
            objective=objective,
        )
        if isinstance(plugin_experience, dict):
            experience = {**experience, **plugin_experience}

        evaluation_plan = _call_optional(
            task_plugin,
            "build_evaluation_plan",
            objective=objective,
            effective_config=effective_config,
        )
        if not isinstance(evaluation_plan, dict):
            evaluation_plan = {}
        plugin_stopping_policy = _call_optional(
            task_plugin,
            "build_stopping_policy",
            objective=objective,
            effective_config=effective_config,
            evaluation_plan=evaluation_plan,
        )
        if isinstance(plugin_stopping_policy, dict):
            evaluation_plan = {**evaluation_plan, **plugin_stopping_policy}

        plugin_constraints = _call_optional(
            task_plugin,
            "build_proposal_constraints",
            objective=objective,
            effective_config=effective_config,
            experience=experience,
            evaluation_plan=evaluation_plan,
        )
        proposal_constraints = {
            "profile_name": request.profile_name,
            "project_name": request.project_name,
            "effective_config": effective_config,
            "proposal_command": effective_config.get("optimization", {}).get("proposal_command"),
            "evaluation_plan": evaluation_plan,
            "request": request.model_dump(),
            "plugin_constraints": plugin_constraints if isinstance(plugin_constraints, dict) else {},
            "proposal_constraints": {
                "focus": objective.get("focus"),
                "allowed_scopes": (
                    list((plugin_constraints or {}).get("allowed_scopes") or [])
                    if isinstance(plugin_constraints, dict)
                    else []
                ),
                "blocked_scopes": (
                    list((plugin_constraints or {}).get("blocked_scopes") or [])
                    if isinstance(plugin_constraints, dict)
                    else []
                ),
                "failure_family_priority": [
                    item.get("family")
                    for item in experience.get("representative_failures", [])
                    if isinstance(item, dict) and item.get("family")
                ],
                "budget_boundaries": (effective_config.get("budget") if isinstance(effective_config.get("budget"), dict) else {}),
            },
        }
        proposer_context = prepare_proposer_context(
            iteration_dir=iteration_dir,
            objective=objective,
            experience=experience,
            runs_root=request.runs_root,
            candidates_root=request.candidates_root,
            proposals_root=proposals_root,
        )
        proposal_constraints["proposer_context"] = proposer_context
        ranked_proposals = _ranked_proposals(
            proposers=_normalize_proposers(proposer),
            objective=objective,
            experience=experience,
            constraints=proposal_constraints,
        )
        proposal_payload = ranked_proposals[0] if ranked_proposals else {}

        proposal_raw = proposal_payload.get("proposal")
        proposal_result = proposal_raw if isinstance(proposal_raw, dict) else {}
        config_patch = proposal_payload.get("config_patch")
        code_patch = proposal_payload.get("code_patch")
        notes = str(proposal_payload.get("notes", ""))
        raw_source_run_ids = proposal_payload.get("source_run_ids", [])
        source_run_ids = [
            str(item)
            for item in raw_source_run_ids
            if isinstance(raw_source_run_ids, list) and str(item)
        ] if isinstance(raw_source_run_ids, list) else []
        proposal_evaluation = {
            "selected_proposal": {
                key: value
                for key, value in proposal_payload.items()
                if key not in {"config_patch", "code_patch"}
            },
            "rejected_proposals": [
                {
                    key: value
                    for key, value in item.items()
                    if key not in {"config_patch", "code_patch"}
                }
                for item in ranked_proposals[1:]
            ],
        }

        proposal_id = None
        proposal_path = None
        candidate_id: str
        if proposals_root is not None:
            created_proposals: list[dict[str, Any]] = []
            for index, ranked_payload in enumerate(ranked_proposals, start=1):
                ranked_source_run_ids = [
                    str(item)
                    for item in ranked_payload.get("source_run_ids", [])
                    if str(item)
                ]
                created_id = create_proposal_record(
                    proposals_root=proposals_root,
                    profile_name=request.profile_name,
                    project_name=request.project_name,
                    proposer_kind=str(ranked_payload.get("proposer_kind", getattr(proposer, "proposer_id", "unknown"))),
                    proposal=(
                        ranked_payload.get("proposal")
                        if isinstance(ranked_payload.get("proposal"), dict)
                        else {}
                    ),
                    config_patch=(
                        ranked_payload.get("config_patch")
                        if isinstance(ranked_payload.get("config_patch"), dict)
                        else None
                    ),
                    code_patch_content=(
                        ranked_payload.get("code_patch")
                        if isinstance(ranked_payload.get("code_patch"), str)
                        else None
                    ),
                    notes=str(ranked_payload.get("notes", "")),
                    source_run_ids=ranked_source_run_ids,
                    proposal_evaluation={
                        "selected": index == 1,
                        "selection_reason": "ranked_first" if index == 1 else "ranked_below_selected",
                        "proposal_rank": int(ranked_payload.get("proposal_rank", index)),
                        "proposal_score": float(ranked_payload.get("proposal_score", 0.0)),
                        "stability_score": float(ranked_payload.get("stability_score", 0.0)),
                        "cost_score": float(ranked_payload.get("cost_score", 0.0)),
                        "ranking_basis": ranked_payload.get("ranking_basis") or {},
                        "rejected_proposals": [],
                    },
                )
                created_proposals.append({"proposal_id": created_id, **ranked_payload})
            proposal_id = created_proposals[0]["proposal_id"]
            proposal_path = str(proposals_root / proposal_id)
            materialized = materialize_candidate_from_proposal(
                proposals_root=proposals_root,
                proposal_id=proposal_id,
                candidates_root=request.candidates_root,
                config_root=request.config_root,
                iteration_id=iteration_id,
                source_artifacts=[proposal_path, proposer_context["bundle_dir"]],
            )
            candidate_id = materialized["candidate_id"]
        else:
            candidate_id = create_candidate(
                candidates_root=request.candidates_root,
                config_root=request.config_root,
                profile_name=request.profile_name,
                project_name=request.project_name,
                config_patch=config_patch if isinstance(config_patch, dict) else None,
                code_patch_content=code_patch if isinstance(code_patch, str) else None,
                notes=notes,
                proposal_id=proposal_id,
                iteration_id=iteration_id,
                source_artifacts=[proposer_context["bundle_dir"]],
                proposal=proposal_result,
                reuse_existing=True,
            )

        candidate_record = load_candidate_record(request.candidates_root, candidate_id)
        candidate_path = candidate_record["candidate_dir"]
        evaluation_payload = _evaluate_candidate(
            request=request,
            evaluation_plan=evaluation_plan,
            benchmark_fn=benchmark_fn,
            shadow_run_fn=shadow_run_fn,
            candidate_id=candidate_id,
            candidate_record=candidate_record,
            effective_config=effective_config,
        )
        current_evaluation_score = score_from_evaluation_result(evaluation_payload)
        score_history.append(current_evaluation_score)

        selection = select_best_result(
            candidate_id=candidate_id,
            evaluation_result=evaluation_payload,
            previous_best=current_best,
            selection_policy=(
                str(evaluation_plan.get("selection_policy"))
                if evaluation_plan.get("selection_policy") is not None
                else None
            ),
        )
        if selection is current_best:
            no_improvement_count += 1
        else:
            no_improvement_count = 0
            current_best = selection
        best_candidate_id = selection.candidate_id
        best_run_id = selection.run_id or best_run_id
        best_score = max(best_score, selection.score)

        stop_decision = decide_stop(
            iteration_index=iteration_index,
            max_iterations=request.max_iterations,
            best_score=best_score,
            target_score=request.stop_target_score,
            no_improvement_count=no_improvement_count,
            no_improvement_limit=int(
                evaluation_plan.get("no_improvement_limit", request.no_improvement_limit)
            ),
            current_score=current_evaluation_score,
            score_history=score_history,
            recent_scores=score_history[-int(evaluation_plan.get("stability_window", 3)) :],
            stability_window=int(evaluation_plan.get("stability_window", 3)),
            instability_threshold=(
                float(evaluation_plan["instability_threshold"])
                if evaluation_plan.get("instability_threshold") is not None
                else None
            ),
            regression_tolerance=(
                float(evaluation_plan["regression_tolerance"])
                if evaluation_plan.get("regression_tolerance") is not None
                else None
            ),
        )
        stop_reason = stop_decision.reason

        summary = _call_optional(
            task_plugin,
            "summarize_iteration",
            benchmark_payload=evaluation_payload,
            selected_variant=selection.raw_result if isinstance(selection.raw_result, dict) else {},
        )
        if not isinstance(summary, dict):
            summary = {
                "score": selection.score,
                "candidate_id": candidate_id,
                "run_id": selection.run_id,
            }

        artifact = LoopIterationArtifact(
            iteration_id=iteration_id,
            iteration_index=iteration_index,
            objective=objective,
            experience=experience,
            proposal={
                **proposal_result,
                "proposer_kind": proposal_payload.get("proposer_kind", "unknown"),
            },
            candidate_id=candidate_id,
            candidate_path=candidate_path,
            proposal_id=proposal_id,
            proposal_path=proposal_path,
            run_id=selection.run_id,
            run_path=str(request.runs_root / selection.run_id) if selection.run_id else None,
            selection=selection,
            stop_decision=stop_decision,
            evaluation=evaluation_payload,
            summary=summary,
            artifacts={"proposer_context": proposer_context["bundle_dir"]},
            proposal_evaluation=proposal_evaluation,
        )
        paths = write_iteration_artifact(loop_dir, artifact)
        artifact.artifacts = {
            **artifact.artifacts,
            **{name: str(path) for name, path in paths.items()},
        }
        backfill_candidate_lineage(
            candidates_root=request.candidates_root,
            candidate_id=candidate_id,
            proposal_id=proposal_id,
            iteration_id=iteration_id,
            source_run_ids=[selection.run_id] if selection.run_id else [],
            source_artifacts=candidate_lineage_artifact_paths(paths),
        )
        paths["iteration_json"].write_text(
            json.dumps(artifact.model_dump(), indent=2),
            encoding="utf-8",
        )
        paths["next_round_context_json"].write_text(
            json.dumps(
                {
                    "stop_decision": artifact.stop_decision.model_dump()
                    if artifact.stop_decision
                    else None,
                    "artifacts": artifact.artifacts,
                    "experience_summary_path": str(paths["experience_summary_json"]),
                    "validation_summary_path": str(paths["validation_summary_json"]),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        append_iteration_history(loop_dir, artifact)
        iterations.append(artifact)

        if stop_decision.should_stop:
            break

    summary = LoopSummary(
        loop_id=loop_id,
        profile_name=request.profile_name,
        project_name=request.project_name,
        request=request,
        best_candidate_id=best_candidate_id,
        best_run_id=best_run_id,
        best_score=best_score,
        iteration_count=len(iterations),
        stop_reason=stop_reason,
        iterations=iterations,
        objective=objective,
        experience=iterations[-1].experience if iterations else {},
        loop_dir=str(loop_dir),
    )
    write_loop_summary(loop_dir, summary)
    return summary


def _build_objective(
    *,
    request: SearchLoopRequest,
    task_plugin: TaskPluginProtocol,
    effective_config: dict[str, Any],
) -> dict[str, Any]:
    objective = _call_optional(
        task_plugin,
        "assemble_objective",
        profile_name=request.profile_name,
        project_name=request.project_name,
        task_set_path=request.task_set_path,
        effective_config=effective_config,
    )
    if not isinstance(objective, dict):
        objective = {}
    objective.setdefault("profile_name", request.profile_name)
    objective.setdefault("project_name", request.project_name)
    objective.setdefault("task_set_path", str(request.task_set_path))
    objective.setdefault("focus", request.focus)
    objective.setdefault("evaluation_mode", request.evaluation_mode)
    return objective


def _evaluate_candidate(
    *,
    request: SearchLoopRequest,
    evaluation_plan: dict[str, Any],
    benchmark_fn: Any,
    shadow_run_fn: Any,
    candidate_id: str,
    candidate_record: dict[str, Any],
    effective_config: dict[str, Any],
    validation_fn: Any = None,
) -> dict[str, Any]:
    return execute_evaluation_plan(
        request=request,
        evaluation_plan=evaluation_plan,
        benchmark_fn=benchmark_fn,
        shadow_run_fn=shadow_run_fn,
        candidate_id=candidate_id,
        effective_config=effective_config,
        validation_fn=validation_fn,
    )


def execute_evaluation_plan(
    *,
    request: SearchLoopRequest,
    evaluation_plan: dict[str, Any],
    benchmark_fn: Any,
    shadow_run_fn: Any,
    candidate_id: str,
    effective_config: dict[str, Any],
    validation_fn: Any = None,
) -> dict[str, Any]:
    evaluation_mode = str(evaluation_plan.get("kind") or request.evaluation_mode)
    if evaluation_mode == "benchmark":
        spec_path = evaluation_plan.get("benchmark_spec_path")
        if not spec_path:
            return {
                "mode": "benchmark",
                "candidate_id": candidate_id,
                "executor": {"kind": "benchmark", "status": "invalid"},
                "error": "benchmark_spec_path missing from evaluation plan",
            }
        validation_payload = _maybe_run_lightweight_validation(
            request=request,
            evaluation_plan=evaluation_plan,
            candidate_id=candidate_id,
            effective_config=effective_config,
            validation_fn=validation_fn,
        )
        if validation_payload is not None:
            validation_status = str(validation_payload.get("status", "")).strip().lower()
            if validation_status and validation_status not in {"passed", "pass", "ok", "completed"}:
                return {
                    "mode": "benchmark",
                    "candidate_id": candidate_id,
                    "executor": {
                        "kind": "benchmark",
                        "status": "validation_failed",
                        "spec_path": str(spec_path),
                    },
                    "validation": validation_payload,
                    "benchmark_skipped": True,
                    "error": str(
                        validation_payload.get("reason")
                        or "lightweight validation failed"
                    ),
                }
        benchmark_payload = benchmark_fn(
            config_root=request.config_root,
            runs_root=request.runs_root,
            candidates_root=request.candidates_root,
            profile_name=request.profile_name,
            project_name=request.project_name,
            task_set_path=request.task_set_path,
            spec_path=Path(str(spec_path)),
            focus=request.focus,
            effective_config_override=effective_config,
        )
        return {
            "mode": "benchmark",
            "candidate_id": candidate_id,
            "executor": {
                "kind": "benchmark",
                "status": "completed",
                "spec_path": str(spec_path),
            },
            "score": benchmark_payload.get("variants", [{}])[0].get("score", {}),
            "validation": validation_payload,
            "benchmark": benchmark_payload,
            **benchmark_payload,
        }

    shadow_validation_policy = resolve_shadow_validation_policy(
        effective_config=effective_config,
        evaluation_plan=evaluation_plan,
        trigger="loop_shadow_run",
    )
    validation_payload = _maybe_run_shadow_validation(
        request=request,
        evaluation_plan=evaluation_plan,
        candidate_id=candidate_id,
        effective_config=effective_config,
        validation_fn=validation_fn,
        shadow_validation_policy=shadow_validation_policy,
    )
    if validation_payload is not None:
        validation_status = str(validation_payload.get("status", "")).strip().lower()
        if (
            validation_status
            and validation_status not in {"passed", "pass", "ok", "completed"}
            and shadow_validation_policy.get("failure_behavior") == "fail_evaluation"
        ):
            return {
                "mode": "shadow-run",
                "candidate_id": candidate_id,
                "executor": {
                    "kind": "shadow-run",
                    "status": "validation_failed",
                },
                "validation": validation_payload,
                "shadow_validation_policy": shadow_validation_policy,
                "shadow_run_skipped": True,
                "error": str(
                    validation_payload.get("reason")
                    or "shadow validation failed"
                ),
            }

    run_id = shadow_run_fn(
        candidates_root=request.candidates_root,
        runs_root=request.runs_root,
        candidate_id=candidate_id,
        task_set_path=request.task_set_path,
    )
    run_record = load_run_record(request.runs_root, run_id)
    score = run_record.get("score") or {}
    if not score:
        score = score_run(request.runs_root / run_id)
    return {
        "mode": "shadow-run",
        "candidate_id": candidate_id,
        "executor": {
            "kind": "shadow-run",
            "status": "completed",
            "run_id": run_id,
        },
        "validation": validation_payload,
        "shadow_validation_policy": shadow_validation_policy,
        "run_id": run_id,
        "score": score,
        "run_record": run_record,
    }


def _maybe_run_lightweight_validation(
    *,
    request: SearchLoopRequest,
    evaluation_plan: dict[str, Any],
    candidate_id: str,
    effective_config: dict[str, Any],
    validation_fn: Any = None,
) -> dict[str, Any] | None:
    validation_command = evaluation_plan.get("validation_command")
    if validation_fn is None and not isinstance(validation_command, list):
        return None
    runner = validation_fn or _run_validation_command
    return runner(
        request=request,
        evaluation_plan=evaluation_plan,
        candidate_id=candidate_id,
        effective_config=effective_config,
    )


def _maybe_run_shadow_validation(
    *,
    request: SearchLoopRequest,
    evaluation_plan: dict[str, Any],
    candidate_id: str,
    effective_config: dict[str, Any],
    shadow_validation_policy: dict[str, Any],
    validation_fn: Any = None,
) -> dict[str, Any] | None:
    if not should_trigger_shadow_validation(
        shadow_validation_policy,
        trigger="loop_shadow_run",
    ):
        return None
    shadow_validation_plan = dict(evaluation_plan)
    validation_command = shadow_validation_policy.get("validation_command")
    if isinstance(validation_command, list):
        shadow_validation_plan["validation_command"] = [
            str(item) for item in validation_command
        ]
    validation_workdir = shadow_validation_policy.get("validation_workdir")
    if validation_workdir is not None:
        shadow_validation_plan["validation_workdir"] = str(validation_workdir)
    return _maybe_run_lightweight_validation(
        request=request,
        evaluation_plan=shadow_validation_plan,
        candidate_id=candidate_id,
        effective_config=effective_config,
        validation_fn=validation_fn,
    )


def _run_validation_command(
    *,
    request: SearchLoopRequest,
    evaluation_plan: dict[str, Any],
    candidate_id: str,
    effective_config: dict[str, Any],
) -> dict[str, Any]:
    command = evaluation_plan.get("validation_command")
    if not isinstance(command, list) or not command:
        return {
            "status": "skipped",
            "reason": "validation_command missing",
            "validation_artifact": {
                "kind": "lightweight",
                "status": "skipped",
            },
        }
    runtime = effective_config.get("runtime") if isinstance(effective_config, dict) else {}
    workspace = runtime.get("workspace") if isinstance(runtime, dict) else {}
    workdir = evaluation_plan.get("validation_workdir")
    if workdir is None and isinstance(workspace, dict):
        workdir = workspace.get("source_repo")
    workspace_root = (
        Path(str(workspace.get("source_repo"))).expanduser()
        if isinstance(workspace, dict) and workspace.get("source_repo") is not None
        else None
    )
    resolved_workdir = Path(str(workdir or ".")).expanduser()
    if not resolved_workdir.is_absolute() and workspace_root is not None:
        resolved_workdir = workspace_root / resolved_workdir
    try:
        completed = subprocess.run(
            [str(item) for item in command],
            cwd=resolved_workdir,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return {
            "status": "failed",
            "reason": str(exc),
            "candidate_id": candidate_id,
            "validation_artifact": {
                "kind": "lightweight",
                "status": "failed",
                "command": [str(item) for item in command],
                "workdir": str(resolved_workdir),
                "error": str(exc),
                "task_set_path": str(request.task_set_path),
            },
        }
    status = "passed" if completed.returncode == 0 else "failed"
    reason = (
        ""
        if completed.returncode == 0
        else completed.stderr.strip()
        or completed.stdout.strip()
        or f"exit {completed.returncode}"
    )
    return {
        "status": status,
        "reason": reason,
        "candidate_id": candidate_id,
        "validation_artifact": {
            "kind": "lightweight",
            "status": status,
            "command": [str(item) for item in command],
            "workdir": str(resolved_workdir),
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "task_set_path": str(request.task_set_path),
        },
    }


def _call_optional(target: Any, method_name: str, **kwargs: Any) -> Any:
    method = getattr(target, method_name, None)
    if method is None:
        return None
    return method(**kwargs)


def _default_proposer() -> ProposerProtocol:
    from meta_harness.proposers.heuristic_proposer import HeuristicProposer

    return HeuristicProposer()


def _normalize_proposers(proposer: Any) -> list[Any]:
    if isinstance(proposer, list):
        return proposer
    if isinstance(proposer, tuple):
        return list(proposer)
    return [proposer]


def _ranked_proposals(
    *,
    proposers: list[Any],
    objective: dict[str, Any],
    experience: dict[str, Any],
    constraints: dict[str, Any],
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for proposer in proposers:
        payload = proposer.propose(
            objective=objective,
            experience=experience,
            constraints=constraints,
        )
        normalized = dict(payload if isinstance(payload, dict) else {})
        normalized.setdefault("proposer_kind", getattr(proposer, "proposer_id", "unknown"))
        payloads.append(normalized)
    return rank_proposals(payloads)


def _resolve_experience_query(
    *,
    request_query: dict[str, Any],
    plugin_query: Any,
) -> dict[str, Any]:
    resolved = dict(request_query)
    if isinstance(plugin_query, dict):
        for key, value in plugin_query.items():
            if value is None:
                continue
            resolved[key] = value
    return resolved
