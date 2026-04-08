# Meta-Harness Search Loop Blueprint

更新时间：2026-04-08

## 1. 目的

本文档将当前仓库已有能力与目标中的“统一搜索闭环 + proposer 抽象 + 轻量任务适配层”收敛为一份可执行的架构蓝图。

目标不是推翻现有 `run / candidate / score / benchmark` 底座，而是在现有 artifact-first 平台之上，补齐一个真正的一等离线优化主循环。

## 2. 适用范围

本文档覆盖：

- 离线 harness 程序搜索主循环
- proposer 与 task plugin 的职责边界
- loop 级 artifact 设计
- 现有模块到目标模块的迁移关系
- 按文件拆分的重构清单

本文档不覆盖：

- 在线 serving
- 分布式 job 调度
- 多租户 API 产品化
- Docker / E2B 等多后端沙箱抽象

## 3. 论文约束

以下边界以论文原始支持范围为准：

- 文件系统是**经验主存储**，不是排他的唯一记忆机制
- 系统定位是**离线 harness 程序搜索器**，不是普通静态代码生成器
- 论文定义的是最小闭环：`读取经验 -> 生成候选 -> 评估 -> 写回经验 -> 迭代`
- 微内核、task plugin、service 分层都属于**工程实现选择**
- 多模态、高并发 serving、复杂生产治理目前都不在论文验证范围内

适用前提：

- harness 对结果质量有显著影响
- 评估可重复、成本可控、延迟较低
- 基线尚未饱和，外壳逻辑仍有明显优化空间

## 4. 当前判断

当前仓库已经具备以下基础能力：

- `candidate` 物化与去重
- `run` 初始化、执行、评分、归档
- `steps.jsonl` / stdout / stderr 等运行轨迹落盘
- `benchmark` 的横向多变体比较
- `optimize propose` 与 `shadow-run`
- integration/harness 场景下的 outer-loop 工件写入

当前仍缺少的关键能力：

- 统一的 search loop 调度器
- 内建 proposer 抽象，而不是只依赖外部 `proposal_command`
- 面向 proposer 的经验装配层
- 独立的 selection / stopping 策略层
- 轻量、可替换的任务适配接口

## 5. 目标形态

### 4.1 架构主轴

目标架构分四层：

1. 事实源层  
   继续使用 `runs/`、`candidates/`、`reports/` 作为 canonical artifacts 和经验主存储。

2. 搜索闭环层  
   新增统一 `SearchLoopService`，负责编排 propose -> materialize -> execute -> benchmark -> select -> stop。

3. 任务适配层  
   用轻量 task plugin 或同等适配接口承接任务语义、目标装配、经验筛选和迭代总结。这一层是工程选择，不是论文要求。

4. 外围入口层  
   CLI / API / integration 只负责把外部请求转成 loop request，不再各自内嵌迭代逻辑。

### 4.2 主流程

```text
Loop Request
    |
    v
Task Plugin -> assemble_objective()
    |
    v
Experience Assembler
    |
    v
Proposer -> candidate proposal
    |
    v
Candidate Materialization
    |
    v
Lightweight Validation Gate
    |
    v
Run / Shadow Run / Benchmark
    |
    v
Selection Policy
    |
    v
Stopping Policy
    |
    +--> continue next iteration
    |
    +--> finalize best candidate
```

## 6. 目录蓝图

建议在 `src/meta_harness/` 下新增以下结构：

```text
src/meta_harness/
  loop/
    __init__.py
    schemas.py
    search_loop.py
    experience.py
    selection.py
    stopping.py
    iteration_store.py
  proposers/
    __init__.py
    base.py
    command_proposer.py
    heuristic_proposer.py
    llm_harness_proposer.py
  task_plugins/
    __init__.py
    base.py
    registry.py
    code_repair.py
    web_scrape.py
    extraction.py
    classification.py
  services/
    optimize_loop_service.py
  cli_optimize_loop.py
```

说明：

- `task_plugins/` 是工程上的轻量适配层，后续如果发现抽象成本高于收益，可以退化成 `adapters/` 或按任务场景内嵌到 loop request builder，不影响主循环成立。

## 7. 核心模块职责

### 6.1 `loop/search_loop.py`

唯一主循环入口，对应论文的最小闭环工程实现。

职责：

- 读取 loop request
- 调用 task plugin 组装目标
- 调用 experience assembler 读取历史
- 调用 proposer 生成候选
- 物化 candidate
- 在 expensive benchmark 前执行 lightweight validation gate
- 执行 benchmark 或 shadow-run
- 运行 selection / stopping
- 写 iteration artifacts
- 产出最终 loop summary

