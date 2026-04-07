# Meta-Harness

Meta-Harness 是一个面向 Agent / Harness 工作流的可复用实验平台。它用文件系统作为事实源，把配置、候选方案、运行结果、轨迹、评分和归档统一落盘，用一套 CLI 和 service 层把“观测、比较、优化、归档”串成可重复执行的闭环。

当前仓库已经不只是最初的 skeleton。除了基础的 run/candidate 生命周期管理，还包含 benchmark/suite、strategy card、catalog/archive/prune/compact、failure dataset 导出、trace export，以及面向后续 API 的 service 拆层。

## 当前项目在做什么

- 用 `platform.json + profile + project overlay + candidate patch` 生成可执行配置。
- 用 `run` 管理一次工作流执行的初始化、执行、评分、查询、失败检索和轨迹导出。
- 用 `candidate` 管理实验候选、patch 候选和 champion 提升。
- 用 `observe` 执行单次观测、benchmark 和 benchmark suite，对不同变体做 A/B 对比。
- 用 `optimize` 从历史失败或外部 proposal command 生成候选，并做 shadow run 验证。
- 用 `strategy` 把外部策略卡转换成 benchmark spec 或 candidate。
- 用 `catalog`/`archive`/`prune`/`compact` 管理运行资产体积和历史视图。
- 用 `services/` 为 CLI 和后续 HTTP/API 集成提供共享业务层。

## 核心概念

- `Platform config`: 全局默认值，位于 `configs/platform.json`。
- `Profile`: 工作流默认配置，位于 `configs/profiles/*.json`。
- `Project overlay`: 项目级覆写，位于 `configs/projects/*.json`。
- `Candidate`: 一组可执行变更，可能只含 `config_patch`，也可能带 `code_patch`。
- `Run`: 某个 profile/project 或 candidate 在任务集上的一次执行。
- `Task set`: 任务集合定义，位于 `task_sets/**/*.json`。
- `Benchmark spec`: 变体对比定义，位于 `configs/benchmarks/*.json`。
- `Strategy card`: 外部策略的结构化描述，位于 `configs/strategy_cards/**/*.json`。

配置优先级与当前实现一致：

`platform defaults < workflow profile < project overlay < candidate patch < runtime flags`

## 目录概览

```text
meta-harness/
  configs/
    platform.json
    profiles/
    projects/
    benchmarks/
    strategy_cards/
    strategy_pools/
    patches/
  docs/
  scripts/
  src/meta_harness/
    cli.py
    runtime.py
    benchmark.py
    optimizer.py
    catalog.py
    compaction.py
    strategy_cards.py
    services/
  task_sets/
  tests/
  runs/
  candidates/
  archive/
```

几个关键目录的职责：

- `src/meta_harness/cli.py`: Typer CLI 入口，安装后暴露为 `mh`。
- `src/meta_harness/services/`: 共享 service 层，CLI 和未来 API 共用。
- `runs/`: run 产物目录，包含 `run_metadata.json`、`effective_config.json`、`tasks/`、`score_report.json`、`evaluators/`、`artifacts/` 等。
- `candidates/`: candidate 元数据、effective config、proposal、patch 等。
- `archive/`: 归档后的 run/candidate 以及 cleanup logs。

## 安装

要求：

- Python 3.11+

开发安装：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

安装后可直接使用：

```bash
mh --help
```

如果不想安装脚本，也可以在仓库根目录执行：

```bash
PYTHONPATH=src python -m meta_harness.cli --help
```

## 快速开始

1. 查看可用 profile。

```bash
mh profile list
```

2. 准备配置。

- 平台默认值：`configs/platform.json`
- workflow profile：`configs/profiles/*.json`
- project overlay：`configs/projects/*.json`
- task set：`task_sets/**/*.json`

3. 初始化一次 run。

```bash
mh run init --profile contextatlas_maintenance --project contextatlas
```

4. 直接执行单次观测。

```bash
mh observe once \
  --profile contextatlas_maintenance \
  --project contextatlas \
  --task-set task_sets/contextatlas/import_profile_and_audit.json
```

5. 查看最近状态。

```bash
mh run current
mh run index
mh candidate current
```

## 常用命令

### Run

```bash
mh run init --profile base --project demo
mh run execute --run-id <run_id> --task-set path/to/task_set.json
mh run score --run-id <run_id>
mh run show --run-id <run_id>
mh run diff --left-run-id <run_a> --right-run-id <run_b>
mh run failures --query "trait bound clone"
mh run export-trace --run-id <run_id> --output trace.json --format otel-json
```

`run` 还提供：

- `list`
- `index`
- `current`
- `archive-list`
- `archive`
- `prune`
- `compact`

其中 `compact` 会基于 catalog 保留最新/最佳 run，清理其余 run 的 `workspace/`，以降低磁盘占用。

### Candidate

```bash
mh candidate create --profile base --project demo --config-patch patch.json
mh candidate create --profile base --project demo --code-patch change.diff
mh candidate promote --candidate-id <candidate_id>
mh candidate index
mh candidate current
```

### Observe / Benchmark

