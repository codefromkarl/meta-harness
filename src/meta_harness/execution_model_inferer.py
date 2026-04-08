from __future__ import annotations

from meta_harness.integration_schemas import ExecutionModel, ProjectObservation


def infer_execution_model(observation: ProjectObservation) -> ExecutionModel:
    commands = _first_entry_command(observation)
    requirements = set(observation.environment_requirements)
    if any("http_job_api" == str(item.get("kind")) for item in observation.detected_entrypoints):
        return ExecutionModel(
            kind="http_job_api",
            entry_command=commands,
            input_mode="http_request",
            output_mode="json_response_or_artifacts",
            needs_wrapper=True,
            wrapper_reason="job API responses need polling and artifact normalization",
        )
    if any("daemon_session" == str(item.get("kind")) for item in observation.detected_entrypoints):
        return ExecutionModel(
            kind="daemon_session",
            entry_command=commands,
            input_mode="session_command",
            output_mode="stream_or_files",
            needs_wrapper=True,
            wrapper_reason="daemon sessions need lifecycle management and output capture",
        )
    if "browser" in requirements:
        return ExecutionModel(
            kind="browser_automation",
            entry_command=commands,
            input_mode="workflow_file" if observation.workflow_files else "interactive",
            output_mode="artifacts",
            needs_wrapper=not _has_html_output(observation),
            wrapper_reason=None if _has_html_output(observation) else "browser run does not expose page.html artifact directly",
        )
    if observation.workflow_files and observation.output_candidates:
        needs_wrapper = not _has_direct_contract_outputs(observation)
        return ExecutionModel(
            kind="file_artifact_workflow",
            entry_command=commands,
            input_mode="workflow_file",
            output_mode="artifacts",
            needs_wrapper=needs_wrapper,
            wrapper_reason="workflow outputs need normalization into primitive artifacts" if needs_wrapper else None,
        )
    if _has_cli_entrypoint(observation):
        return ExecutionModel(
            kind="json_stdout_cli",
            entry_command=commands,
            input_mode="cli_args",
            output_mode="stdout_or_files",
            needs_wrapper=True,
            wrapper_reason="CLI projects need wrapper normalization before harness activation",
        )
    if observation.output_candidates:
        return ExecutionModel(
            kind="json_stdout_cli",
            entry_command=commands,
            input_mode="cli_args",
            output_mode="stdout_or_files",
            needs_wrapper=not _has_direct_contract_outputs(observation),
            wrapper_reason="CLI output boundary is not yet aligned to primitive contract"
            if not _has_direct_contract_outputs(observation)
            else None,
        )
    return ExecutionModel(
        kind="unknown",
        entry_command=commands,
        input_mode="unknown",
        output_mode="unknown",
        needs_wrapper=True,
        wrapper_reason="could not infer a stable execution boundary from project observation",
    )


def _first_entry_command(observation: ProjectObservation) -> list[str]:
    for entrypoint in observation.detected_entrypoints:
        command = entrypoint.get("command")
        if isinstance(command, list) and command:
            return [str(item) for item in command]
    return []


def infer_capability_modules(observation: ProjectObservation, execution_model: ExecutionModel) -> list[str]:
    modules: list[str] = []
    kinds = {str(item.get("kind") or "") for item in observation.detected_entrypoints}
    if execution_model.kind in {"json_stdout_cli", "daemon_session"}:
        modules.append("command_proxy")
        modules.append("output_filter")
    if execution_model.kind == "file_artifact_workflow":
        modules.append("workflow_orchestrator")
    if execution_model.kind == "browser_automation":
        modules.append("browser_operator")
    if execution_model.kind == "http_job_api":
        modules.append("job_dispatcher")
    if any(item in kinds for item in {"rust_cli", "python_script", "npm_script", "file_entrypoint"}):
        modules.append("tooling_wrapper")
    if observation.output_candidates or "stdout_print" in observation.logging_patterns:
        modules.append("output_filter")
    if any(str(item.get("artifact_name") or "").endswith(".md") for item in observation.output_candidates):
        modules.append("report_normalizer")
    if any(str(item.get("artifact_name") or "").endswith(".db") for item in observation.output_candidates):
        modules.append("artifact_producer")
    return sorted(set(modules))


def _has_html_output(observation: ProjectObservation) -> bool:
    return any(str(item.get("artifact_name") or "").endswith(".html") for item in observation.output_candidates)


def _has_direct_contract_outputs(observation: ProjectObservation) -> bool:
    names = {str(item.get("artifact_name") or "") for item in observation.output_candidates}
    return "page.html" in names and "extracted.json" in names


def _has_cli_entrypoint(observation: ProjectObservation) -> bool:
    cli_kinds = {"rust_cli", "python_script", "npm_script", "file_entrypoint"}
    return any(str(item.get("kind") or "") in cli_kinds for item in observation.detected_entrypoints)
