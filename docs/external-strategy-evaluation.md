# External Strategy Evaluation

## 目标

这份文档定义 Meta-Harness 如何接入“外部发现的索引策略”，把它们标准化成可执行的 benchmark variant，而不是直接把网页思路手工塞进 benchmark spec。

当前最小闭环已经支持：

1. 用 `strategy_card` 描述外部策略
2. 把可执行策略转换成 benchmark variant
3. 生成可直接运行的 benchmark spec
4. 用现有 V2 benchmark / suite 继续评测

## Strategy Card

当前 `strategy_card` 的核心字段在 [schemas.py](/home/yuanzhi/Develop/tools/meta-harness/src/meta_harness/schemas.py) 里定义：

- `strategy_id`
- `title`
- `source`
- `category`
- `group`
- `priority`
- `change_type`
- `variant_name`
- `hypothesis`
- `implementation_id`
- `variant_type`
- `compatibility`
- `expected_benefits`
- `expected_costs`
- `config_patch`
- `code_patch`
- `expected_signals`
- `risk_notes`
- `tags`

其中最关键的是：

- `change_type = config_only`
  - 适合纯参数或纯配置策略
- `change_type = patch_based`
  - 适合需要代码补丁接入的新索引实现
- `change_type = not_yet_executable`
  - 只记录，不进入 benchmark spec

## 示例

```json
{
  "strategy_id": "indexing/freshness-guard-v1",
  "title": "Freshness Guard",
  "source": "https://example.invalid/indexing/freshness-guard",
  "category": "indexing",
  "change_type": "config_only",
  "variant_name": "freshness_guard_external",
  "hypothesis": "freshness guard improves stale-index recovery with acceptable cost growth",
  "config_patch": {
    "indexing": {
      "chunk_size": 1200,
      "chunk_overlap": 160,
      "freshness_guard": true
    }
  },
  "expected_signals": {
    "probes": {
      "indexing.index_freshness_ratio": {
        "min": 0.9
      }
    }
  },
  "tags": ["external", "freshness"]
}
```

## CLI

当前可以直接用：

```bash
PYTHONPATH=src python -m meta_harness.cli strategy build-spec \
  --template contextatlas_indexing_v2 \
  --experiment external-indexing-comparison \
  --baseline current_indexing \
  --output configs/benchmarks/external_indexing_comparison.json \
  configs/strategy_cards/contextatlas/freshness_guard_external.json \
  configs/strategy_cards/contextatlas/incremental_refresh_patch.json
```

这个命令会：

- 读取多个 `strategy_card`
- 自动跳过 `not_yet_executable` 且没有 `config_patch/code_patch` 的卡片
- 生成 V2 benchmark spec
- 当 `--template contextatlas_indexing_v2` 时，会自动注入 ContextAtlas indexing V2 的默认 scenarios、repeats 和 recommended task set

实现位置在：

- [strategy_cards.py](/home/yuanzhi/Develop/tools/meta-harness/src/meta_harness/strategy_cards.py)
- [cli.py](/home/yuanzhi/Develop/tools/meta-harness/src/meta_harness/cli.py)

如果想直接把某个外部策略变成 candidate，可以用：

```bash
PYTHONPATH=src python -m meta_harness.cli strategy create-candidate \
  --profile contextatlas_benchmark \
  --project contextatlas_benchmark \
  --config-root configs \
  --candidates-root candidates \
  configs/strategy_cards/contextatlas/freshness_guard_external.json
```

如果想在真正执行前先看 compatibility gate，可以用：

```bash
PYTHONPATH=src python -m meta_harness.cli strategy inspect \
  --profile contextatlas_benchmark \
  --project contextatlas_benchmark \
  --config-root configs \
  configs/strategy_cards/contextatlas/incremental_refresh_patch.json
```

当前 gate 会返回：

- `status = executable`
- `status = review_required`
- `status = blocked`

并给出：

- `missing_runtime_keys`
- `missing_paths`
- `missing_artifacts`

如果想先对一批策略卡做批量筛选，可以用：