### 6.2 `loop/experience.py`

经验装配器，不负责做决策。

输入：

- `runs/`
- `candidates/`
- 最近 loop 历史
- 当前 objective

输出：

- 最近 N 轮失败上下文
- 最近 N 轮成功上下文
- 当前最佳 candidate
- 当前最佳 run
- 代表性 stdout / stderr / trace refs
- score delta / stability / capability gaps

### 6.3 `loop/selection.py`

负责选谁进入下一轮和谁成为当前最优。

建议内置策略：

- `best_by_score`
- `best_by_stability`
- `baseline_guardrail`
- `multi_objective_rank`

### 6.4 `loop/stopping.py`

负责迭代终止条件。

建议支持：

- 达到目标分数停止
- 连续 K 轮无提升停止
- 达到最大轮数停止
- 波动过大停止
- 明显退化停止

### 6.5 `loop/iteration_store.py`

负责 loop 自身的工件，不替代 `runs/` 和 `candidates/`。

建议落盘到：

```text
reports/loops/<loop_id>/
  loop.json
  iteration_history.jsonl
  iterations/<iteration_id>/
    proposal_input.json
    proposal_output.json
    selected_candidate.json
    benchmark_summary.json
    validation_summary.json
    next_round_context.json
    iteration_summary.json
```

### 6.6 `proposers/base.py`

定义 proposer 协议。平台不再关心 proposal 来自命令、LLM 还是启发式。

### 6.7 `task_plugins/base.py`

定义轻量任务适配协议。平台不再内嵌每个任务的历史筛选与目标定义逻辑。

## 8. 核心接口

### 7.1 Search Loop Request

```python
{
    "profile_name": "...",
    "project_name": "...",
    "task_set_path": "...",
    "plugin_id": "...",
    "proposer_id": "...",
    "max_iterations": 8,
    "focus": "all",
}
```

### 7.2 `TaskPlugin`

```python
class TaskPlugin(Protocol):
    plugin_id: str

    def assemble_objective(
        self,
        *,
        profile_name: str,
        project_name: str,
        task_set_path: Path,
        effective_config: dict[str, Any],
    ) -> dict[str, Any]: ...

    def assemble_experience(
        self,
        *,
        runs_root: Path,
        candidates_root: Path,
        selected_runs: list[dict[str, Any]],
        objective: dict[str, Any],
    ) -> dict[str, Any]: ...

    def build_evaluation_plan(
        self,
        *,
        objective: dict[str, Any],
        effective_config: dict[str, Any],
    ) -> dict[str, Any]: ...

    def summarize_iteration(
        self,
        *,
        benchmark_payload: dict[str, Any],
        selected_variant: dict[str, Any],
    ) -> dict[str, Any]: ...
```

### 7.3 `Proposer`

```python
class Proposer(Protocol):
    proposer_id: str

    def propose(
        self,
        *,
        objective: dict[str, Any],
        experience: dict[str, Any],
        constraints: dict[str, Any],
    ) -> dict[str, Any]:
        ...
```

建议 proposer 返回：

```python
{
    "proposal": {...},
    "config_patch": {...} | None,
    "code_patch": "..." | None,
    "candidate_source": {...} | None,
    "notes": "...",
}
```

## 9. 与现有模块的关系

### 8.1 保留为稳定原语

以下模块继续作为底座保留：

- `src/meta_harness/candidates.py`
- `src/meta_harness/runtime_execution.py`
- `src/meta_harness/runtime_workspace.py`
- `src/meta_harness/scoring.py`
- `src/meta_harness/evaluators.py`
- `src/meta_harness/benchmark_engine.py`
- `src/meta_harness/trace_store.py`
- `src/meta_harness/failure_index.py`

### 8.2 迁移后缩薄

以下模块保留兼容入口，但核心职责迁出：

- `src/meta_harness/optimizer_generation.py`
- `src/meta_harness/optimizer_context.py`
- `src/meta_harness/optimizer_shadow.py`
- `src/meta_harness/services/optimize_service.py`
- `src/meta_harness/services/integration_outer_loop_service.py`
- `src/meta_harness/cli_run_candidate_optimize.py`

### 8.3 外围入口化

以下能力保留为外围产品面，不再承载核心 loop 逻辑：

- `src/meta_harness/api/`
- `src/meta_harness/services/integration_service.py`
- `src/meta_harness/cli_profile_workflow_integration.py`
- `src/meta_harness/observation.py`
- `src/meta_harness/services/observation_service.py`

## 10. 调整后的实施顺序

### Phase 1

补齐统一主循环最小闭环，保持在论文明确支持范围内。