```bash
mh observe summary --profile contextatlas_maintenance --project contextatlas
mh observe once --profile contextatlas_maintenance --project contextatlas --task-set task_sets/contextatlas/import_profile_and_audit.json
mh observe benchmark --profile contextatlas_benchmark --project contextatlas_benchmark --task-set task_sets/contextatlas/benchmark_retrieval_memory.json --spec configs/benchmarks/contextatlas_retrieval_memory_ab.json
mh observe benchmark-suite --profile contextatlas_benchmark --project contextatlas_benchmark --task-set task_sets/contextatlas/benchmark_retrieval_memory.json --suite configs/benchmarks/contextatlas_default_suite.json
```

`benchmark` 和 `benchmark-suite` 默认会在结束后自动 compact 旧 run workspace。

### Optimize

```bash
mh optimize propose --profile base --project demo
mh optimize shadow-run --candidate-id <candidate_id> --task-set path/to/task_set.json
```

当前实现支持两类 proposal 来源：

- 内置启发式：例如针对重复失败提升预算。
- 外部 `proposal_command`：由项目自定义脚本通过 stdin/stdout 生成 `config_patch`、`code_patch`、`proposal` 和 `notes`。

### Strategy

```bash
mh strategy shortlist configs/strategy_cards/contextatlas/*.json --profile contextatlas_benchmark --project contextatlas_benchmark
mh strategy inspect configs/strategy_cards/contextatlas/dense_chunking_external.json --profile contextatlas_benchmark --project contextatlas_benchmark
mh strategy build-spec --experiment external-strategy-eval --baseline current_indexing --output /tmp/spec.json configs/strategy_cards/contextatlas/dense_chunking_external.json
mh strategy create-candidate configs/strategy_cards/contextatlas/incremental_refresh_patch.json --profile contextatlas_benchmark --project contextatlas_benchmark
mh strategy benchmark configs/strategy_cards/contextatlas/dense_chunking_external.json --profile contextatlas_benchmark --project contextatlas_benchmark --task-set task_sets/contextatlas/benchmark_indexing_architecture_v2.json --experiment contextatlas_external_indexing_strategies --baseline current_indexing
```

Strategy card 支持：

- 兼容性检查
- 生成 benchmark variant
- 生成 candidate
- 对外部策略做可执行性分组和对比评测

### Dataset

```bash
mh dataset extract-failures --output datasets/failures.json
```

这个命令会从历史 run 的失败轨迹中提取结构化失败样本，可用于离线分析或后续优化流程。

## 内置资产

仓库目前内置了偏向 ContextAtlas 场景的资产：

- profiles: `contextatlas_maintenance`、`contextatlas_benchmark`、`contextatlas_patch_repair`
- projects: `contextatlas`、`contextatlas_benchmark`、`contextatlas_patch`
- benchmark specs: retrieval/memory A-B、indexing sweep、memory routing sweep、stability penalty calibration、external strategy first-pass suite
- task sets: import/audit、retrieval benchmark、indexing architecture benchmark、patch repair
- strategy cards: config-only、patch-based、research-only 等外部策略描述

这也说明当前项目已经从“通用骨架”推进到了“通用平台 + 一套 ContextAtlas 基准资产”的状态。

## 架构观察

从当前代码结构看，项目已经形成了比较明确的分层：

- `cli.py`: 参数解析与命令编排。
- `services/`: 面向产品/API 的稳定业务接口。
- `runtime.py` / `benchmark.py` / `optimizer.py`: 执行与实验编排核心。
- `catalog.py` / `compaction.py`: 运行资产治理。
- `strategy_cards.py`: 外部策略到内部 benchmark/candidate 的桥接层。
- `config_loader.py`: 配置分层与深度合并。
- `schemas.py`: Pydantic schema 与契约对象。

`docs/api-surface-v1.md` 也表明后续设计方向是让 CLI 和 HTTP API 共用 service 层，并把长时任务纳入 job 模型。

## 测试

运行全部测试：

```bash
pytest
```

项目当前测试覆盖了：

- CLI 命令面
- 配置加载
- benchmark / benchmark-suite
- catalog / archive / prune / compact
- optimize propose / shadow-run
- strategy card 兼容性与 spec 生成
- runtime / scoring / trace export / dataset extraction

## 参考文档

- [平台设计](docs/platform-design.md)
- [API Surface v1](docs/api-surface-v1.md)
- [Artifact Contracts](docs/artifact-contracts.md)
- [Data Model v1](docs/data-model-v1.md)
- [Gate Policy v1](docs/gate-policy-v1.md)
- [Benchmark Spec v2](docs/benchmark-spec-v2.md)
- [External Strategy Evaluation](docs/external-strategy-evaluation.md)

## 当前结论

如果把当前仓库当成一个产品来理解，它更接近“面向 Agent workflow 的实验操作系统”，而不是单纯的评测脚本集合。核心价值在于：

- 所有运行结果可落盘、可回放、可比较。
- 配置、候选、基准和策略之间已经形成闭环。
- 现有 service 层为后续 API 化和异步 job 化留出了明确边界。
