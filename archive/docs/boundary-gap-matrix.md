# Meta-Harness 边界与缺口矩阵

更新时间：2026-04-07

## 1. 当前系统定位

综合 `platform-design.md`、`eval-platform-evolution-plan.md`、`api-surface-v1.md` 与
`Meta-Harness.pdf`，当前系统最合理的定义是：

- **artifact-first 的评测与优化控制平面**
- 负责组织 `candidate -> run -> trace/artifact -> score -> benchmark -> propose -> shadow-run`
- 不直接承载被测系统的业务逻辑
- 通过 profile / project overlay / evaluator / contract 注入任务差异

一句话：

> Meta-Harness 是评测与优化内核，不是单个业务 agent，也不是完整的 observability / annotation / UI 平台。

## 2. 边界与缺口表

### 2.1 边界内已实现

| 类别 | 项目 | 当前状态 | 依据 | 建议优先级 |
|---|---|---|---|---|
| 边界内已实现 | 配置分层与 profile/project 复用模型 | 已实现 | `docs/platform-design.md` | 维持 |
| 边界内已实现 | candidate / run / score / archive 基础闭环 | 已实现 | `docs/platform-design.md` | 维持 |
| 边界内已实现 | CLI 主入口与子命令体系 | 已实现 | `src/meta_harness/cli.py` | 维持 |
| 边界内已实现 | benchmark / benchmark-suite / observation | 已实现 | `src/meta_harness/cli.py` | 维持 |
| 边界内已实现 | optimize propose / shadow-run | 已实现 | `docs/platform-design.md` | 维持 |
| 边界内已实现 | 基础 API 骨架与 async job 入口 | 部分实现 | `docs/api-surface-v1.md`, `src/meta_harness/api/app.py` | 中 |
| 边界内已实现 | dataset 抽取与 task_set -> dataset 兼容层 | 部分实现 | `docs/eval-platform-evolution-plan.md`, `src/meta_harness/datasets.py` | 中 |
| 边界内已实现 | trace export 骨架 | 部分实现 | `src/meta_harness/services/export_service.py` | 中 |

### 2.2 边界内缺失

| 类别 | 项目 | 当前状态 | 缺什么 | 建议优先级 |
|---|---|---|---|---|
| 边界内缺失 | evaluator 自身可观测性 | 部分实现 | 当前 `command evaluator` 已归档执行工件，但仍缺统一 evaluator envelope 与 evaluator 自身 tracing | P0 |
| 边界内缺失 | 白盒审计 evaluator | 部分实现 | 已有 rule_files、runtime profiling 与 gate 接线；仍缺更完整规则库、内存峰值等深度运行时 profiling | P0 |
| 边界内缺失 | dataset 生命周期 | 部分实现 | 已有 task-set/failure dataset、annotation ingestion、split derivation、promotion；仍缺更完整 annotation queue / dataset governance / hard-case 飞轮产品化 | P1 |
| 边界内缺失 | gate policy 产品化 | 部分实现 | 已有最小 gate engine、benchmark/promotion policy 与 target artifact；仍缺 registry、history、waiver/notification 执行与 workflow 自动接线 | P1 |
| 边界内缺失 | proposer 一等能力 | 部分实现 | 已有 proposal artifact、proposal-only、materialization；仍缺 proposer registry、多 proposer/search worker、proposal ranking 与 query 面 | P1 |
| 边界内缺失 | API 产品化收口 | 部分实现 | 需要更完整的一致性、认证、分页、长任务治理 | P2 |
| 边界内缺失 | trace/event 语义完整化 | 部分实现 | 需要向完整 trace grading / exporter 继续收口 | P2 |
| 边界内缺失 | 外部集成完整链路 | 部分实现 | 需要 OTel / Phoenix / Langfuse 的真实 transport 与映射闭环 | P2 |

### 2.3 边界外不做

| 类别 | 项目 | 为什么不该进 core | 结论 |
|---|---|---|---|
| 边界外不做 | 被测系统业务逻辑 | 违反“平台通用，任务专有”原则 | 不进 core |
| 边界外不做 | 项目专属架构修改逻辑 | 应通过 project-specific evaluator / proposal_command 注入 | 不进 core |
| 边界外不做 | 通用 observability 平台本体 | 演进计划已明确“外部兼容，不做真相源替代” | 不进 core |
| 边界外不做 | Annotation UI / 标注队列产品 | 可对接，但不应成为核心平台职责 | 不进 core |
| 边界外不做 | 通用 coding agent 本体 | 平台应该编排 proposer，而不是自己变成 proposer 产品 | 不进 core |
| 边界外不做 | 外部平台作为 canonical store | 与 artifact-first 原则冲突 | 不进 core |

### 2.4 关键判断

| 类别 | 关键判断 | 结论 |
|---|---|---|
| 系统定位 | 当前最合理定位是什么 | artifact-first 的评测与优化控制平面 |
| 是否完整 | 是否已经是论文意义上的完整 Meta-Harness 系统 | 不是，更像其平台化内核 |
| 该往哪里扩 | 应扩到哪里 | 白盒审计、evaluator observability、dataset、gate |
| 不该往哪里扩 | 不应扩到哪里 | 业务逻辑、通用观测平台、标注产品、通用 agent 本体 |
| 近期最重要缺口 | 最该补什么 | P0 是白盒审计 + evaluator 可观测性 |

## 3. 当前实施策略

结合上表，本仓库当前已经完成或补出最小闭环的能力：

1. evaluator execution artifact 归档
2. 白盒审计 evaluator 最小骨架
3. dataset 正式物化入口
4. gate policy 最小执行器
5. dataset lifecycle 最小闭环
6. proposal artifact 与 delayed materialization

以下能力仍保留在后续阶段：

- TraceEvent v2 / trace grading
- evaluator tracing 与统一 EvaluatorRun envelope
- proposer registry / ranking / query
- gate registry / waiver / notification / history
- API 全面产品化
- 外部 observability 平台真实 SDK 适配
