# ContextAtlas Integration

## 目标

将 `~/Develop/tools/ContextAtlas` 作为一个被治理系统接入 Meta-Harness，而不是把其内部实现直接嵌入平台。

当前接入方式：

- 工作流 profile: `contextatlas_maintenance`
- 项目 overlay: `contextatlas`
- task set: `task_sets/contextatlas/import_profile_and_audit.json`
- command evaluator: `scripts/contextatlas_run_eval.py`

新增的代码补丁工作流：

- 工作流 profile: `contextatlas_patch_repair`
- 项目 overlay: `contextatlas_patch`
- task set: `task_sets/contextatlas/repair_with_patch.json`
- command evaluator: `scripts/contextatlas_patch_eval.py`
- proposal generator: `scripts/contextatlas_patch_proposal.py`

新增的 benchmark 工作流：

- 工作流 profile: `contextatlas_benchmark`
- 项目 overlay: `contextatlas_benchmark`
- 默认 benchmark spec: `configs/benchmarks/contextatlas_retrieval_memory_ab.json`
- 默认 indexing sweep spec: `configs/benchmarks/contextatlas_indexing_sweep.json`
- 默认 memory routing sweep spec: `configs/benchmarks/contextatlas_memory_routing_sweep.json`
- 组合验证 spec: `configs/benchmarks/contextatlas_combo_validation.json`
- 默认 benchmark suite: `configs/benchmarks/contextatlas_default_suite.json`
- 当前最佳已知组合 overlay: `configs/projects/contextatlas_benchmark_current_best.json`
- task set: `task_sets/contextatlas/benchmark_retrieval_memory.json`
- command evaluator: `scripts/contextatlas_run_eval.py`

## 运行方式

### 1. 创建候选

```bash
PYTHONPATH=src python -m meta_harness.cli candidate create \
  --profile contextatlas_maintenance \
  --project contextatlas \
  --config-root configs \
  --candidates-root candidates \
  --notes "contextatlas maintenance"
```

### 2. 执行 shadow run

```bash
PYTHONPATH=src python -m meta_harness.cli optimize shadow-run \
  --candidate-id <candidate-id> \
  --task-set task_sets/contextatlas/import_profile_and_audit.json \
  --candidates-root candidates \
  --runs-root runs
```

### 3. 查看评分

```bash
cat runs/<run-id>/score_report.json
```

## 代码补丁候选运行方式

### 1. 创建补丁候选

```bash
PYTHONPATH=src python -m meta_harness.cli candidate create \
  --profile contextatlas_patch_repair \
  --project contextatlas_patch \
  --config-root configs \
  --candidates-root candidates \
  --code-patch /path/to/fix.patch \
  --notes "contextatlas patch repair"
```

### 1b. 基于历史失败自动生成补丁候选

```bash
PYTHONPATH=src python -m meta_harness.cli optimize propose \
  --profile contextatlas_patch_repair \
  --project contextatlas_patch \
  --config-root configs \
  --runs-root runs \
  --candidates-root candidates
```

### 2. 执行 patch shadow run

```bash
PYTHONPATH=src python -m meta_harness.cli optimize shadow-run \
  --candidate-id <candidate-id> \
  --task-set task_sets/contextatlas/repair_with_patch.json \
  --candidates-root candidates \
  --runs-root runs
```

## 观测基础设施

### 1. 执行一次观测

```bash
PYTHONPATH=src python -m meta_harness.cli observe once \
  --profile contextatlas_maintenance \
  --project contextatlas \
  --config-root configs \
  --runs-root runs \
  --task-set task_sets/contextatlas/import_profile_and_audit.json
```

返回 JSON，至少包含：

- `run_id`
- `score`
- `needs_optimization`
- `recommended_focus`
- `triggered_optimization`

### 2. 需要时自动进入 optimize propose

```bash
PYTHONPATH=src python -m meta_harness.cli observe once \
  --profile contextatlas_patch_repair \
  --project contextatlas_patch \
  --config-root configs \
  --runs-root runs \
  --candidates-root candidates \
  --task-set task_sets/contextatlas/repair_with_patch.json \
  --auto-propose
```

当最新 run 存在健康缺口、richer metrics 缺口，或者用户显式要求 `--auto-propose` 且项目已配置 `proposal_command` 时，返回结果会带上 `candidate_id`。

### 3. 汇总当前观测状态

```bash
PYTHONPATH=src python -m meta_harness.cli observe summary \
  --profile contextatlas_patch_repair \
  --project contextatlas_patch \
  --runs-root runs
```

返回 JSON，至少包含：

- `run_count`
- `latest_run_id`
- `best_run_id`
- `needs_optimization`
- `recommended_focus`

### 4. 执行参数/开关对照评测

```bash
PYTHONPATH=src python -m meta_harness.cli observe benchmark \
  --profile contextatlas_benchmark \
  --project contextatlas_benchmark \
  --config-root configs \
  --runs-root runs \
  --candidates-root candidates \
  --task-set task_sets/contextatlas/benchmark_retrieval_memory.json \
  --spec configs/benchmarks/contextatlas_retrieval_memory_ab.json
```

