# Meta-Harness 复现指南

更新时间：2026-04-09

这份文档面向第一次接触仓库的读者。阅读顺序不是“把所有命令都看一遍”，而是：

1. 先跑通一条最短闭环
2. 看清楚关键 artifact 会落到哪里
3. 再按 dataset / benchmark / proposal 三条主线拆开复现

## 1. 环境

要求：

- Python 3.11+

安装：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

如果不使用入口脚本：

```bash
PYTHONPATH=src python -m meta_harness.cli --help
```

## 2. 先跑最短闭环

最短、最稳、最适合第一次体验的路径是公开 demo：

```bash
bash scripts/demo_public_flow.sh .demo-output
```

它会串起一次最小完整闭环，依次经过：

- `run init`
- `run execute`
- `optimize propose --proposal-only`
- `optimize materialize-proposal`
- `dataset build-task-set`
- `dataset ingest-annotations`
- `dataset derive-split`
- `dataset promote`
- `run export-trace`
- `optimize loop`
- `observe benchmark`
- `artifact contract validator`

## 3. 你会得到什么

脚本输出会直接打印关键 ID 和 artifact 路径，典型形态如下：

```text
demo_root=.demo-output
run_id=<generated-run-id>
proposal_id=<generated-proposal-id>
materialized_candidate_id=<generated-candidate-id>
proposal_dir=.demo-output/proposals/<generated-proposal-id>
dataset_dir=.demo-output/datasets/demo-public-cases
trace_export=.demo-output/exports/<generated-run-id>.otel.json
loop_id=<generated-loop-id>
benchmark_report=.demo-output/reports/benchmarks/demo_public_budget_headroom.json
validation_report=.demo-output/reports/demo_public_validation.json
```

最重要的输出目录：

- `.demo-output/runs`
- `.demo-output/candidates`
- `.demo-output/proposals`
- `.demo-output/datasets`
- `.demo-output/reports`
- `.demo-output/exports`

如果你只想判断“仓库是不是能真实跑通闭环”，看到这些目录和上面的 8 个字段就够了。

## 4. 公开 demo 资产

公开 demo 默认使用这些仓库内置资产：

- `configs/profiles/demo_public.json`
- `configs/projects/demo_public.json`
- `configs/benchmarks/demo_public_budget_headroom.json`
- `task_sets/demo/failure_repair.json`
- `demo/annotations/demo_dataset_annotations.jsonl`
- `scripts/demo_public_flow.sh`
- `reports/benchmarks/demo_public_budget_headroom.json`

它们不依赖任何本机私有项目。

## 5. 分支复现

如果你已经跑通最短闭环，可以按下面三条分支分别复现。

### 5.1 Dataset 路径

从 task set 物化 dataset：

```bash
PYTHONPATH=src python -m meta_harness.cli dataset build-task-set \
  --task-set task_sets/demo/failure_repair.json \
  --dataset-id demo-public-cases \
  --version v1 \
  --output datasets/demo-public-cases/v1/dataset.json
```

产物：

- `datasets/demo-public-cases/v1/dataset.json`
- `datasets/demo-public-cases/v1/manifest.json`

注入 annotation：

```bash
PYTHONPATH=src python -m meta_harness.cli dataset ingest-annotations \
  --dataset datasets/demo-public-cases/v1/dataset.json \
  --annotations demo/annotations/demo_dataset_annotations.jsonl \
  --output datasets/demo-public-cases/v2/dataset.json
```

派生 hard_case split：

```bash
PYTHONPATH=src python -m meta_harness.cli dataset derive-split \
  --dataset datasets/demo-public-cases/v2/dataset.json \
  --split hard_case \
  --dataset-id demo-public-cases-hard \
  --version v1 \
  --output datasets/demo-public-cases-hard/v1/dataset.json
```

promotion：

```bash
PYTHONPATH=src python -m meta_harness.cli dataset promote \
  --datasets-root datasets \
  --dataset-id demo-public-cases-hard \
  --version v1 \
  --split hard_case \
  --promoted-by demo-user \
  --reason "public demo promotion"
```

### 5.2 Proposal / Candidate 路径

先 proposal-only：

```bash
PYTHONPATH=src python -m meta_harness.cli optimize propose \
  --profile demo_public \
  --project demo_public \
  --config-root configs \
  --runs-root .demo-output/runs \
  --candidates-root .demo-output/candidates \
  --proposals-root .demo-output/proposals \
  --proposal-only
```

再物化 proposal：

