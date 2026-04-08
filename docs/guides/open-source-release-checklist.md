# Meta-Harness 开源发布 Checklist

更新时间：2026-04-08

本文档面向“将 `meta-harness` 作为基于论文思想实现的工程项目开源”这一目标。

原则：

- 先保证**别人能理解、能跑通、能复现**
- 再保证**论文思想与工程实现之间的映射清晰**
- 最后再扩展产品面、外部集成和 UI

## A. 首发前必须完成

### A1. 定位与文档

- [x] README 首页给出一句话定位、核心对象和快速入口
- [x] 增加论文映射文档：`docs/research/paper-mapping.md`
- [x] 增加复现文档：`docs/guides/reproducibility.md`
- [x] 同步边界矩阵状态：`archive/docs/boundary-gap-matrix.md`
- [x] 在 README 中明确哪些能力已稳定、哪些仍是 experimental
- [x] 增加术语表，统一 `proposal`、`candidate`、`benchmark variant`、`promotion`、`champion`

### A2. 运行与复现

- [x] 提供最小 CLI 路径说明
- [x] 提供 dataset / benchmark / proposal 的最小复现路径
- [x] 增加可直接执行的 demo 脚本或 `make demo-*` 入口
- [x] 提供一组公开可分发的小型 demo assets
- [x] 提供预期输出样例，便于读者核对结果

### A3. 开源卫生

- [x] 补 `LICENSE`
- [x] 审核并移除 `docs/Meta-Harness.pdf`，避免再分发权限风险
- [x] 清理或改造所有机器私有绝对路径
- [x] 将项目特定配置替换为示例配置或环境变量写法
- [x] 将本机参考项目相关资产完全从公开仓库中剥离
- [x] 检查 README / docs / config 中的外部链接是否可公开访问或明确为占位链接

### A4. 工程可信度

- [x] 相关核心能力已有自动化测试
- [x] 增加 artifact contract validator
- [x] 增加一份“公开 benchmark 结果快照”
- [x] 在 CI 中增加面向开源发布的 smoke 路径

当前对应资产：

- validator 入口：`src/meta_harness/artifact_contracts.py`
- 公开 snapshot：`reports/benchmarks/demo_public_budget_headroom.json`
- 公开 smoke 脚本：`scripts/demo_public_flow.sh`
- CI smoke workflow：`.github/workflows/smoke.yml`

## B. 首发后一月内建议完成

### B1. Trace 与 Evaluator

- [x] 收口 `TraceEventV2`
- [x] 增加 trace grading 最小实现
- [x] 统一 `EvaluatorRun` artifact envelope
- [ ] 增加 evaluator 自身 tracing / profiling

### B2. Gate 与 Promotion

- [x] benchmark / promotion 已有最小 gate policy artifact
- [x] 增加 gate registry / list / inspect
- [x] 增加 gate result artifact 与历史记录
- [x] 支持 workflow 中自动执行 gate
- [x] 实现 waiver / notification 的真实执行

### B3. Proposal / Proposer

- [x] proposal 已成为独立 artifact
- [x] 支持 `proposal-only` 与后续 materialization
- [x] 增加 proposal list / query / inspect 能力
- [x] 增加多 proposer / proposer registry
- [ ] 增加 proposal ranking / evaluation

## C. 适合作为论文工程增强部分

### C1. 外部 Observability

- [ ] OTLP 真正发送路径
- [ ] Phoenix SDK / API 接入
- [ ] Langfuse SDK / API 接入
- [x] integration health check

### C2. 服务化与产品面

- [ ] 完整 API 产品面
- [ ] token auth / workspace 权限（当前仅有 bearer token，尚无 workspace 权限模型）
- [ ] job queue / worker（当前为单机 inline job + retry surface）
- [ ] DB projection 与 migration
- [ ] UI：Runs / Benchmarks / Datasets / Candidates / Gate Policies

## D. 当前已具备、可对外强调的能力

- [x] artifact-first 的 `candidate -> run -> score -> benchmark -> propose -> shadow-run` 闭环
- [x] versioned dataset artifact、annotation ingestion、split derivation、dataset promotion
- [x] proposal artifact 生命周期与 delayed materialization
- [x] benchmark / promotion gate artifact 雏形
- [x] white-box audit 最小能力与 runtime profiling

## E. 建议发布节奏

### Release 0.1

目标：研究工程实现可公开阅读、运行和复现

- README / paper mapping / reproducibility 完整
- demo 资产可跑通
- 私有路径与 license 问题解决
- dataset lifecycle 与 proposal artifacts 作为主亮点

### Release 0.2

目标：从“研究工程”走向“可复用平台内核”

- TraceEventV2
- unified EvaluatorRun
- gate result artifact
- proposal registry

### Release 0.3

目标：开始具备外部系统集成与团队协作能力

- OTLP transport
- API 收口
- auth / pagination / query model
