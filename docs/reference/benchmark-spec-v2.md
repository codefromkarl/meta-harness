# Meta-Harness Benchmark Spec V2

## 目标

当前 `benchmark` 更适合做参数扫描和开关 A/B：

- `variant` 主要通过 `config_patch` 表达
- 输出重点是 `best_variant` 和 `delta_from_baseline`
- 评分重点偏向结果指标，而不是方法路径

这对 `top_k`、`rerank_k`、`memory.enabled` 这类调参问题足够，但对真正的架构升级不够。

Benchmark Spec V2 的目标是把评测对象从“参数点”升级为“方法假设”，支持回答这些问题：

- 某个架构变更到底提升了哪类任务
- 提升来自哪条方法链路，而不是只看最终分数
- 这个变更是参数优化、实现优化，还是方法替换
- 多个方法模块叠加时，收益是否独立、稳定、可解释

当前仓库中的 V2 已实现能力：

- spec 顶层支持 `analysis_mode`、`report`、`scenarios`
- variant 支持 `variant_type`、`hypothesis`、`implementation_id`、`expected_signals`、`tags`、`code_patch`
- task set 支持 `scenario`、`difficulty`、`weight`，并落盘到 `task_result.json`
- benchmark 输出支持 `best_by_quality`、`best_by_stability`、`ranking_score`
- variant 输出支持 `mechanism` 和 `capability_gains`
- suite 输出支持 `best_by_quality_by_experiment`、`best_by_stability_by_experiment`
- optimizer proposal payload 会携带 benchmark V2 上下文，包括 task 场景、mechanism、capability_gains、ranking_score
- proposal command 可以直接返回 architecture-level proposal 元数据，并原样写入 candidate 的 `proposal.json`
- `observe once --auto-propose` 在没有外部 `proposal_command` 时，会基于 `architecture_recommendation` 自动生成内建的 method-family candidate
- 内建 method-family candidate 已支持按 `focus=indexing|memory|retrieval` 注入不同的默认 exploratory config patch，而不只是空壳 proposal
- 内建模板现在会按 `gap_signals` 与 `metric_thresholds` 的强度动态升级 patch，而不是始终使用同一组常量
- 内建模板现在还会参考当前 `effective_config` 和 `source_run_ids` 对应的历史 best run，避免重复探索已经处于当前配置或已知最佳配置的同一档位

## 边界

`benchmark` 与 `loop` 的边界需要保持清晰：

- `benchmark` 负责横向比较一组既定 variants
- `loop` 负责纵向迭代，包括经验读取、候选生成、停止条件和下一轮上下文
- `integration outer-loop` 这类上层流程可以复用 `benchmark` 结果，但不应把 benchmark engine 继续扩成通用迭代状态机

工程上如果需要将某个外层流程迁移到统一 loop 主轴，建议保留 benchmark 的输入输出 contract，只把“谁来生成下一轮候选、何时停止、如何写 iteration artifacts”迁到 loop 层。

仍然留在后续演进范围内的内容：

- 更复杂的 mechanism evaluator 注册体系
- 跨多项目统一的 architecture-level proposal 生成
- 更丰富的 scenario 权重学习和长期趋势分析

---

## V1 的局限

V1 的核心问题不是功能不足，而是分析粒度不对。

### 1. 变更对象偏参数

当前 `variant` 基本是：

- baseline
- 改一个数值
- 关一个开关

这种设计天然偏向：

- 参数扫描
- 阈值微调
- 功能开关收益判断

但不擅长表达：

- 检索方法替换
- routing 策略替换
- context packer 重写
- 索引策略变更

### 2. 结果导向强，机制解释弱

当前报告主要回答：

- 哪个 variant 分高
- 相比 baseline 差了多少

但架构分析真正需要的是：

- 方法链路是否真的走到了预期路径
- 中间阶段发生了什么变化
- 改善发生在哪一类任务上
- 是否引入新的副作用