- 新增 `loop/search_loop.py`
- 新增 `loop/selection.py`
- 新增 `loop/stopping.py`
- 新增 `loop/iteration_store.py`
- 新增 `services/optimize_loop_service.py`
- 新增 `cli_optimize_loop.py`

### Phase 2

把“经验装配”从当前 optimizer 逻辑中抽离，强调“文件系统为主的经验存储 + 可查询经验装配”，而不是“唯一记忆”。

- 新增 `loop/experience.py`
- 将 `optimizer_context.py` 收缩为兼容层

### Phase 3

把 proposal 机制升级为统一 proposer 抽象，明确其目标是 harness 程序搜索，而不是静态代码生成。

- 新增 `proposers/base.py`
- 新增 `proposers/command_proposer.py`
- 新增 `proposers/heuristic_proposer.py`
- 新增 `proposers/llm_harness_proposer.py`
- 将 `optimizer_generation.py` 变为 facade

### Phase 4

引入轻量任务适配层。

- 新增 `task_plugins/base.py`
- 新增 `task_plugins/registry.py`
- 先落两个 plugin：`web_scrape`、`code_repair`

### Phase 5

让 integration outer-loop 复用统一主循环。

- `services/integration_outer_loop_service.py` 改为 request adapter
- `benchmark_engine.py` 保持横向比较，不再承担纵向迭代职责

优先级说明：

- Phase 1-3 直接对应论文支持的核心闭环工程化
- Phase 4-5 是工程扩展，不应反过来主导系统定位

## 11. 按文件重构清单

下表按“新增 / 修改 / 保留”给出文件级操作。

