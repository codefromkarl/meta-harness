# Meta-Harness 复现指南

更新时间：2026-04-08

本文档面向第一次接触仓库的读者，目标是：

- 在本地跑通最小闭环
- 理解关键 artifact 会写到哪里
- 能复现 dataset / benchmark / proposal 三条主线

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

## 2. 最小 CLI 路径

先确认 CLI 可用：

```bash
PYTHONPATH=src python -m meta_harness.cli --help
PYTHONPATH=src python -m meta_harness.cli profile list
```

## 2.1 一键公开 demo

仓库内提供了一条不依赖任何私有外部项目的最小 demo：

```bash
bash scripts/demo_public_flow.sh .demo-output
```

这条脚本会串起：

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

产物会落到：

- `.demo-output/runs`
- `.demo-output/candidates`
- `.demo-output/benchmark-candidates`
- `.demo-output/proposals`
- `.demo-output/datasets`
- `.demo-output/reports`
- `.demo-output/exports`

典型标准输出示例：

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

## 2.2 一键 OpenClaw demo

如果本机已经安装可用的 `openclaw` CLI，可以直接运行：

```bash
bash scripts/bootstrap.sh --require-openclaw
bash scripts/demo_openclaw_websearch_analysis.sh .openclaw-demo-output
```

这条脚本会：

- 建立 Python 环境
- 检查 `openclaw agent` 是否可用
- 运行打包在仓库内的 WebSearch + Data Analysis benchmark
- 输出 benchmark 结果和 best run 的 trace export

主要资产：

- `configs/profiles/demo_openclaw.json`
- `configs/projects/demo_openclaw.json`
- `configs/benchmarks/demo_openclaw_websearch_analysis.json`
- `task_sets/demo/openclaw_websearch_analysis.json`
- `demo/openclaw_websearch_analysis/`

## 3. Dataset 路径

### 3.1 从 task set 物化 dataset

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

### 3.2 注入 annotation

```bash
PYTHONPATH=src python -m meta_harness.cli dataset ingest-annotations \
  --dataset datasets/demo-public-cases/v1/dataset.json \
  --annotations path/to/annotations.jsonl \
  --output datasets/demo-public-cases/v2/dataset.json
```

### 3.3 派生 hard_case / adversarial split

```bash
PYTHONPATH=src python -m meta_harness.cli dataset derive-split \
  --dataset datasets/demo-public-cases/v2/dataset.json \
  --split hard_case \
  --dataset-id demo-public-cases-hard \
  --version v1 \
  --output datasets/demo-public-cases-hard/v1/dataset.json
```

### 3.4 promotion

```bash
PYTHONPATH=src python -m meta_harness.cli dataset promote \
  --datasets-root datasets \
  --dataset-id demo-public-cases-hard \
  --version v1 \
  --split hard_case \
  --promoted-by demo-user \
  --reason "ready for regression"
```

产物：

- `datasets/promotions.json`
- `datasets/promotion_records.json`
- `datasets/<dataset_id>/<version>/promotion_target.json`

## 4. Proposal 路径

### 4.1 直接生成 candidate

```bash
PYTHONPATH=src python -m meta_harness.cli optimize propose \
  --profile demo_public \
  --project demo_public \
  --config-root configs \
  --runs-root runs \
  --candidates-root candidates
```

产物：

- `proposals/<proposal_id>/proposal.json`
- `candidates/<candidate_id>/candidate.json`
- `candidates/<candidate_id>/effective_config.json`
- `candidates/<candidate_id>/proposal.json`

### 4.2 proposal-only

```bash
PYTHONPATH=src python -m meta_harness.cli optimize propose \
  --profile demo_public \
  --project demo_public \
  --config-root configs \
  --runs-root runs \
  --candidates-root candidates \
  --proposals-root proposals \
  --proposal-only
```

输出是 `proposal_id`。

典型输出示例：

```text
<generated-proposal-id>
```

### 4.3 后续物化 candidate

```bash
PYTHONPATH=src python -m meta_harness.cli optimize materialize-proposal \
  --proposal-id <proposal_id> \
  --proposals-root proposals \
  --candidates-root candidates \
  --config-root configs
```

### 4.4 使用 `llm_harness` proposer

如果你希望 `optimize propose` 或 `mh optimize loop` 走 LLM 风格 proposal，但又不想把仓库直接绑定到某个模型 SDK，可以在 project override 中配置 `optimization.llm_harness`：

```json
{
  "workflow": "base",
  "overrides": {
    "optimization": {
      "llm_harness": {
        "command": ["python", "scripts/generate_llm_proposal.py"],
        "model": "gpt-5.4",
        "system_prompt": "You are an offline harness optimizer."
      }
    }
  }
}
```

仓库内已经提供了一个最小可运行示例：

- `scripts/generate_llm_proposal.py`

约定：

- `command` 会收到 JSON stdin，其中包含 `model`、`system_prompt`、`user_prompt`、`objective`、`experience`、`effective_config`
- 命令需要返回 JSON，形状与 `proposal_command` 一致：`proposal`、可选 `config_patch`、可选 `code_patch`、可选 `notes`
- 只要 `optimization.llm_harness.command` 和 `model` 存在，`optimize propose` 会优先使用 `llm_harness`
- `observe once --auto-propose` 在没有 `proposal_command` 时，也会识别这组配置并触发 proposal 路径

最小返回示例：

```json
{
  "proposal": {
    "strategy": "llm_harness_patch",
    "summary": "increase retrieval breadth before reranking"
  },
  "config_patch": {
    "retrieval": {
      "top_k": 12
    }
  },
  "notes": "generated by llm harness"
}
```

## 5. 公开 demo 资产

仓库当前对外推荐的最小公开资产是：

- `configs/profiles/demo_public.json`
- `configs/projects/demo_public.json`
- `configs/benchmarks/demo_public_budget_headroom.json`
- `task_sets/demo/failure_repair.json`
- `demo/annotations/demo_dataset_annotations.jsonl`
- `scripts/demo_public_flow.sh`
- `reports/benchmarks/demo_public_budget_headroom.json`

它们不依赖任何本机私有参考项目。

## 6. 公开 benchmark snapshot

推荐复现命令：

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

对应快照：

- `reports/benchmarks/demo_public_budget_headroom.json`

当前公开快照的预期摘要：

- baseline 的 `budget.max_turns=6`，`score.composite=0.6`
- `budget_plus_two` 的 `budget.max_turns=8`，`score.composite=0.8`
- `best_variant=budget_plus_two`
- `delta_from_baseline.composite=0.2`

如何用它对照 loop：

- `optimize loop` 在同一 `demo_public` + `failure_repair` 路径上，默认 heuristic proposal 也是把 `budget.max_turns` 增加 2
- 因此外部读者可以直接对照 `reports/benchmarks/demo_public_budget_headroom.json` 与 `reports/loops/<loop_id>/loop.json`
- 如果 loop 的首轮 proposal 也是 `increase_budget_on_repeated_failures`，那么它应该落到与 snapshot 同方向的改进

说明：

- 这份 snapshot 是一条公开、确定性、可 smoke 的 release benchmark
- 它用于说明 loop 的最小改进信号是否可复现，不代表真实业务任务已经成功修复

## 7. 关键 artifact

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

```bash
pytest tests/test_schema_contracts.py \
  tests/test_demo_assets.py \
  tests/test_cli_dataset.py \
  tests/test_cli_optimize.py -q
```

如果你要验证这轮公开 demo / artifact contract / proposal / loop 收尾主线，以上是当前最直接的一组回归入口。