默认 benchmark 会比较：

- `baseline`
- `retrieval_wide`
- `dense_chunking`
- `memory_off`

如果只想专门扫描索引参数，可以直接跑：

```bash
PYTHONPATH=src python -m meta_harness.cli observe benchmark \
  --profile contextatlas_benchmark \
  --project contextatlas_benchmark \
  --config-root configs \
  --runs-root runs \
  --candidates-root candidates \
  --task-set task_sets/contextatlas/benchmark_retrieval_memory.json \
  --spec configs/benchmarks/contextatlas_indexing_sweep.json \
  --focus indexing
```

这套默认 indexing sweep 会比较：

- `baseline`
- `topk_12_rerank_24`
- `topk_16_rerank_32`
- `chunk_800_overlap_120`
- `chunk_1200_overlap_160`

如果想用 V2 结构评测“索引方式 + 质量 + 消耗”而不只是参数 sweep，可以单独跑：

```bash
PYTHONPATH=src python -m meta_harness.cli observe benchmark \
  --profile contextatlas_benchmark \
  --project contextatlas_benchmark \
  --config-root configs \
  --runs-root runs \
  --candidates-root candidates \
  --task-set task_sets/contextatlas/benchmark_indexing_architecture_v2.json \
  --spec configs/benchmarks/contextatlas_indexing_architecture_v2.json \
  --focus indexing
```

这份 V2 skeleton 会：

- 在 spec 顶层声明 `analysis_mode = "architecture"`
- 用 `variant_type` / `hypothesis` / `implementation_id` 区分参数变体与方法族变体
- 用 `scenarios` 和 `report.primary_axes = ["quality", "mechanism", "stability", "cost"]` 固化结果解读维度

说明：

- 当前已能稳定评估索引质量、机制和稳定性
- 当前也已输出 `indexing.build_latency_ms`、`indexing.peak_memory_mb`、`indexing.index_size_bytes`、`indexing.query_p95_ms` 等 cost probes
- 如果在 `evaluation.stability.cost_weights` 中声明权重，`ranking_score` 会对高于 baseline 的 indexing 成本增量施加惩罚
- 详细说明见 `docs/contextatlas-indexing-benchmark-v2.md`

如果只想专门看记忆模块到底有没有收益，以及哪种编排更好，可以直接跑：

```bash
PYTHONPATH=src python -m meta_harness.cli observe benchmark \
  --profile contextatlas_benchmark \
  --project contextatlas_benchmark \
  --config-root configs \
  --runs-root runs \
  --candidates-root candidates \
  --task-set task_sets/contextatlas/benchmark_retrieval_memory.json \
  --spec configs/benchmarks/contextatlas_memory_routing_sweep.json \
  --focus memory
```

这套默认 memory routing sweep 会比较：

- `baseline`
- `memory_lightweight`
- `memory_freshness_bias`
- `memory_strict_pruning`
- `memory_off`

如果要验证“可独立叠加”的 retrieval / indexing 组合效应，可直接跑：

```bash
PYTHONPATH=src python -m meta_harness.cli observe benchmark \
  --profile contextatlas_benchmark \
  --project contextatlas_benchmark \
  --config-root configs \
  --runs-root runs \
  --candidates-root candidates \
  --task-set task_sets/contextatlas/benchmark_retrieval_memory.json \
  --spec configs/benchmarks/contextatlas_combo_validation.json
```

这套组合验证矩阵会比较：

- `old_baseline`
- `retrieval_wide_only`
- `indexing_dense_only`
- `retrieval_wide_plus_indexing_dense`

说明：历史上的 `retrieval_wide` 与 `topk_16_rerank_32` 都修改 `retrieval.top_k / rerank_k`，不属于严格独立维度；因此组合验证改为使用独立的 `indexing.chunk_size / indexing.chunk_overlap` 作为 indexing 因子。

如果想一次把默认三套 benchmark 全跑完，可以直接跑：

```bash
PYTHONPATH=src python -m meta_harness.cli observe benchmark-suite \
  --profile contextatlas_benchmark \
  --project contextatlas_benchmark \
  --config-root configs \
  --runs-root runs \
  --candidates-root candidates \
  --task-set task_sets/contextatlas/benchmark_retrieval_memory.json \
  --suite configs/benchmarks/contextatlas_default_suite.json
```

`benchmark-suite` 在 suite 开始时会冻结一次 `runtime.workspace.source_repo`，后续所有 benchmark/variant 都复用这份源码快照；这样长时间运行过程中，即使原始仓库继续被修改，也不会让后半段结果跑到另一份代码。

默认 suite 现在包含：

- retrieval / memory A-B
- indexing sweep
- indexing architecture V2
- memory routing sweep
- stability penalty calibration

并且 suite entry 已支持各自声明 `task_set`，所以：

- indexing architecture V2 会自动使用 `task_sets/contextatlas/benchmark_indexing_architecture_v2.json`
- stability calibration 会自动使用 `task_sets/contextatlas/benchmark_stability_penalty_calibration.json`
- 其他 benchmark 仍沿用命令行传入的全局 `--task-set`