| 路径 | 动作 | 目标职责 | 备注 |
| --- | --- | --- | --- |
| `src/meta_harness/loop/__init__.py` | 新增 | 暴露 loop 公共接口 | 最小导出 `run_search_loop` |
| `src/meta_harness/loop/schemas.py` | 新增 | 定义 loop request、iteration summary、selection result、stop decision | 先只建内部 schema |
| `src/meta_harness/loop/search_loop.py` | 新增 | 主循环 orchestration | Phase 1 核心文件 |
| `src/meta_harness/loop/experience.py` | 新增 | 统一经验装配 | 吸收 `optimizer_context.py` 的主体能力 |
| `src/meta_harness/loop/selection.py` | 新增 | 选优与保底策略 | 从 benchmark 结果中做 loop 级选择 |
| `src/meta_harness/loop/stopping.py` | 新增 | 停止条件 | 支持 max iterations / no improvement |
| `src/meta_harness/loop/iteration_store.py` | 新增 | 写入 `reports/loops/` 工件 | 不替代 `runs/` 和 `candidates/` |
| `src/meta_harness/proposers/__init__.py` | 新增 | proposer 导出入口 | 保持薄封装 |
| `src/meta_harness/proposers/base.py` | 新增 | proposer 协议与公共类型 | 平台统一面向该接口 |
| `src/meta_harness/proposers/command_proposer.py` | 新增 | 外部命令 proposer | 迁移 `_run_proposal_command()` |
| `src/meta_harness/proposers/heuristic_proposer.py` | 新增 | 内建启发式 proposer | 迁移 `increase_budget_on_repeated_failures` 路径 |
| `src/meta_harness/proposers/llm_harness_proposer.py` | 新增 | 面向 harness 代码生成的 proposer | 当前为 command-backed LLM prompt adapter，可继续扩成直接模型接入 |
| `src/meta_harness/task_plugins/__init__.py` | 新增 | plugin 导出入口 | 保持薄封装 |
| `src/meta_harness/task_plugins/base.py` | 新增 | task plugin 协议 | 平台与任务语义解耦的关键 |
| `src/meta_harness/task_plugins/registry.py` | 新增 | plugin 注册与查找 | 与现有 registry 分开，避免过早耦合 |
| `src/meta_harness/task_plugins/web_scrape.py` | 新增 | web scrape 任务目标与经验装配 | 第一批优先落地 |
| `src/meta_harness/task_plugins/code_repair.py` | 新增 | code repair 任务目标与经验装配 | 第一批优先落地 |
| `src/meta_harness/task_plugins/extraction.py` | 新增 | extraction 任务插件 | 后续插件 |
| `src/meta_harness/task_plugins/classification.py` | 新增 | classification 任务插件 | 后续插件 |
| `src/meta_harness/services/optimize_loop_service.py` | 新增 | service 层 loop 请求入口 | CLI / API 共用 |
| `src/meta_harness/cli_optimize_loop.py` | 新增 | `mh optimize loop` 命令 | 只做参数转发与输出 |
| `src/meta_harness/optimizer_context.py` | 修改 | 兼容层 | 主体逻辑迁到 `loop/experience.py` |
| `src/meta_harness/optimizer_generation.py` | 修改 | facade + 向后兼容 | proposal 逻辑迁到 `proposers/` |
| `src/meta_harness/optimizer_shadow.py` | 修改 | 作为 loop 内原语 | 保留 `shadow_run_candidate()` |
| `src/meta_harness/optimizer.py` | 修改 | 兼容导出 | 对外继续导出旧名称 |
| `src/meta_harness/services/optimize_service.py` | 修改 | 兼容旧 API | 内部改调 `optimize_loop_service.py` |
| `src/meta_harness/services/integration_outer_loop_service.py` | 修改 | integration request adapter | 不再自己组织完整迭代状态机 |
| `src/meta_harness/cli_run_candidate_optimize.py` | 修改 | 保留旧命令并新增 loop 入口 | 旧 propose/shadow-run 不删 |
| `src/meta_harness/cli.py` | 修改 | 注册新的 optimize loop CLI | 仅路由变更 |
| `src/meta_harness/benchmark_engine.py` | 修改 | 保持 benchmark 原语 | 明确不承担 loop 状态机 |
| `src/meta_harness/benchmark_helpers.py` | 修改 | 抽出可复用 selection 输入 | 只补帮助函数，不扩语义 |
| `src/meta_harness/candidates.py` | 修改 | 支持 loop lineage / source artifacts | 不改变现有 canonical contract |
| `src/meta_harness/scoring.py` | 保留 | 聚合 evaluator 结果 | 保持稳定原语 |
| `src/meta_harness/evaluators.py` | 保留 | evaluator registry | 后续再考虑 task-aware 封装 |
| `src/meta_harness/runtime_execution.py` | 保留 | run 执行原语 | loop 直接复用 |
| `src/meta_harness/runtime_workspace.py` | 保留 | workspace 物化原语 | loop 直接复用 |
| `src/meta_harness/failure_index.py` | 修改 | 扩成经验检索辅件 | 先保持 failure signature 兼容 |
| `src/meta_harness/observation.py` | 修改 | 只做 observe，不再承载 optimize 主循环 | 减少职责漂移 |
| `src/meta_harness/services/observation_service.py` | 修改 | observe 结果可转 loop request | 不直接替代 loop |
| `src/meta_harness/api/routes_execution_ops.py` | 可选修改 | 后续暴露 loop API | Phase 1 不阻塞 |
| `tests/test_cli_optimize.py` | 修改 | 覆盖新 `mh optimize loop` 入口 | 旧命令测试保留 |
| `tests/test_services.py` | 修改 | 增加 loop service 覆盖 | integration outer-loop 用例需调整 |
| `tests/test_runtime.py` | 保留 | 继续验证底层执行闭环 | 无需重写 |
| `tests/test_schema_contracts.py` | 修改 | 增加 loop schemas contract 测试 | 确认 request/result 兼容性 |
| `tests/test_cli_integration.py` | 修改 | integration outer-loop 改为 loop adapter 断言 | 关注入口行为而不是内部实现 |
| `docs/architecture/platform-design.md` | 可选修改 | 后续吸纳本蓝图的稳定部分 | 当前先以本文为增量设计 |
| `docs/reference/artifact-contracts.md` | 可选修改 | 后续补 `reports/loops/` contract | 当前先不改 canonical contract |

## 12. 第一批最小交付

如果只做一轮最小可用改造，建议第一批只交付以下内容：

- `loop/search_loop.py`
- `loop/selection.py`
- `loop/stopping.py`
- `loop/iteration_store.py`
- `services/optimize_loop_service.py`
- `cli_optimize_loop.py`
- `proposers/base.py`
- `proposers/command_proposer.py`
- `proposers/heuristic_proposer.py`
- `tests/test_cli_optimize.py` 中新增 loop happy path
- `tests/test_services.py` 中新增 loop service happy path

这一批完成后，仓库就会从“有 propose/shadow-run 原语的平台”变成“具备统一离线 optimize loop 入口的平台”。

## 13. 成功标准

完成上述重构后，至少应满足：

- 存在统一命令：`mh optimize loop`
- loop 输出独立的 iteration artifacts
- integration outer-loop 可复用统一 loop service
- proposer 不再只是一段散落在 optimizer 中的逻辑
- benchmark 与 loop 的职责边界清晰
- 旧命令仍然可用，但退化为兼容入口
- 文档表述不再把工程架构选择误写成论文主张