```bash
PYTHONPATH=src python -m meta_harness.cli strategy shortlist \
  --profile contextatlas_benchmark \
  --project contextatlas_benchmark \
  --config-root configs \
  configs/strategy_cards/contextatlas/dense_chunking_external.json \
  configs/strategy_cards/contextatlas/freshness_guard_external.json \
  configs/strategy_cards/contextatlas/incremental_refresh_patch.json \
  configs/strategy_cards/contextatlas/graph_posting_lists_research_only.json
```

输出会分成三组：

- `executable`
- `review_required`
- `blocked`

并且组内会按：

1. `priority`
2. `group`
3. `strategy_id`

排序，便于先处理真正值得跑的策略。

如果想不落静态 spec，直接从若干 `strategy_card` 跑 benchmark，可以用：

```bash
PYTHONPATH=src python -m meta_harness.cli strategy benchmark \
  --profile contextatlas_benchmark \
  --project contextatlas_benchmark \
  --config-root configs \
  --runs-root runs \
  --candidates-root candidates \
  --task-set task_sets/contextatlas/benchmark_indexing_architecture_v2.json \
  --experiment external-indexing-comparison \
  --baseline current_indexing \
  --template contextatlas_indexing_v2 \
  --focus indexing \
  configs/strategy_cards/contextatlas/dense_chunking_external.json \
  configs/strategy_cards/contextatlas/freshness_guard_external.json
```

## 当前边界

这套平台当前只解决：

- 外部策略的标准化表示
- 外部策略到 benchmark variant 的转换
- 外部策略的本地评测接入

它还没有自动完成：

- 上网搜索策略
- 自动判断论文/博客实现是否可迁移
- 自动生成高质量 patch

所以合理用法是：

1. 外部 research 先产出 `strategy_card`
2. 先用 compatibility gate 判定是否可执行
3. 再用 `strategy shortlist` 做批量筛选
4. Meta-Harness 负责把它变成 benchmark variant / candidate
5. 再用现有 benchmark / suite 跑实测

## 仓库内示例资产

当前仓库已提供一批 ContextAtlas 示例资产：

- `configs/strategy_cards/contextatlas/dense_chunking_external.json`
- `configs/strategy_cards/contextatlas/freshness_guard_external.json`
- `configs/strategy_cards/contextatlas/incremental_refresh_patch.json`
- `configs/strategy_cards/contextatlas/graph_posting_lists_research_only.json`
- `configs/benchmarks/contextatlas_external_indexing_strategies.json`
- `configs/benchmarks/contextatlas_external_strategy_first_pass_suite.json`
- `configs/strategy_pools/contextatlas_first_pass.json`

其中：

- 前三个可以直接进入 benchmark
- `graph_posting_lists_research_only.json` 会被模板生成过程自动跳过

如果要做第一轮初评，可以直接跑：

```bash
PYTHONPATH=src python -m meta_harness.cli observe benchmark-suite \
  --profile contextatlas_benchmark \
  --project contextatlas_benchmark \
  --config-root configs \
  --runs-root runs \
  --candidates-root candidates \
  --task-set task_sets/contextatlas/benchmark_retrieval_memory.json \
  --suite configs/benchmarks/contextatlas_external_strategy_first_pass_suite.json
```

跑完后可以用：

```bash
python scripts/contextatlas_benchmark_summary.py path/to/benchmark-suite-output.json
```

来快速看：

- `best_variant`
- `best_by_quality`
- `best_by_stability`
- `ranking_penalty / stability_penalty / cost_penalty`

如果想先只生成首轮评估计划和 shortlist，可以用：

```bash
python scripts/contextatlas_first_pass_runner.py \
  --pool configs/strategy_pools/contextatlas_first_pass.json \
  --config-root configs \
  --dry-run
```

## 推荐落地顺序

1. 先用当前 indexing V2 闭环本地参数评测。
2. 再把外部策略整理成 `strategy_card`。
3. 先跑 `config_only` 策略。
4. 确认流程稳定后，再接 `patch_based` 的真实实现替换。