如果要把外部发现的索引策略接入当前评测流程，建议先用 `strategy_card` 标准化，再生成 benchmark spec。说明见：

- `docs/external-strategy-evaluation.md`

所有 ContextAtlas benchmark 报告都建议标记为 `snapshot-based`，并说明 `contextatlas_benchmark_probe.ts` 会直接读取 run 内的 `effective_config.json` 来消费 retrieval / indexing / memory 配置。

自定义 `benchmark.json` 至少包含：

```json
{
  "experiment": "retrieval-memory-ab",
  "baseline": "baseline",
  "variants": [
    {"name": "baseline"},
    {"name": "larger_top_k", "config_patch": {"retrieval": {"top_k": 12}}},
    {"name": "larger_chunks", "config_patch": {"indexing": {"chunk_size": 1200, "chunk_overlap": 160}}},
    {"name": "memory_off", "config_patch": {"contextatlas": {"memory": {"enabled": false}}}}
  ]
}
```

返回 JSON，至少包含：

- `experiment`
- `baseline`
- `best_variant`
- `variants`

每个 variant 会记录：

- `name`
- `candidate_id`
- `run_id`
- `score`
- `delta_from_baseline`

如果设置了 `repeats`，还会额外记录：

- `run_ids`
- `stability`
- `stability_assessment`

顶层还会记录：

- `repeat_count`
- `stability_policy`

如果只想看某一类差异，可以加 `--focus indexing|memory|retrieval`。

## task set 内容

当前 task set 会依次执行：

1. `hub:register-project`
2. `profile:import-omc`
3. `pnpm build`
4. `index ${workspace_dir}`
5. `tests/omc-profile-import.test.ts`
6. `profile:show`
7. `memory:check-consistency`
8. `health:check --json --project-id <workspace projectId>`
9. `contextatlas_benchmark_probe.ts --project-id <workspace projectId>`

## 评分逻辑

`contextatlas_run_eval.py` 会从 task 输出中提取：

- `profile_present`
- `memory_consistency_ok`
- `snapshot_ready`
- `vector_index_ready`
- `db_integrity_ok`
- 当 `health_check` 或 `benchmark_probe` 输出结构化 benchmark 数据时，也会追加：
- `memory_module_count` / `memory_scope_count`
- `memory_completeness` / `memory_freshness` / `memory_stale_ratio`
- `index_document_count` / `index_chunk_count`
- `vector_coverage_ratio` / `index_freshness_ratio`
- `retrieval_hit_rate` / `retrieval_mrr` / `grounded_answer_rate`
- `task_success_rate` / `task_grounded_success_rate` / `task_case_count`

并通过 command evaluator 合并到 `score_report.json`。

`contextatlas_patch_eval.py` 会从 patch workflow 输出中提取：

- `patch_applied`
- `build_ok`
- `targeted_tests_ok`
- `profile_present`
- `memory_consistency_ok`

`contextatlas_patch_proposal.py` 会读取历史失败签名：

- 优先读取历史 `score_report`，当 `profile_present` / `memory_consistency_ok` 存在质量缺口时生成代码补丁候选
- 命中 `.omc` / profile / memory consistency 相关失败时也会生成代码补丁候选
- 当代码补丁已经存在于源码中时，shadow-run 会把它视为 `patch_already_present`，不会因此失败
- 当最新 run 仍有索引健康缺口时，生成 `explore_indexing_headroom`
- 当最新 run 的 `vector_coverage_ratio` / `index_freshness_ratio` 明显偏低时，也会直接生成 `explore_indexing_headroom`
- 当最新 run 已健康、但历史上存在记忆治理缺口时，生成 `explore_memory_headroom`
- 当最新 run 的 `memory_completeness` / `memory_freshness` / `memory_stale_ratio` 明显偏差时，也会直接生成 `explore_memory_headroom`
- 当当前整体健康且没有待闭合缺口时，生成 `explore_retrieval_headroom`
- 当最新 run 的 `retrieval_hit_rate` / `retrieval_mrr` / `grounded_answer_rate` 明显偏低时，也会直接生成 `explore_retrieval_headroom`
- 只有最新 run 仍存在未闭合失败时，才回退为 failure-driven 配置型 proposal
- `optimize propose` 现在会把每个历史 run 的 `run_context` 一并传给 proposal command，包括 task_result 汇总、`show_profile` / `check_memory` / `test_omc_import` / `health_check` 提取出的上下文信号
- `configs/projects/contextatlas_patch.json` 中的 `optimization.headroom_defaults` 定义了 indexing / memory / retrieval 三类 headroom 的默认调参模板、目标 signals 和待执行 checks
- `configs/projects/contextatlas_patch.json` 中的 `optimization.headroom_thresholds` 定义了 richer metrics 的判定阈值，可按项目覆写，不再依赖脚本内写死常量
- proposal 生成的 `config_patch` 现在会同时写入 `optimization.headroom` 结构化证据，以及 `contextatlas.headroom.<category>` 的 signals/checks，避免 headroom 只剩一个 `focus` 标签
