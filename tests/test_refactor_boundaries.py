from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_production_code_uses_split_runtime_benchmark_and_integration_modules() -> None:
    allowed = {
        "meta_harness.benchmark": {
            "src/meta_harness/benchmark.py",
            "src/meta_harness/cli.py",
        },
        "meta_harness.runtime": {
            "src/meta_harness/runtime.py",
            "src/meta_harness/cli.py",
            "src/meta_harness/runtime_execution.py",
            "src/meta_harness/runtime_workspace.py",
        },
        "meta_harness.services.integration_service": {
            "src/meta_harness/services/integration_service.py",
            "src/meta_harness/cli.py",
            "src/meta_harness/cli_profile_workflow_integration.py",
            "src/meta_harness/api/app.py",
        },
        "meta_harness.api.app": {
            "src/meta_harness/api/routes_core.py",
            "src/meta_harness/api/routes_data_ops.py",
            "src/meta_harness/api/routes_execution_ops.py",
            "src/meta_harness/api/routes_integrations.py",
        },
        "meta_harness.cli": {
            "src/meta_harness/cli_observe_strategy_dataset_gate.py",
            "src/meta_harness/cli_profile_workflow_integration.py",
            "src/meta_harness/cli_run_candidate_optimize.py",
        },
        "meta_harness.optimizer": {
            "src/meta_harness/optimizer.py",
            "src/meta_harness/cli.py",
        },
        "meta_harness.strategy_cards": {
            "src/meta_harness/strategy_cards.py",
            "src/meta_harness/cli.py",
        },
        "meta_harness.services.workflow_service": {
            "src/meta_harness/services/workflow_service.py",
            "src/meta_harness/services/async_jobs.py",
            "src/meta_harness/cli.py",
            "src/meta_harness/cli_profile_workflow_integration.py",
            "src/meta_harness/api/app.py",
        },
        "meta_harness.services.strategy_service": {
            "src/meta_harness/services/strategy_service.py",
            "src/meta_harness/services/async_jobs.py",
            "src/meta_harness/cli.py",
            "src/meta_harness/cli_observe_strategy_dataset_gate.py",
            "src/meta_harness/api/app.py",
        },
    }

    violations: list[str] = []
    for path in sorted((REPO_ROOT / "src").rglob("*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        imported = _imported_modules(path)
        for module_name, allowed_paths in allowed.items():
            if module_name not in imported:
                continue
            if rel not in allowed_paths:
                violations.append(f"{rel} imports {module_name}")

    assert violations == []
