<div align="center">
  <h1>Meta-Harness</h1>
  <p>A platform for trying, comparing, and improving AI workflows. It records every attempt, compares alternatives automatically, and helps you find better ways to execute tasks faster.</p>
  <p>
    <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&amp;logoColor=white">
    <img alt="Pytest" src="https://img.shields.io/badge/testing-pytest-0A9EDC?logo=pytest&amp;logoColor=white">
    <img alt="CLI" src="https://img.shields.io/badge/CLI-Typer-5B5EA6">
    <img alt="API" src="https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&amp;logoColor=white">
    <img alt="Status" src="https://img.shields.io/badge/status-experimental-F59E0B">
  </p>
  <p><a href="./README.md">中文说明</a></p>
  <p><a href="#quick-start">Quick Start</a> · <a href="./docs/platform-design.md">Platform Design</a> · <a href="./docs/data-model-v1.md">Data Model</a> · <a href="./docs/api-surface-v1.md">API Draft</a></p>
</div>

## Research Background

This project is inspired by the paper [Meta-Harness: End-to-End Optimization of Model Harnesses](https://arxiv.org/abs/2603.28052). The paper argues that the performance of an LLM system depends not only on model weights, but also on the harness: the code that decides what information to store, retrieve, present, and execute around the model. Instead of optimizing only prompts or final outputs, the paper treats harness code itself as the optimization target and uses prior candidates, scores, and execution traces as the outer-loop search surface.

This repository extends that direction into a reusable platform entry point for experiment orchestration, candidate management, benchmarking, traces, and optimization loops.

## What It Is

Meta-Harness is not a one-off script, nor is it a temporary utility for a single project. It is a platform for continuously testing, comparing, and improving AI workflows.

Its core value is to bring different execution paths, variants, and results into a single operational framework, so that experiment records, comparison, and iterative optimization have one consistent entry point instead of being scattered across shell history, ad hoc scripts, and manual bookkeeping.

For AI automation, agent workflows, task execution systems, and other processes that require ongoing tuning, the project provides a more systematic and reusable way to organize that work.

## Highlights

- 🔥 **End-to-end optimization loop**: candidate, run, score, observe, benchmark, propose, and shadow-run are organized as one continuous workflow, allowing execution, evaluation, and iteration to operate as a stable loop.
- 🚀 **Candidate-first optimization model**: config variants and code patches are managed within the same candidate system, then filtered through execution and evaluation results on a consistent comparison basis.
- 🌟 **Multi-layer workflow control**: the platform supports platform defaults, workflow profiles, project overlays, and candidate patches, making it possible to narrow from reusable capabilities to task-specific execution.
- 🧠 **AI-driven proposal flow**: future candidates can be generated from historical results, failure traces, and proposal workflows, allowing optimization to move gradually from manual coordination toward automation.
- 🧩 **Modular capability blocks**: benchmarks, strategy cards, task sets, dataset extraction, and trace export remain independently composable, which improves reuse and scenario-specific extension.
- 📊 **Benchmark-driven iteration**: repeatable benchmarks and suites provide a quantitative basis for comparing quality, stability, and cost across variants.
- 🌐 **Designed for integration and extension**: the CLI is the primary entry point today, while the service layer and API surface preserve a foundation for future automation, evaluation pipelines, and control-plane integration.

## What Problem It Solves

- it keeps each experiment and execution result traceable, reducing reliance on manual memory during optimization
- it unifies execution, comparison, optimization, and archiving in one flow, lowering the overhead of managing scattered scripts and directories
- it allows alternative approaches to be rerun and compared directly, so optimization decisions can be grounded in verifiable results
- it preserves iteration discipline as workflows become more complex, instead of forcing teams to rebuild the process manually each time

## What You Can Do With It

- continuously improve an AI assistant or agent: when the same task can be executed in different ways, the platform helps compare outcomes and move toward a more stable and effective approach
- manage and compare different versions of an AI workflow: whether the change comes from prompts, workflow steps, or code logic, the differences can be validated in one consistent process
- build a reusable experiment record for a team: each attempt, result, and improvement direction can be preserved, reducing reliance on scattered scripts, folders, and memory

The repository already contains runnable profiles, project overlays, task sets, benchmark specs, and strategy cards, which provide a practical foundation for these scenarios.

## Architecture

```mermaid
flowchart LR
    User[User / CI / Automation]
    CLI[Typer CLI]
    API[FastAPI Surface]
    Services[Service Layer]
    Config[Config Loader]
    Runtime[Runtime / Workflow]
    Benchmark[Benchmark / Observe]
    Optimize[Optimize / Shadow Run]
    Artifacts[(runs / candidates / archive / reports)]
    Docs[Design Docs]

    User --> CLI
    User --> API
    CLI --> Services
    API --> Services
    Services --> Config
    Services --> Runtime
    Services --> Benchmark
    Services --> Optimize
    Config --> Artifacts
    Runtime --> Artifacts
    Benchmark --> Artifacts
    Optimize --> Artifacts
    Docs -. guide .-> Services
```

## Quick Start

Requirement: Python 3.11+

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Inspect the CLI:

```bash
mh --help
```

If you do not want to install the script entry point yet, run it directly:

```bash
PYTHONPATH=src python -m meta_harness.cli --help
```

Minimal path to try the platform:

```bash
PYTHONPATH=src python -m meta_harness.cli profile list

PYTHONPATH=src python -m meta_harness.cli --help
```

From there, choose an existing set of assets from `configs/profiles/`, `configs/projects/`, and `task_sets/`, then initialize and execute your first run.

## Documentation Entry Points

If you want the deeper technical view instead of the landing-page summary, read these first:

1. [Platform Design](./docs/platform-design.md)
2. [Data Model v1](./docs/data-model-v1.md)
3. [API Surface v1](./docs/api-surface-v1.md)

Additional references:

- [Artifact Contracts](./docs/artifact-contracts.md)
- [Gate Policy v1](./docs/gate-policy-v1.md)
- [Benchmark Spec v2](./docs/benchmark-spec-v2.md)
- [External Strategy Evaluation](./docs/external-strategy-evaluation.md)
- [ADR Index](./docs/adr/README.md)

## Current Status

- the CLI is the primary execution surface today
- the HTTP API is still in design and productization
- the repository already contains a reusable service layer and an API surface draft
- the repository does not currently include a `LICENSE` file; add one before external distribution or open-source release