### 3. 任务集缺少场景标签

如果任务不按能力簇分组，最终很容易只得到一个平均分，而看不出：

- 精确符号查找是否变好
- 跨文件依赖追踪是否变好
- stale memory 干扰是否减少
- 长上下文打包是否更稳

---

## 设计原则

1. 把比较单位从参数点升级为方法假设
2. 把评测结果从“选冠军”升级为“解释设计”
3. 把结果指标和过程指标同时纳入报告
4. 把任务集按能力场景组织，而不是只按单次运行组织
5. 把参数级、实现级、架构级变更放进同一套运行协议

---

## 新概念

### 1. Variant Type

V2 中每个 variant 需要声明自己是哪一类变更：

- `parameter`: 纯参数变化
- `feature_toggle`: 功能开关变化
- `implementation_patch`: 通过代码补丁替换实现
- `method_family`: 切换到另一种方法族
- `composite`: 组合多个方法变更

这个字段的作用不是装饰，而是帮助后续报告区分：

- 这是调参收益
- 这是方法替换收益
- 这是叠加收益

### 2. Capability Scenario

每个 benchmark task 应该带场景标签，例如：

- `exact_symbol_lookup`
- `cross_file_dependency_trace`
- `memory_staleness_resistance`
- `long_context_packing`
- `index_freshness_sensitive`

后续报告按场景聚合，而不是只按 run 聚合。

### 3. Probe Signal

Probe signal 是方法链路上的中介指标，不直接代表最终好坏，但用于解释“为什么”。

示例：

- `retrieval.query_decomposition_used`
- `retrieval.candidate_pool_size`
- `retrieval.rerank_pruned_ratio`
- `memory.routing_path`
- `memory.stale_filtered_count`
- `context.pack_truncation_ratio`
- `indexing.snapshot_age_seconds`

### 4. Execution Fingerprint

Execution fingerprint 是一次 run 内部实际走过的策略路径摘要，用于区分“配置声明”与“运行事实”。

示例：

- `retrieval.strategy = "decompose_then_merge"`
- `memory.routing_mode = "freshness-biased"`
- `indexing.update_mode = "incremental"`
- `context.packer = "hierarchical"`

---

## Spec V2 结构

建议在现有 JSON 基础上扩展，而不是推翻重写。

### 顶层结构

```json
{
  "experiment": "method_comparison_demo",
  "baseline": "baseline_v1",
  "analysis_mode": "architecture",
  "report": {
    "group_by": ["scenario", "variant_type"],
    "primary_axes": ["quality", "mechanism", "stability"]
  },
  "scenarios": [
    {
      "id": "exact_symbol_lookup",
      "label": "Exact Symbol Lookup",
      "weight": 1.0
    },
    {
      "id": "memory_staleness_resistance",
      "label": "Memory Staleness Resistance",
      "weight": 1.2
    }
  ],
  "variants": []
}
```

### variant 结构

```json
{
  "name": "freshness_routing_v2",
  "variant_type": "method_family",
  "hypothesis": "freshness-biased routing reduces stale-memory interference on memory-sensitive tasks",
  "config_patch": {
    "memory": {
      "routing_mode": "freshness-biased",
      "freshness_bias": 0.8
    }
  },
  "code_patch": "patches/freshness-routing-v2.patch",
  "implementation_id": "memory-routing/freshness-v2",
  "expected_signals": {
    "fingerprints": {
      "memory.routing_mode": "freshness-biased"
    },
    "probes": {
      "memory.stale_filtered_count": {
        "min": 1
      }
    }
  }
}
```

---

## 字段定义

### 顶层字段

- `experiment`: 实验名
- `baseline`: 基准 variant 名
- `analysis_mode`: `parameter` 或 `architecture`
- `scenarios`: 场景定义列表
- `report`: 报告聚合偏好
- `variants`: 待比较变体

### variant 字段

