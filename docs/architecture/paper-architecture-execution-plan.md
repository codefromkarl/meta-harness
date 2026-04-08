# Meta-Harness 论文架构收口执行计划

更新时间：2026-04-08

## 1. 目标

本计划用于把当前仓库从“已经具备论文最小闭环”推进到“论文导向架构基本收口”的状态。

计划聚焦以下目标：

- 强化统一 `search loop` 主轴
- 提升 `experience -> propose -> evaluate -> select -> write-back` 闭环质量
- 收敛 integration outer-loop 与通用 loop 的重复编排
- 为后续执行提供可分批推进的任务清单、验收标准与验证路径

本计划默认作为后续实现会话的执行依据。

## 2. 范围

### 2.1 纳入本计划

- `loop/` 主循环能力强化
- `task_plugins/` 任务语义适配层强化
- `proposers/` 提案质量与排序能力强化
- loop 级经验装配与经验写回
- integration outer-loop 对统一 loop 的收口
- 与上述能力直接相关的测试、文档和 artifact contract

### 2.2 不纳入本计划

- UI
- 多租户 / workspace 权限模型
- 数据库 projection / migration
- 分布式 job queue / worker
- Phoenix / Langfuse / OTLP 的完整产品化接入

这些内容保留在平台产品化路线中，不作为“论文架构收口”的阻塞项。

## 3. 当前判断

当前仓库已经具备：

- artifact-first 的 `candidate -> run -> score -> benchmark -> propose -> shadow-run` 闭环
- 统一 `run_search_loop()` 主循环
- `selection` / `stopping` 策略基础实现
- `task plugin` 与 `proposer` 注册机制
- `optimize loop` 的 CLI / service 接入
- integration harness outer-loop 对统一 loop 的局部复用

当前主要差距：

- `experience assembler` 仍偏浅，历史经验筛选和摘要不足
- proposal 生成已抽象，但 proposal ranking / evaluation 尚未并入统一主流程
- task plugin 仍更接近轻量包装，而非强语义适配层
- integration outer-loop 仍保留较多场景专用编排
- “经验写回”尚未形成稳定的下一轮输入飞轮

## 4. 完成定义

满足以下条件即可认为“论文架构收口”完成：

1. `run_search_loop()` 可消费经过筛选和摘要的历史经验，而非原始 run 列表堆叠。
2. proposal 不仅能生成，还能排序、记录理由并形成可审计的 proposal evaluation artifact。
3. 不同任务类型的差异主要体现在 task plugin，而非散落在 service 层。
4. integration outer-loop 的通用逻辑回收到统一 loop 主轴，场景层只负责 request 和 plugin 装配。
5. loop 迭代结果会产出可复用经验摘要，并能直接进入下一轮优化输入。
6. 相关 contract 和核心路径具备自动化测试，公开 demo / smoke 路径不被破坏。

## 5. 执行原则

- 每个阶段都先补测试，再补实现，再跑验证。
- 优先收口主循环，不做并行扩面。
- 每批任务以 2 到 4 个子任务为上限，批次结束后回看结果再继续。
- 若某子任务需要显著改变 schema 或 artifact 结构，必须先更新文档 contract。
- 若实现过程中发现当前抽象显著阻碍推进，应停下来修订计划，而不是强行贴补丁。

## 6. 分阶段任务

## Phase 1：Experience Assembler 强化

目标：把 loop 输入从“历史记录列表”升级为“可直接被 proposer 消费的精选经验包”。

### Task 1.1：增加经验筛选策略

- [x] 在 `loop/experience.py` 中增加可配置的历史筛选策略
- [x] 至少支持：最近 N 轮、最佳 K 轮、失败家族去重、按 focus 过滤
- [x] 对外暴露稳定参数，而不是把策略散在 plugin 内部

目标文件：

- `src/meta_harness/loop/experience.py`
- `src/meta_harness/loop/schemas.py`
- `tests/test_loop_runtime.py`

验收标准：

- experience payload 中的 `matching_runs` 不再是简单按 profile/project 全量截断
- 能用测试覆盖不同筛选策略输出

验证：

- `pytest -q tests/test_loop_runtime.py`

### Task 1.2：补齐代表性经验摘要

- [x] 在 experience payload 中增加代表性失败、代表性成功、能力缺口、代表性 trace/stdout/stderr refs
- [x] 摘要结构稳定，便于 proposer 直接读取
- [x] 明确区分原始历史与摘要视图

目标文件：

- `src/meta_harness/loop/experience.py`
- `src/meta_harness/loop/schemas.py`
- `tests/test_loop_runtime.py`

验收标准：

