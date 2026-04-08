from __future__ import annotations

from importlib import import_module

import typer

from meta_harness.cli_observe_strategy_dataset_gate import (
    dataset_app,
    gate_app,
    observe_app,
    strategy_app,
)
from meta_harness.cli_profile_workflow_integration import (
    integration_app,
    method_app,
    profile_app,
    workflow_app,
)
from meta_harness.cli_run_candidate_optimize import (
    candidate_app,
    optimize_app,
    run_app,
)


_LAZY_ATTRS: dict[str, tuple[str, str]] = {
    "archive_runs": ("meta_harness.services.catalog_service", "archive_runs_payload"),
    "prune_runs": ("meta_harness.services.catalog_service", "prune_runs_payload"),
    "archive_candidates": ("meta_harness.services.catalog_service", "archive_candidates_payload"),
    "prune_candidates": ("meta_harness.services.catalog_service", "prune_candidates_payload"),
    "compact_runs": ("meta_harness.compaction", "compact_runs"),
    "run_benchmark": ("meta_harness.benchmark", "run_benchmark"),
    "run_benchmark_suite": ("meta_harness.benchmark", "run_benchmark_suite"),
    "execute_managed_run": ("meta_harness.runtime", "execute_managed_run"),
    "execute_task_set": ("meta_harness.runtime", "execute_task_set"),
    "benchmark_harness_payload": (
        "meta_harness.services.integration_service",
        "benchmark_harness_payload",
    ),
    "benchmark_integration_payload": (
        "meta_harness.services.integration_service",
        "benchmark_integration_payload",
    ),
    "harness_outer_loop_payload": (
        "meta_harness.services.integration_service",
        "harness_outer_loop_payload",
    ),
}


def __getattr__(name: str):
    target = _LAZY_ATTRS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


app = typer.Typer(help="Meta-Harness CLI")
app.add_typer(profile_app, name="profile")
app.add_typer(run_app, name="run")
app.add_typer(candidate_app, name="candidate")
app.add_typer(optimize_app, name="optimize")
app.add_typer(observe_app, name="observe")
app.add_typer(strategy_app, name="strategy")
app.add_typer(dataset_app, name="dataset")
app.add_typer(workflow_app, name="workflow")
app.add_typer(method_app, name="method")
app.add_typer(gate_app, name="gate")
app.add_typer(integration_app, name="integration")


if __name__ == "__main__":
    app()