- `name`: variant 名称
- `variant_type`: 变更类型
- `hypothesis`: 该变更试图验证的假设
- `config_patch`: 配置变更
- `code_patch`: 代码补丁路径
- `implementation_id`: 方法实现标识
- `expected_signals`: 预期出现的 fingerprint / probe
- `tags`: 可选标签，如 `["retrieval", "method-change"]`

### expected_signals

这个字段是 V2 的关键之一。它不是用于阻塞运行，而是用于验证：

- 方法是否真的被执行
- 变更是否只停留在配置上

如果一个 variant 声称切换到了新 routing，但 fingerprint 里没有体现，就说明实验本身不成立。

---

## Task Set V2 扩展

现有 task set 只有 task/phases/workdir，还缺场景语义。建议扩展为：

```json
{
  "tasks": [
    {
      "task_id": "memory-stale-case-01",
      "scenario": "memory_staleness_resistance",
      "difficulty": "medium",
      "weight": 1.2,
      "workdir": "${workspace_dir}",
      "phases": []
    }
  ]
}
```

新增字段建议：

- `scenario`: 场景 id
- `difficulty`: `easy|medium|hard`
- `weight`: 任务权重
- `expectations`: 该任务需要命中的关键机制，可选

这样 benchmark 汇总时才能回答：

- 这个方法在哪类场景上提升最大
- 提升是否只发生在某些任务簇

---

## Run Context V2

当前 `run_context` 更像健康摘要。V2 要把它扩展成“可解释运行上下文”。

建议新增三层：

### 1. Fingerprints

记录实际执行的策略指纹。

```json
{
  "fingerprints": {
    "retrieval.strategy": "decompose_then_merge",
    "memory.routing_mode": "freshness-biased",
    "indexing.update_mode": "incremental",
    "context.packer": "hierarchical"
  }
}
```

### 2. Probes

记录中介指标。

```json
{
  "probes": {
    "retrieval.query_decomposition_used": true,
    "retrieval.candidate_pool_size": 48,
    "retrieval.rerank_pruned_ratio": 0.58,
    "memory.stale_filtered_count": 3,
    "context.pack_truncation_ratio": 0.14
  }
}
```

### 3. Validation

记录该 variant 的方法假设是否被运行事实支持。

```json
{
  "validation": {
    "expected_signals_satisfied": true,
    "missing_signals": [],
    "mismatch_signals": []
  }
}
```

---

## Evaluator V2

V2 仍然复用现有 `basic + command evaluator` 机制，但 command evaluator 要拆出两类职责。

### 0. Lightweight Validation Gate

在进入完整 benchmark 之前，loop 可以先执行一层 lightweight validation gate。

目的：

- 快速排除明显不可执行或明显退化的 candidate
- 让 expensive benchmark 只消耗在通过基础校验的候选上
- 为 selection / stopping 保留一份独立的 pre-benchmark validation artifact

建议最小输入：

```json
{
  "validation_command": ["python", "-m", "pytest", "-q", "tests/test_smoke.py"],
  "validation_workdir": "."
}
```

最小输出：

```json
{
  "status": "passed",
  "reason": "",
  "validation_artifact": {
    "kind": "lightweight",
    "status": "passed",
    "command": ["python", "-m", "pytest", "-q", "tests/test_smoke.py"],
    "workdir": ".",
    "exit_code": 0
  }
}
```

若 `status != passed`，loop 应 short-circuit 当前 benchmark，并返回 `benchmark_skipped=true`。

### 1. Outcome Evaluator

继续负责最终结果指标：

- correctness
- maintainability
- architecture
- retrieval
- composite_adjustment

### 2. Mechanism Evaluator

新增机制分析脚本，专门读取 task artifacts / logs / workspace 输出，生成：

- fingerprints
- probes
- validation

这样最后的 `score_report.json` 或并行报告中，会同时拥有：

- 最终结果
- 方法执行证据
- 设计假设校验

