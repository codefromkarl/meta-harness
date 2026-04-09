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
- 自动 `shadow validation policy` 已统一接入 loop shadow-run 与 observation auto-shadow
- `selection_rationale` 与 Pareto-frontier + bottleneck 的多目标选择 v1 已落地
- OTLP transport request envelope 与规范化 `/v1/traces` export path 已落地

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
- `CandidateMetadata` 已带 `proposal_id`、`source_proposal_ids`、`iteration_id`、`source_iteration_ids`、`source_run_ids`、`source_artifacts`
- `CandidateMetadata` 现在会同步输出 canonical `lineage` envelope，保持与扁平 lineage 字段对齐
- loop / proposal / candidate 之间的基础 lineage 已能落到 `candidate.json`，并有 contract 测试覆盖
- catalog / API 的 current candidate view 已开始直接投影 canonical `lineage`
- export trace payload 现在也会直接投影 canonical `lineage`：`otel-json` resource、`phoenix-json` trace metadata、`langfuse-json` trace metadata 均已带稳定 lineage 字段，并有导出路径测试覆盖

缺口：

- canonical `lineage` envelope 已建立，且 contract 文档已明确 `lineage-first` 治理语义；剩余问题不再是是否以 `lineage` 为主，而是兼容字段 surface 还要保留到什么程度
- 当前 contract 已覆盖 selected candidate 对同 iteration 核心工件与 selected run 的引用，export 层也已补齐最小稳定投影；剩余缺口主要收敛到 compaction / archive / integration artifact 的一致治理语义，以及是否继续压缩对外 surface

目标文件：

- `src/meta_harness/schemas.py`
- `src/meta_harness/candidates.py`
- `docs/architecture/data-model-v1.md`
- `docs/reference/artifact-contracts.md`
- 相关测试

验收标准：

- `CandidateMetadata` 可稳定通过 canonical `lineage` envelope 表达 proposal / iteration / source proposal / source run / source artifacts lineage
- 不依赖扫 trace，也能从 candidate artifact 直接追溯 loop 来源与关联 run
- contract 文档与测试同步更新，并保证 `lineage` 与兼容字段一致

## 5. P1：外部集成加固

### 5.2 Phoenix SDK / API 接入

当前状态：

- 已支持 `phoenix-json` 导出
- 已支持命名 integration 的 HTTP export
- 已补 `phoenix_api_request` request envelope，并会随 integration export artifact 一起落盘
- 已有 service / API 路径测试覆盖 Phoenix 产品面请求与 artifact 保留

缺口：

- 仍未形成 Phoenix 官方 SDK / hosted API 级接入路径
- 当前已是“产品面 request envelope + artifact 保留”，但仍不是正式 SDK / API 集成

### 5.3 Langfuse SDK / API 接入

当前状态：

- 已支持 `langfuse-json` 导出
- 已支持命名 integration 的 HTTP export
- 已补 `langfuse_api_request` request envelope，并会随 integration export artifact 一起落盘
- 已有 service / API 路径测试覆盖 Langfuse 产品面请求与 artifact 保留

缺口：

- 仍未形成 Langfuse 官方 SDK / hosted API 级接入路径
- 当前已是“产品面 request envelope + artifact 保留”，但仍不是正式 SDK / API 集成

## 6. P2：平台产品化

### 6.1 auth / workspace 权限模型

当前状态：

- API 已有 Bearer Token 中间件
- 已补 `WorkspaceAuthContext`，并支持基于 header 的最小 workspace 约束
- API contract 已开始显式携带 `workspace_id`

缺口：

- 仍缺完整 workspace 级权限模型
- 仍缺多 workspace / 多用户 / 多项目隔离语义

目标文件：

- `src/meta_harness/api/app.py`
- API contracts / docs
- service 层权限上下文

### 6.2 真正的 job queue / worker

当前状态：

- 已有 job record、retry API、job facade
- 已补 `execution_mode=queued|inline`
- 已补最小 worker runtime 路径 `process_pending_jobs()`
- inline 执行仍是主路径，queued worker 仍是最小骨架

缺口：

- 仍缺独立常驻 worker
- 仍缺真正的后台队列调度 / lease / recovery 机制
- 长任务治理仍未脱离当前最小 worker 骨架

目标文件：

- `src/meta_harness/services/service_execution.py`
- `src/meta_harness/services/async_jobs.py`
- `src/meta_harness/services/job_runtime_service.py`
- `src/meta_harness/services/job_service.py`
- API / 文档 / 测试

### 6.3 DB projection 与 migration

当前状态：

- 文档中已有 database-first 之外的 projection 约束
- 代码中已补一版最小 SQLite projection store 与 migration 入口
- 当前 projection 已支持 `ensure/upsert/load/list` 最小闭环与对应测试

缺口：

- 缺索引/查询加速层
- 缺面向 run / candidate / job 的系统性 projection 过程与主要查询路径接入

### 6.4 UI / dashboard

当前状态：

- 已有内嵌在 API 内的 dashboard shell
- 当前已覆盖 Runs、Benchmarks、Current Candidates、Datasets、Gate Policies、Jobs、Proposals、Trace Exports 面板
- 已补 current candidate 的最小 lineage 摘要展示

缺口：

- 仍缺更细粒度 lineage 卡片
- 仍缺 trace / export 的更深层 drill-down
- 仍缺独立前端资产与更完整的产品化交互

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

1. P0.1 `loop lineage` 剩余治理尾项
2. P1.2 Phoenix SDK / API 接入
3. P1.3 Langfuse SDK / API 接入
4. P2.1 auth / workspace 权限
5. P2.2 job queue / worker
6. P2.3 DB projection / migration
7. P2.4 UI / dashboard

## 9. 维护说明

- 本文档是当前有效 backlog
- 历史蓝图和收口计划继续保留，但不直接作为待办清单使用
- 若某项任务完成，应同步更新本文档和 `docs/README.md`

## 10. 下一轮 Run 任务全集

以下项目默认全部进入下一轮 run 的任务池；除非启动前显式裁剪，否则视为当前主线剩余项全集。

### 10.1 P0 主线

- `4.1` 完整 `loop lineage` 收口

其中 `4.1` 在当前上下文下还应继续显式跟踪这些未决点：

- 是否把对外 contract 从“`lineage` envelope + 扁平兼容字段”进一步压缩到以 `lineage` 为主
- compaction / archive / integration artifact 是否都应直接消费 canonical `lineage`
- trace / integration export 目前已完成 resource-level lineage 投影；是否还需要继续扩展到更细粒度的 span / observation 级 lineage 投影

### 10.2 P1 外部集成

- `5.2` Phoenix SDK / API 接入
- `5.3` Langfuse SDK / API 接入

### 10.3 P2 平台产品化

- `6.1` auth / workspace 权限模型
- `6.2` 真正的 job queue / worker
- `6.3` DB projection 与 migration
- `6.4` UI / dashboard

### 10.4 启动约束

- 下一轮 run 若仍走治理与集成主线，优先顺序调整为 `4.1 -> 5.2 -> 5.3 -> 6.x`
- 对 `4.1` 而言，下一轮更值得优先验证的是 compaction / archive / integration export 对 canonical `lineage` 的直接消费，而不是重复补 export resource-level 投影
- 若下一轮 run 需要“全部列入但分批执行”，本节任务全集优先作为任务池，而不是承诺单轮全部实现
