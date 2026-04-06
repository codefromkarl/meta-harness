# ContextAtlas Indexing Benchmark V2

## 目标

这份资产把 ContextAtlas 的 indexing benchmark 从“参数 sweep”升级到“索引方式 + 质量 + 消耗”的 V2 评测骨架。

当前新增的 spec：

- `configs/benchmarks/contextatlas_indexing_architecture_v2.json`

它不是默认 suite 的一部分，目的是先提供一个可单独运行的 architecture benchmark skeleton，不扰动现有稳定基线。

## 当前可直接评的内容

基于 `task_sets/contextatlas/benchmark_indexing_architecture_v2.json`、`scripts/contextatlas_benchmark_probe.ts` 和 V2 benchmark 流程，当前已经能稳定覆盖：

- 索引质量：
  - `vector_coverage_ratio`
  - `index_freshness_ratio`
  - `retrieval_hit_rate`
  - `retrieval_mrr`
  - `grounded_answer_rate`
  - `task_success_rate`
  - `task_grounded_success_rate`
- 执行机制：
  - `fingerprints.retrieval.strategy`
  - `fingerprints.indexing.chunk_profile`
  - `fingerprints.memory.routing_mode`
  - `probes.retrieval.retrieval_budget`
  - `probes.retrieval.rerank_budget`
  - `probes.task.case_count`
- 稳定性：
  - `repeats`
  - `composite_range`
  - `composite_stddev`
  - `best_by_quality`
  - `best_by_stability`
  - `ranking_score`

这意味着现在就可以比较：

- 不同 chunk profile 对 freshness-sensitive retrieval 的影响
- 不同 indexing skeleton 在场景任务上的 capability gains
- 高分 variant 是否稳定

## 当前已经接入的成本指标

`scripts/contextatlas_benchmark_probe.ts` 现在已经输出这些 indexing cost probes：

- `indexing.build_latency_ms`
- `indexing.peak_memory_mb`
- `indexing.index_size_bytes`
- `indexing.embedding_calls`
- `indexing.files_scanned_count`
- `indexing.files_reindexed_count`
- `indexing.query_p50_ms`
- `indexing.query_p95_ms`

这些信号会进入：

- `benchmark_probe.stdout.txt`
- `score_report.cost`
- `delta_from_baseline.cost`

如果在 `evaluation.stability.cost_weights` 中声明权重，`ranking_score` 还会自动对“高于 baseline 的成本增量”施加惩罚。

当前还没有单独接入的，是更细粒度的：

- `indexing.incremental_latency_ms`
- 更真实的运行时采样内存
- 更真实的索引磁盘体积统计

也就是说，当前版本已经能做相对稳定的“成本敏感排序”，但其中一部分成本仍然是 probe 内的结构化近似值，而不是系统级采样值。

## Spec 设计

`contextatlas_indexing_architecture_v2.json` 里有三类 variant：

- `parameter`
  - 用于观察 chunk profile 本身的收益和代价
- `method_family`
  - 用于承载 `incremental_refresh`、`freshness_guard` 这类索引方法假设
- baseline
  - 用于锚定 snapshot-based 对照组

当前 skeleton 中的 `method_family` variant 先通过：

- `variant_type`
- `hypothesis`
- `implementation_id`
- `tags`
- `optimization.indexing_strategy_hint`

来表达方法意图；真正的运行机制指纹，后续要由 probe 补充，例如：

- `fingerprints.indexing.update_mode`
- `fingerprints.indexing.freshness_guard`

## 推荐运行方式

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

这套 task set 结构是：

- `indexing-bootstrap`
  - 负责依赖安装、project register、profile import、build、index、health check
- 六个 scenario task
  - 只复用已注册 `project_id`
  - 通过 `contextatlas_benchmark_probe.ts --scenario <id>` 分别输出各自场景的质量/机制/成本信号

## 结果解读

建议把结果分成三层看：

1. 质量层
- 看 `delta_from_baseline`
- 看 `capability_gains`
- 重点观察 `index_freshness_sensitive`、`recent_change_discovery`、`stale_index_recovery`

2. 机制层
- 看 `mechanism.fingerprints`
- 确认实际运行路径是否真的与 variant 假设一致

3. 成本层
- 看 `score.cost`
- 看 `delta_from_baseline.cost`
- 如果配置了 `evaluation.stability.cost_weights`，再看 `ranking_score` / `cost_penalty`

## 建议后续演进

建议按这个顺序继续：

1. 为 `recent_change_discovery` 和 `stale_index_recovery` 增加更专门的 task case。
2. 把成本 probes 从“结构化近似”升级为更真实的系统采样。
3. 为不同项目沉淀一组默认 `cost_weights`。
4. 对外部索引策略，先整理成 `strategy_card`，再生成 benchmark spec 接入评测。

外部策略接入方式见：

- `docs/external-strategy-evaluation.md`
