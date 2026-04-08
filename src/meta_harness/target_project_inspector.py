from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

import yaml

from meta_harness.integration_schemas import IntegrationIntent, ProjectObservation

_WORKFLOW_PATTERNS = ("*.yaml", "*.yml", "*.json")
_OUTPUT_HINT = re.compile(r"([A-Za-z0-9_./-]+\.(?:json|html|txt|csv|md|log|db))")
_IGNORED_DIR_NAMES = {
    ".git",
    ".github",
    ".omc",
    "target",
    "node_modules",
    "__pycache__",
    ".venv",
    "dist",
    "build",
}


def inspect_target_project(intent: IntegrationIntent) -> ProjectObservation:
    project_root = Path(intent.target_project_path)
    workflow_paths = _collect_workflow_paths(project_root, intent.workflow_files)
    entrypoints = _detect_entrypoints(project_root, workflow_paths)
    output_candidates = _detect_output_candidates(project_root, workflow_paths)
    input_candidates = _detect_input_candidates(workflow_paths)
    environment_requirements = _detect_environment_requirements(project_root, workflow_paths)
    logging_patterns = _detect_logging_patterns(project_root)
    confidence = _estimate_confidence(
        entrypoints=entrypoints,
        workflow_paths=workflow_paths,
        output_candidates=output_candidates,
    )
    return ProjectObservation(
        detected_entrypoints=entrypoints,
        workflow_files=[str(path) for path in workflow_paths],
        output_candidates=output_candidates,
        input_candidates=input_candidates,
        environment_requirements=environment_requirements,
        logging_patterns=logging_patterns,
        confidence=confidence,
    )


def _collect_workflow_paths(project_root: Path, configured: list[str]) -> list[Path]:
    discovered: list[Path] = []
    seen: set[str] = set()
    for raw in configured:
        path = Path(raw).expanduser().resolve()
        if path.is_file() and str(path) not in seen:
            seen.add(str(path))
            discovered.append(path)
    root_candidates = [
        project_root / "workflow.yaml",
        project_root / "workflow.yml",
        project_root / "workflow.json",
    ]
    for path in root_candidates:
        if path.is_file() and not _should_ignore_path(path, project_root):
            resolved = path.resolve()
            if str(resolved) not in seen:
                seen.add(str(resolved))
                discovered.append(resolved)

    for base in (project_root / "workflows",):
        if not base.exists():
            continue
        for pattern in _WORKFLOW_PATTERNS:
            for path in sorted(base.rglob(pattern)):
                if not path.is_file():
                    continue
                if _should_ignore_path(path, project_root):
                    continue
                if str(path.resolve()) in seen:
                    continue
                seen.add(str(path.resolve()))
                discovered.append(path.resolve())
    return discovered