- experience payload 能直接表达“为什么下一轮值得优化”
- proposer 不需要自行重新遍历全部 run artifact 才能得到核心信号

验证：

- `pytest -q tests/test_loop_runtime.py`

### Task 1.3：增加经验写回摘要

- [x] 为每轮 loop 生成稳定的 next-round experience summary artifact
- [x] 约定该 artifact 与 iteration artifact 的关系
- [x] 让下一轮可直接消费上一轮摘要，而不是重新从原始 run 扫全量

目标文件：

- `src/meta_harness/loop/search_loop.py`
- `src/meta_harness/loop/iteration_store.py`
- `docs/reference/artifact-contracts.md`
- `tests/test_loop_runtime.py`

验收标准：

- `reports/loops/<loop_id>/` 下新增稳定经验摘要文件
- loop 下一轮输入可引用该摘要

验证：

- `pytest -q tests/test_loop_runtime.py tests/test_schema_contracts.py`

## Phase 2：Task Plugin 语义化

目标：让 task plugin 从“格式适配器”升级为“任务语义适配器”。

### Task 2.1：扩展 task plugin 协议

- [x] 增加经验筛选、proposal 约束、停止条件覆写等可选协议
- [x] 保持默认 plugin 兼容，避免一次性破坏现有实现

目标文件：

- `src/meta_harness/task_plugins/base.py`
- `src/meta_harness/loop/search_loop.py`
- `tests/test_loop_runtime.py`

验收标准：

- plugin 可以参与决定经验范围和 loop policy
- 未实现新钩子的 plugin 不会崩溃

验证：

- `pytest -q tests/test_loop_runtime.py tests/test_task_plugins.py`

### Task 2.2：至少强化两个现有 plugin

- [x] 选 `web_scrape` 和 `code_repair` 或等价两个 plugin，补任务专有经验筛选与迭代总结
- [x] 让 plugin 输出真正可驱动 proposer 的任务语义上下文

目标文件：

- `src/meta_harness/task_plugins/web_scrape.py`
- `src/meta_harness/task_plugins/code_repair.py`
- `tests/test_task_plugins.py`

验收标准：

- plugin 输出不再只是 task_set 摘要
- 针对不同任务类型，experience / evaluation plan / iteration summary 有可观差异

验证：

- `pytest -q tests/test_task_plugins.py tests/test_loop_runtime.py`

## Phase 3：Proposal / Proposer 收口

目标：让 proposal 成为可排序、可审计、可回顾的统一对象。

### Task 3.1：把 proposal ranking 接入主循环

- [x] 支持多 proposer 产出 proposal
- [x] 把 `rank_proposals()` 接入 loop，而不是只做独立工具函数
- [x] 明确 ranking 输入字段和 fallback 逻辑

目标文件：

- `src/meta_harness/proposers/registry.py`
- `src/meta_harness/loop/search_loop.py`
- `tests/test_proposers_registry.py`
- `tests/test_loop_runtime.py`

验收标准：

- loop 至少支持“多 proposal -> 排序 -> 选择最佳 proposal -> 物化”
- 单 proposer 模式保持兼容

验证：

- `pytest -q tests/test_proposers_registry.py tests/test_loop_runtime.py`

### Task 3.2：增加 proposal evaluation artifact

- [x] 为 proposal 增加评价 artifact，记录来源经验、排序结果、采纳原因、淘汰原因
- [x] 把 evaluation artifact 纳入 proposal 生命周期

目标文件：

- `src/meta_harness/proposals.py`
- `src/meta_harness/services/optimize_service.py`
- `docs/reference/artifact-contracts.md`
- `tests/test_cli_optimize.py`
- `tests/test_schema_contracts.py`

验收标准：

- proposal 不再只有 `proposal.json`
- 可以回看某 proposal 为什么被采纳或未采纳

验证：

- `pytest -q tests/test_cli_optimize.py tests/test_schema_contracts.py`

### Task 3.3：增强 LLM proposer 的结构化约束

- [x] 增加允许修改范围、预算边界、失败模式优先级、禁改项等结构化约束
- [x] 在 prompt payload 中保持稳定字段命名

目标文件：

- `src/meta_harness/proposers/llm_harness_proposer.py`
- `tests/test_proposers_registry.py`

验收标准：

- LLM proposer 的输入不再只有 objective/experience 粗摘要
- 约束字段可以在测试中直接断言

验证：

- `pytest -q tests/test_proposers_registry.py`

## Phase 4：统一主循环收口

目标：减少并行 outer-loop 逻辑，把统一 search loop 变成真正的一等主轴。

### Task 4.1：抽象统一 evaluation executor