---

## 报告模型

V2 的输出不应该只包含 `best_variant`。

建议新增三个维度的报告：

### 1. Quality

仍然保留：

- `composite`
- `delta_from_baseline`
- 各 section metric delta

### 2. Mechanism

新增：

- 是否命中预期方法路径
- probe 信号是否符合假设
- 哪些机制指标发生显著变化

### 3. Stability

新增：

- 同场景方差
- 多任务一致性
- 是否只在少数任务上偶然变好

最终报告建议长成这样：

```json
{
  "experiment": "method_comparison_demo",
  "baseline": "baseline_v1",
  "best_by_quality": "freshness_routing_v2",
  "best_by_stability": "baseline_v1",
  "variants": [
    {
      "name": "freshness_routing_v2",
      "variant_type": "method_family",
      "hypothesis": "reduce stale memory interference",
      "quality": {},
      "mechanism": {
        "expected_signals_satisfied": true,
        "changed_fingerprints": [
          "memory.routing_mode"
        ],
        "key_probe_deltas": {
          "memory.stale_filtered_count": 2
        }
      },
      "capability_gains": {
        "memory_staleness_resistance": {
          "composite_delta": 1.8
        }
      },
      "stability": {
        "scenario_consistency": 0.82
      }
    }
  ]
}
```

---

## 分析范式

### 参数分析

适合：

- `top_k`
- `rerank_k`
- `chunk_size`
- `budget.max_turns`

输出重点：

- 最佳数值区间
- 基线增益

### 架构分析

适合：

- 方法替换
- routing 重构
- packer 重构
- indexing 策略切换

输出重点：

- 假设是否成立
- 提升在哪类场景
- 提升通过什么机制发生
- 有哪些副作用

---

## 对当前仓库的最小落地方案

不建议一次性大改。建议按下面顺序推进。

### Phase 1

先扩 spec，不改主循环语义：

- `variant_type`
- `hypothesis`
- `implementation_id`
- `expected_signals`
- task 的 `scenario`

这一步主要改：

- `src/meta_harness/benchmark.py`
- task set JSON 解析逻辑
- benchmark 输出 JSON schema

### Phase 2

扩 run context：

- 在 `optimizer_workflow.py` 里增加 fingerprints/probes/validation
- 让任务侧 probe 输出结构化方法信号

这一步主要改：

- `src/meta_harness/optimizer_workflow.py`
- task-specific probe / evaluator 脚本

### Phase 3

扩报告：

- 增加 scenario 维度聚合
- 增加 mechanism/stability 维度
- 区分 `best_by_quality` 和 `best_by_stability`

这一步主要改：

- `src/meta_harness/benchmark.py`
- CLI 输出协议
- 对应测试

### Phase 4

再把 proposal 接到方法分析：

- proposal 不再只输出 config headroom
- 可以输出“建议尝试的新方法族”
- 支持 architecture-level candidate 生成

---

## 与通用方法评测的对应关系

V2 更适合表达“方法族比较”，而不只是继续做单一参数 sweep。优先提升成方法级 variant 的对象通常包括：

- `memory routing`: baseline vs freshness-biased vs strict-pruning
- `retrieval strategy`: direct retrieval vs query decomposition
- `indexing strategy`: full rebuild vs incremental freshness-aware update
- `context packing`: flat packing vs hierarchical packing

然后为每类方法补配：

- capability scenario
- mechanism probes
- expected fingerprints

这样最后得到的就不是“哪个参数更大更好”，而是：

- 哪种方法更适合哪类问题
- 哪种方法值得进入默认架构

---

## 一句话结论

Benchmark Spec V2 的核心不是加更多字段，而是把平台从“调参系统”升级为“设计实验系统”：

- `variant` 表达方法假设
- `task` 表达能力场景
- `run_context` 表达执行机制
- `report` 表达设计结论

这才是能够分析架构变革的方法。
