# ContextAtlas Benchmark Methodology

## Current confirmed baseline conclusions

- retrieval 最优：`retrieval_wide`
- indexing sweep 最优：`topk_16_rerank_32`
- memory routing 最优：`baseline`

## Current best known combination

- 配置名：`contextatlas_current_best_known_v1`
- 组合：`retrieval_wide + topk_16_rerank_32 + memory_baseline`
- 可直接复用的 project overlay：`configs/projects/contextatlas_benchmark_current_best.json`
- 旧默认保留：`configs/projects/contextatlas_benchmark.json`

> 说明：`retrieval_wide` 与 `topk_16_rerank_32` 都会修改 `retrieval.top_k / rerank_k`，因此它们不是严格独立维度。
> 为了完成真正的组合效应验证，组合矩阵已改为“retrieval 宽搜”与“indexing chunk 参数”这两个可独立叠加的因子：
> `configs/benchmarks/contextatlas_combo_validation.json`。

当前语义约束：

- retrieval 只管 `top_k / rerank_k`
- indexing 只管 `chunk_size / chunk_overlap`

## Benchmark constraints (fixed process)

1. `observe benchmark` / `observe benchmark-suite` 必须先冻结源码快照。
2. 同一 benchmark run 内的所有 variants 复用同一份源码快照。
3. `benchmark-suite` 内的所有 benchmark 也复用同一份源码快照。
4. `probe` 必须真实读取 `effective_config.json` 并消费配置，而不是只按 variant 名称分支。
5. 回归测试持续覆盖：
   - snapshot-based source freezing
   - probe consumption of retrieval / indexing / memory config
   - task-level benchmark quality metrics
   - repeat-based stability policy evaluation

## Stability policy

- benchmark 输出应带最小重复次数规范。
- 当 composite 波动超过阈值时，应标记为不稳定。
- 当某个 variant 分数较高但波动过大时，应标记为“高分但不稳定”。

建议关注：

- 最小重复次数
- composite range / stddev
- 高分但不稳定

## penalty 参数校准

如果要校准 ranking penalty，建议单独运行：

- `configs/benchmarks/contextatlas_stability_penalty_calibration.json`

这类 calibration benchmark 应重点比较：

- `unstable_high_score_penalty`
- `range_weight`
- `stddev_weight`

目标不是追求“扣分越大越好”，而是找到：

- 能压制明显不稳定高分
- 又不会误伤稳定高分
- 与当前 task-level benchmark 波动结构匹配

建议记录：

- raw composite 排名
- ranking_score 排名
- best_by_quality / best_by_stability / best_variant 是否一致

## Cost-sensitive ranking

当 benchmark 已经输出 indexing cost probes 时，可以在 `evaluation.stability.cost_weights` 中声明权重，例如：

```json
{
  "evaluation": {
    "stability": {
      "cost_weights": {
        "index_build_latency_ms": 0.0015,
        "index_size_bytes": 0.000001
      }
    }
  }
}
```

当前语义是：

- 只对“高于 baseline 的成本增量”加罚
- 不对更低成本做额外奖励
- 成本惩罚与稳定性惩罚共同组成 `ranking_penalty`

建议优先用于：

- indexing strategy 对比
- freshness / cost tradeoff 对比
- 高质量但高成本 variant 的排序纠偏

## Reporting convention

- 所有后续结果都应标注为 `snapshot-based`。
- 所有后续实验默认对照组都以 `contextatlas_current_best_known_v1` 为起点；如需回退，使用 `contextatlas_benchmark`。
- 如果继续做 memory routing，只做假设驱动的小范围尝试，不再做无方向的大 sweep。