def _detect_entrypoints(project_root: Path, workflow_paths: list[Path]) -> list[dict[str, Any]]:
    entrypoints: list[dict[str, Any]] = []
    pyproject_path = project_root / "pyproject.toml"
    if pyproject_path.exists():
        payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        scripts = payload.get("project", {}).get("scripts", {})
        if isinstance(scripts, dict):
            for name, target in scripts.items():
                entrypoints.append(
                    {
                        "kind": "python_script",
                        "name": str(name),
                        "target": str(target),
                        "path": str(pyproject_path.resolve()),
                        "command": ["python", "-m", str(target).split(":")[0]],
                        "source": "pyproject.toml",
                    }
                )

    package_json = project_root / "package.json"
    if package_json.exists():
        payload = json.loads(package_json.read_text(encoding="utf-8"))
        scripts = payload.get("scripts")
        if isinstance(scripts, dict):
            for name, command in scripts.items():
                entrypoints.append(
                    {
                        "kind": "npm_script",
                        "name": str(name),
                        "command": str(command).split(),
                        "path": str(package_json.resolve()),
                        "source": "package.json",
                    }
                )

    cargo_toml = project_root / "Cargo.toml"
    if cargo_toml.exists():
        entrypoints.append(
            {
                "kind": "rust_cli",
                "name": project_root.name,
                "path": str(cargo_toml.resolve()),
                "command": ["cargo", "run", "--"],
                "source": "Cargo.toml",
            }
        )

    for workflow_path in workflow_paths:
        document = _load_structured_document(workflow_path)
        for command in _extract_workflow_commands(document):
            entrypoints.append(
                {
                    "kind": "workflow_step",
                    "name": workflow_path.stem,
                    "command": command,
                    "path": str(workflow_path),
                    "source": "workflow",
                }
            )

    for candidate in ("main.py", "app.py", "cli.py", "scripts/run.py"):
        path = project_root / candidate
        if path.exists():
            entrypoints.append(
                {
                    "kind": "file_entrypoint",
                    "name": path.stem,
                    "path": str(path.resolve()),
                    "command": ["python", str(path.relative_to(project_root))],
                    "source": "filesystem",
                }
            )

    for candidate in _sample_text_files(project_root):
        text = candidate.read_text(encoding="utf-8", errors="ignore").lower()
        if ("http://" in text or "https://" in text) and ("/jobs" in text or "requests.post" in text):
            entrypoints.append(
                {
                    "kind": "http_job_api",
                    "name": candidate.stem,
                    "path": str(candidate.resolve()),
                    "source": "code_scan",
                }
            )
        if "serve_forever" in text or ("while true" in text and "socket" in text):
            entrypoints.append(
                {
                    "kind": "daemon_session",
                    "name": candidate.stem,
                    "path": str(candidate.resolve()),
                    "source": "code_scan",
                }
            )

    return _dedupe_dict_items(entrypoints, key=lambda item: json.dumps(item, sort_keys=True))


def _detect_output_candidates(project_root: Path, workflow_paths: list[Path]) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for workflow_path in workflow_paths:
        document = _load_structured_document(workflow_path)
        for item in _extract_workflow_outputs(document):
            outputs.append(
                {
                    "path": str((project_root / item).resolve()) if not Path(item).is_absolute() else str(Path(item)),
                    "source": "workflow",
                    "kind": "declared_output",
                    "artifact_name": Path(item).name,
                }
            )

    for candidate in _sample_text_files(project_root):
        text = candidate.read_text(encoding="utf-8", errors="ignore")
        for match in _OUTPUT_HINT.findall(text):
            if "/" not in match and "." not in match:
                continue
            normalized = project_root / match
            outputs.append(
                {
                    "path": str(normalized.resolve()),
                    "source": str(candidate.resolve()),
                    "kind": "referenced_output",
                    "artifact_name": normalized.name,
                }
            )

    for directory_name in ("outputs", "output", "artifacts", "reports", "results"):
        directory = project_root / directory_name
        if directory.exists():
            for path in sorted(directory.rglob("*")):
                if path.is_file():
                    outputs.append(
                        {
                            "path": str(path.resolve()),
                            "source": "filesystem",
                            "kind": "existing_output",
                            "artifact_name": path.name,
                        }
                    )
    return _dedupe_dict_items(outputs, key=lambda item: item["path"])


def _detect_input_candidates(workflow_paths: list[Path]) -> list[dict[str, Any]]:
    inputs: list[dict[str, Any]] = []
    for workflow_path in workflow_paths:
        document = _load_structured_document(workflow_path)
        for item in _extract_workflow_inputs(document):
            inputs.append(
                {
                    "path": item,
                    "source": str(workflow_path),
                    "kind": "workflow_input",
                }
            )
    return _dedupe_dict_items(inputs, key=lambda item: json.dumps(item, sort_keys=True))


