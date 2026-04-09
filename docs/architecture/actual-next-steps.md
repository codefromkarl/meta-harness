# Meta-Harness 实际待办清单

更新时间：2026-04-09

## 1. 目的

本文档只记录**经当前仓库代码和测试核对后，仍未完成的任务**。

它用于替代把历史蓝图直接当成 backlog 的做法，避免继续把已经落地的 `search loop / proposer / task plugin / integration outer-loop` 收口工作误列为后续任务。

## 2. 判断原则

- 以当前仓库代码和自动化测试为准，不以历史蓝图中的“待做”表述为准
- “已有最小实现”不等于“已经收口”
- 只有仍存在明确能力缺口或只停留在最小骨架的事项，才进入本清单

## 3. 已完成，不进入后续任务

以下能力已经在仓库中落地，不应继续作为主 backlog：

- 统一 `run_search_loop()` 主循环
- `experience assembler`、proposal ranking / evaluation
- `task plugin` 与 `proposer` 注册/接入
- `mh optimize loop` CLI / service 入口
- integration outer-loop 复用统一 loop
- `next_round_context` artifact link contract 与 loop artifact validator 对齐

对应依据：

- `src/meta_harness/loop/search_loop.py`
- `src/meta_harness/proposers/`
- `src/meta_harness/task_plugins/`
- `src/meta_harness/services/optimize_loop_service.py`
- `src/meta_harness/services/integration_outer_loop_service.py`
- `docs/architecture/paper-architecture-execution-plan.md`

## 4. P0：治理收口

### 4.1 完整 loop lineage 收口

当前状态：

- `TraceEvent` 已带 `proposal_id`、`iteration_id`、`source_artifacts`、`provenance`
- `CandidateMetadata` 仍只有 `parent_candidate_id`
- candidate canonical metadata 还不能稳定表达“由哪个 proposal / iteration 物化而来”

缺口：

- candidate 级 lineage 仍主要分散在 trace、proposal artifact 和 runtime context 中
- 无法只靠 `candidates/<candidate_id>/candidate.json` 完整追溯 loop 来源

目标文件：

- `src/meta_harness/schemas.py`
- `src/meta_harness/candidates.py`
- `docs/architecture/data-model-v1.md`
- `docs/reference/artifact-contracts.md`
- 相关测试

验收标准：

- `CandidateMetadata` 可稳定表达 proposal / iteration / source artifacts lineage
- 不依赖扫 trace，也能从 candidate artifact 直接追溯 loop 来源
- contract 文档与测试同步更新

### 4.2 自动 shadow validation 策略

当前状态：

- `shadow_run_candidate()` 已存在
- 自动触发目前只出现在特定 `observation_service` 分支，不是统一策略

缺口：

- 没有统一的自动 shadow validation policy / executor
- loop / observe / promote 之间没有共享的自动 shadow validation 规则

目标文件：

- `src/meta_harness/services/observation_service.py`
- `src/meta_harness/loop/search_loop.py`
- `src/meta_harness/services/gate_service.py`
- `src/meta_harness/services/gate_policy_service.py`
- 相关测试与文档

验收标准：

- 自动 shadow validation 变成显式策略，而不是散落的特判
- 可配置触发条件、失败行为和 artifact 输出
- loop / observation / promotion 至少两类入口复用同一策略

### 4.3 多维评分与选择策略升级

当前状态：

- 已有 `best_by_score`、`best_by_stability`、`baseline_guardrail`、`multi_objective_rank`
- `multi_objective_rank` 仍是简单加权，不是 Pareto 聚合或更强的多目标选择

缺口：

- 多目标 trade-off 仍然较弱
- selection 与 reporting 还不能充分表达“为何保留这个候选而不是另一个候选”

目标文件：

- `src/meta_harness/loop/selection.py`
- `src/meta_harness/scoring.py`
- `docs/architecture/platform-design.md`
- `docs/reference/artifact-contracts.md`
- 相关测试

验收标准：

- 至少补一版可解释的多目标选择策略
- selection artifact 能解释 score / stability / cost 等维度取舍
- 文档不再把当前简单加权误写成最终形态

## 5. P1：外部集成加固

### 5.1 OTLP transport 真正发送路径

当前状态：

- 已支持 `otel-json` 导出
- 已支持基于 integration config 的 HTTP POST + timeout/retry

缺口：

- 仍缺批量、协议对齐、治理和更稳的 transport 能力
- 当前更接近“通用 JSON HTTP export”，不是完整 OTLP transport

目标文件：

- `src/meta_harness/exporters.py`
- `src/meta_harness/services/export_service.py`
- `src/meta_harness/services/integration_catalog_service.py`
- 集成配置、测试与文档

### 5.2 Phoenix SDK / API 接入

当前状态：

- 已支持 `phoenix-json` 导出
- 已支持命名 integration 的 HTTP export

缺口：

- 仍未形成 Phoenix 产品级接入路径
- 当前只是 JSON payload export，不是正式 SDK / API 集成

### 5.3 Langfuse SDK / API 接入

当前状态：

- 已支持 `langfuse-json` 导出
- 已支持命名 integration 的 HTTP export

缺口：

- 仍未形成 Langfuse 产品级接入路径
- 当前只是 JSON payload export，不是正式 SDK / API 集成

## 6. P2：平台产品化

### 6.1 auth / workspace 权限模型

当前状态：

- API 只有单一 Bearer Token 中间件

缺口：

- 无 workspace 级权限模型
- 无多用户/多项目隔离语义

目标文件：

- `src/meta_harness/api/app.py`
- API contracts / docs
- service 层权限上下文

### 6.2 真正的 job queue / worker

当前状态：

- 已有 job record、retry API、job facade
- 实际执行仍走 `execute_inline_job()`，本质是单机同步执行

缺口：

- 无独立 worker
- 无真正的后台队列调度
- 长任务治理仍停留在 inline facade

目标文件：

- `src/meta_harness/services/service_execution.py`
- `src/meta_harness/services/async_jobs.py`
- `src/meta_harness/services/job_runtime_service.py`
- `src/meta_harness/services/job_service.py`
- API / 文档 / 测试

### 6.3 DB projection 与 migration

当前状态：

- 文档中已有 database-first 之外的 projection 约束
- 代码中尚无实际 DB projection / migration 实现

缺口：

- 缺索引/查询加速层
- 缺 projection 过程与 schema migration

### 6.4 UI / dashboard

当前状态：

- 仓库内没有实际 frontend 资产

缺口：

- Runs / Benchmarks / Datasets / Candidates / Gate Policies 没有 UI

## 7. 不再作为独立待办的事项

以下事项已经有实现，不再单列：

- `search loop` 主循环
- proposer 抽象
- task plugin 基础层
- integration outer-loop 收口
- proposal artifact 生命周期
- lightweight validation gate

如果后续仍要改动这些区域，应以“治理增强”或“产品化对接”的名义进入 backlog，而不是回到“从零补主循环”。

## 8. 推荐执行顺序

1. P0.1 `loop lineage`
2. P0.2 自动 `shadow validation`
3. P0.3 多维评分与选择策略
4. P1.1-P1.3 外部 observability transport 加固
5. P2.1 auth / workspace 权限
6. P2.2 job queue / worker
7. P2.3 DB projection / migration
8. P2.4 UI / dashboard

## 9. 维护说明

- 本文档是当前有效 backlog
- 历史蓝图和收口计划继续保留，但不直接作为待办清单使用
- 若某项任务完成，应同步更新本文档和 `docs/README.md`