- [x] 收敛 benchmark 与 shadow-run 的分支执行逻辑
- [x] 形成统一 evaluation executor 或等价抽象

目标文件：

- `src/meta_harness/loop/search_loop.py`
- `src/meta_harness/services/benchmark_service.py`
- `src/meta_harness/optimizer_shadow.py`
- `tests/test_loop_runtime.py`

验收标准：

- loop 内不再直接散落 benchmark/shadow-run 特判
- evaluation mode 扩展成本下降

验证：

- `pytest -q tests/test_loop_runtime.py tests/test_cli_benchmark.py tests/test_runtime.py`

### Task 4.2：收敛 integration outer-loop

- [x] 把 integration outer-loop 中通用 proposal / selection / loop artifact 逻辑尽量回收到 `run_search_loop()`
- [x] integration 层保留 harness-specific request builder 和 plugin 装配

目标文件：

- `src/meta_harness/services/integration_outer_loop_service.py`
- `src/meta_harness/loop/search_loop.py`
- `tests/test_harness_loop_review.py`
- `tests/test_cli_integration.py`

验收标准：

- integration outer-loop 不再维护一套平行的 loop 状态机
- 场景层代码明显变薄

验证：

- `pytest -q tests/test_harness_loop_review.py tests/test_cli_integration.py tests/test_loop_runtime.py`

### Task 4.3：统一外围入口的 loop request 构造

- [x] CLI / API / integration 入口统一走 loop request builder
- [x] 避免入口层偷偷内嵌策略逻辑

目标文件：

- `src/meta_harness/services/optimize_loop_service.py`
- `src/meta_harness/cli_optimize_loop.py`
- `src/meta_harness/api/routes_execution_ops.py`
- `tests/test_cli_optimize.py`
- `tests/test_api.py`

验收标准：

- 三类入口的 loop 相关参数模型对齐
- 行为差异主要来自 request 内容而非入口实现分叉

验证：

- `pytest -q tests/test_cli_optimize.py tests/test_api.py tests/test_services.py`

## Phase 5：Contract / Demo / Smoke 收尾

目标：为“论文架构收口完成”提供可验证证据。

### Task 5.1：增加 artifact contract validator

- [ ] 提供面向真实 artifact 目录的 contract validator
- [ ] 能检查 loop / proposal / dataset / evaluator 关键 artifact

目标文件：

- `src/meta_harness/`
- `docs/reference/artifact-contracts.md`
- `tests/test_schema_contracts.py`

验收标准：

- 不依赖人工目检 artifact 结构
- validator 可被 smoke 路径复用

验证：

- `pytest -q tests/test_schema_contracts.py`

### Task 5.2：补公开 benchmark snapshot

- [ ] 选一条公开 demo 路径产出 benchmark 结果快照
- [ ] 在文档中给出复现方式与预期摘要

目标文件：

- `docs/guides/reproducibility.md`
- `docs/guides/open-source-release-checklist.md`
- `reports/` 或等价公开样例目录

验收标准：

- 外部读者可以对照快照理解 loop 是否产生改进

### Task 5.3：增加开源 smoke 路径

- [ ] 把 `demo_public`
- [ ] `optimize propose / materialize`
- [ ] `optimize loop` 最小路径纳入 smoke 验证

目标文件：

- CI workflow 文件
- `scripts/demo_public_flow.sh`
- 相关测试与文档

验收标准：

- 关键公开路径在自动化中可复现

验证：

- 以 CI 配置中的 smoke 命令为准

## 7. 建议执行批次

建议按以下批次推进，每批结束后回看并确认是否继续：

### Batch A

- Task 1.1
- Task 1.2

### Batch B

- Task 1.3
- Task 2.1
- Task 2.2

### Batch C

- Task 3.1
- Task 3.2
- Task 3.3

### Batch D

- Task 4.1
- Task 4.2
- Task 4.3

### Batch E

- Task 5.1
- Task 5.2
- Task 5.3

## 8. 风险与注意事项

- `experience` 结构一旦改动过大，plugin、proposer、integration outer-loop 都会受影响，必须先补契约测试。
- 若 proposal ranking 直接并入主循环，需谨慎保持现有单 proposer 路径兼容。
- integration outer-loop 收口阶段最容易引入“表面统一、实际双写”的坏状态，必须优先删重复逻辑。
- artifact contract 变更必须同步文档，否则后续 smoke 与对外复现会失真。

## 9. 后续执行方式

后续实现会话按以下方式进行：

1. 读取本计划文档
2. 优先执行当前批次的前 2 到 3 个任务
3. 每批次完成后先汇报验证结果，再决定是否进入下一批

推荐从 `Batch A` 开始。