```bash
PYTHONPATH=src python -m meta_harness.cli optimize materialize-proposal \
  --proposal-id <proposal_id> \
  --proposals-root .demo-output/proposals \
  --candidates-root .demo-output/candidates \
  --config-root configs
```

关键产物：

- `proposals/<proposal_id>/proposal.json`
- `proposals/<proposal_id>/proposal_evaluation.json`
- `candidates/<candidate_id>/candidate.json`
- `candidates/<candidate_id>/effective_config.json`

### 5.3 Benchmark / Loop 路径

先导出 trace：

```bash
PYTHONPATH=src python -m meta_harness.cli run export-trace \
  --run-id <run_id> \
  --runs-root .demo-output/runs \
  --output .demo-output/exports/<run_id>.otel.json
```

再跑一次最小 optimize loop：

```bash
PYTHONPATH=src python -m meta_harness.cli optimize loop \
  --profile demo_public \
  --project demo_public \
  --task-set task_sets/demo/failure_repair.json \
  --config-root configs \
  --runs-root .demo-output/runs \
  --candidates-root .demo-output/candidates \
  --proposals-root .demo-output/proposals \
  --reports-root .demo-output/reports \
  --max-iterations 1
```

最后跑公开 benchmark：

```bash
PYTHONPATH=src python -m meta_harness.cli observe benchmark \
  --profile demo_public \
  --project demo_public \
  --task-set task_sets/demo/failure_repair.json \
  --spec configs/benchmarks/demo_public_budget_headroom.json \
  --config-root configs \
  --runs-root .demo-output/runs \
  --candidates-root .demo-output/benchmark-candidates \
  --reports-root .demo-output/reports \
  --no-auto-compact-runs
```

关键产物：

- `reports/loops/<loop_id>/loop.json`
- `reports/loops/<loop_id>/iteration_history.jsonl`
- `reports/benchmarks/demo_public_budget_headroom.json`

## 6. 如何对照 benchmark 快照

公开 benchmark 快照：

- `reports/benchmarks/demo_public_budget_headroom.json`

当前公开快照的预期摘要：

- baseline 的 `budget.max_turns=6`，`score.composite=0.6`
- `budget_plus_two` 的 `budget.max_turns=8`，`score.composite=0.8`
- `best_variant=budget_plus_two`
- `delta_from_baseline.composite=0.2`

这份快照和 loop 的关系是：

- `optimize loop` 在同一 `demo_public + failure_repair` 路径上，默认 heuristic proposal 也是把 `budget.max_turns` 增加 2
- 所以可以直接对照 `reports/benchmarks/demo_public_budget_headroom.json` 和 `reports/loops/<loop_id>/loop.json`
- 如果 loop 首轮 proposal 也是 `increase_budget_on_repeated_failures`，那它应该落到和 snapshot 同方向的改进

## 7. 关键 artifact 索引

### Candidate

- `candidates/<candidate_id>/candidate.json`
- `candidates/<candidate_id>/effective_config.json`
- `candidates/<candidate_id>/proposal.json`

### Proposal

- `proposals/<proposal_id>/proposal.json`
- `proposals/<proposal_id>/proposal_evaluation.json`
- `proposals/<proposal_id>/code.patch`（如有）

### Run

- `runs/<run_id>/run_metadata.json`
- `runs/<run_id>/effective_config.json`
- `runs/<run_id>/score_report.json`
- `runs/<run_id>/evaluators/`
- `runs/<run_id>/tasks/`

### Loop

- `reports/loops/<loop_id>/loop.json`
- `reports/loops/<loop_id>/iteration_history.jsonl`
- `reports/loops/<loop_id>/iterations/<iteration_id>/`

### Benchmark

- `reports/benchmarks/<experiment_id>.json`

### Validation

- `reports/demo_public_validation.json`

### Dataset

- `datasets/<dataset_id>/<version>/dataset.json`
- `datasets/<dataset_id>/<version>/manifest.json`

## 8. 建议验证命令

如果你要验证公开 demo / artifact contract / proposal / loop 主线，最直接的一组回归入口是：

```bash
pytest tests/test_schema_contracts.py \
  tests/test_demo_assets.py \
  tests/test_cli_dataset.py \
  tests/test_cli_optimize.py -q
```

如果你只想先确认 CLI 和 demo 脚本本身能跑，优先跑：

```bash
PYTHONPATH=src python -m meta_harness.cli --help
bash scripts/demo_public_flow.sh .demo-output
```