def _detect_environment_requirements(project_root: Path, workflow_paths: list[Path]) -> list[str]:
    requirements: list[str] = []
    if (project_root / "Cargo.toml").exists():
        requirements.append("rust")
    if (project_root / "pyproject.toml").exists() or (project_root / "requirements.txt").exists():
        requirements.append("python")
    if (project_root / "package.json").exists():
        requirements.append("node")
    if any("playwright" in str(path).lower() for path in workflow_paths):
        requirements.append("browser")
    for candidate in _sample_text_files(project_root):
        text = candidate.read_text(encoding="utf-8", errors="ignore")
        lower = text.lower()
        if candidate.name.lower().startswith("readme"):
            continue
        if "playwright" in lower or "selenium" in lower:
            requirements.append("browser")
        if "api_key" in lower or "token" in lower:
            requirements.append("secrets")
        if "localhost:" in lower or "127.0.0.1:" in lower:
            requirements.append("service_port")
    return sorted(set(requirements))


def _detect_logging_patterns(project_root: Path) -> list[str]:
    patterns: list[str] = []
    for candidate in _sample_text_files(project_root):
        text = candidate.read_text(encoding="utf-8", errors="ignore")
        if "print(" in text:
            patterns.append("stdout_print")
        if "logging." in text:
            patterns.append("python_logging")
        if "console.log(" in text:
            patterns.append("console_log")
        if "logger." in text:
            patterns.append("structured_logger")
    return sorted(set(patterns))


def _estimate_confidence(
    *,
    entrypoints: list[dict[str, Any]],
    workflow_paths: list[Path],
    output_candidates: list[dict[str, Any]],
) -> float:
    score = 0.2
    if entrypoints:
        score += 0.3
    if workflow_paths:
        score += 0.3
    if output_candidates:
        score += 0.2
    return min(1.0, round(score, 2))


def _load_structured_document(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}
    payload = yaml.safe_load(raw)
    return payload if isinstance(payload, dict) else {}


def _extract_workflow_commands(payload: dict[str, Any]) -> list[list[str]]:
    commands: list[list[str]] = []
    steps = payload.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            run = step.get("run")
            command = step.get("command")
            if isinstance(run, str) and run.strip():
                commands.append(run.strip().split())
            elif isinstance(command, list):
                commands.append([str(item) for item in command])
    return commands


def _extract_workflow_outputs(payload: dict[str, Any]) -> list[str]:
    outputs: list[str] = []
    raw_outputs = payload.get("outputs")
    if isinstance(raw_outputs, dict):
        for value in raw_outputs.values():
            if isinstance(value, str):
                outputs.append(value)
    elif isinstance(raw_outputs, list):
        for value in raw_outputs:
            if isinstance(value, str):
                outputs.append(value)
    return outputs


def _extract_workflow_inputs(payload: dict[str, Any]) -> list[str]:
    inputs: list[str] = []
    raw_inputs = payload.get("inputs")
    if isinstance(raw_inputs, dict):
        for value in raw_inputs.values():
            if isinstance(value, str):
                inputs.append(value)
    elif isinstance(raw_inputs, list):
        for value in raw_inputs:
            if isinstance(value, str):
                inputs.append(value)
    return inputs


def _sample_text_files(project_root: Path) -> list[Path]:
    candidates: list[Path] = []
    for pattern in ("*.py", "*.js", "*.ts", "*.yaml", "*.yml", "*.json", "README*"):
        candidates.extend(sorted(project_root.rglob(pattern)))
    files: list[Path] = []
    for path in candidates:
        if not path.is_file():
            continue
        if _should_ignore_path(path, project_root):
            continue
        files.append(path)
        if len(files) >= 24:
            break
    return files


def _should_ignore_path(path: Path, project_root: Path) -> bool:
    try:
        relative_parts = path.relative_to(project_root).parts
    except ValueError:
        relative_parts = path.parts
    for part in relative_parts[:-1]:
        if part in _IGNORED_DIR_NAMES or part.startswith("."):
            return True
    return False


def _dedupe_dict_items(items: list[dict[str, Any]], key: Any) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        marker = key(item)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(item)
    return deduped
