# Meta-Harness 评测平台演进计划

## 1. 背景

`meta-harness` 当前已经具备一条可用的离线治理闭环：

- `candidate -> run -> score -> observe -> benchmark -> propose -> shadow-run`
- run 级 artifact 落盘与回放
- snapshot-based benchmark 与 stability/cost 排序

当前强项在于实验编排与变体治理，而不是通用 eval 产品或生产可观测性平台。

随着 benchmark V2、observation loop、proposal workflow 的演进，下一阶段的主要瓶颈已不再是“能不能跑”，而是：

1. trace 数据模型过薄，难以支撑 trace grading、OTel exporter、Phoenix/Langfuse 对接。
2. evaluator 结果可归档，但 evaluator 自身不可观测。
3. task set 更像执行脚本，而不是可版本化、可持续扩张的 eval dataset。
4. benchmark 能力已成型，但尚未产品化为 CI gate。

## 2. 决策

### 2.1 不重写平台

当前仓库已经沉淀出通用但稀缺的平台能力：

- 文件系统为真相源
- run/candidate lineage
- benchmark variant orchestration
- proposal/shadow-run optimization loop

这些能力并不是 `promptfoo`、`Inspect AI`、`Phoenix`、`Langfuse` 的直接替代对象，因此不建议基于外部项目重做一遍平台。

### 2.2 采用“内核自持 + 外部兼容”路线

下一阶段采用以下原则：

- 内部保持 canonical artifact 与 canonical data model
- 外部能力通过 adapter / exporter / importer 接入
- 不将任一外部项目的数据结构直接作为内部真相源

## 3. 设计参考

本计划参考以下优秀设计与论文/文档，并吸收其最适合当前仓库的部分：

- OpenAI, *Evaluation best practices*  
  来源：<https://developers.openai.com/api/docs/guides/evaluation-best-practices>  
  启发：把目标、数据集、指标、对比实验、持续评估组织成飞轮；数据集来源必须混合生产数据、专家样本、历史日志与边界样本。

- OpenAI, *Trace grading*  
  来源：<https://developers.openai.com/api/docs/guides/trace-grading>  
  启发：不仅评 final output，也要让整条 trace 可以被 grading；trace 本身应是可分析对象。

- UK AISI, *Inspect AI*  
  来源：<https://inspect.aisi.org.uk/scorers.html>  
  来源：<https://inspect.aisi.org.uk/tracing.html>  
  来源：<https://inspect.aisi.org.uk/agent-bridge.html>  
  启发：执行、sandbox、trace、scorer 需要正交分层；评分可后置；对外部 agent/CLI 的桥接能力非常重要。

- Promptfoo, *CI/CD* 与 *Tracing*  
  来源：<https://www.promptfoo.dev/docs/integrations/ci-cd/>  
  来源：<https://www.promptfoo.dev/docs/tracing/>  
  启发：评测必须以 PR gate / nightly gate 的形态出现；trace viewer 与 OTLP 兼容层能显著降低接入成本。

- OpenTelemetry, *GenAI semantic conventions*  
  来源：<https://opentelemetry.io/docs/specs/semconv/gen-ai/>  
  启发：trace 语义需要在模型、agent、event、tool、MCP 等层面标准化，否则后续 exporter 只能不断堆临时 mapping。

- Arize Phoenix, *Tracing* 与 *LLM evals*  
  来源：<https://arize.com/docs/phoenix/get-started/get-started-tracing>  
  来源：<https://arize.com/docs/phoenix/evaluation/llm-evals>  
  启发：不仅 agent 执行需要 tracing，evaluator 自身也应可追踪、可复盘。

- Langfuse, *Documentation*  
  来源：<https://langfuse.com/docs>  
  启发：session、prompt version、dataset、experiments、annotation queue 应被视为同一平台内的关联对象，而不是零散工具。

- Anthropic, *Quantifying infrastructure noise in agent coding evals*  
  来源：<https://www.anthropic.com/engineering/infrastructure-noise>  
  启发：基础设施噪声会显著扭曲评测结论，因此 benchmark 必须显式冻结环境并记录稳定性。

## 4. 目标状态

下一阶段目标不是把仓库变成另一个 `promptfoo` 或 `Langfuse`，而是把 `meta-harness` 演进为：

- 对内：artifact-first 的 experiment control plane
- 对外：可对接通用 evaluator、OTel backend、trace UI、CI gate 的评测平台内核

## 5. Canonical 数据模型

下一阶段新增或升级的核心对象如下。

### 5.1 Dataset 层

- `Dataset`
- `DatasetVersion`
- `Case`
- `CaseExpectation`
- `Annotation`

### 5.2 Execution 层

- `Run`
- `TaskExecution`
- `TraceEventV2`
- `ArtifactRef`
- `SessionRef`
- `PromptRef`

### 5.3 Evaluation 层

- `EvaluatorRun`
- `Score`
- `BenchmarkExperiment`
- `BenchmarkVariant`

## 6. 分阶段计划

### Phase 0: 架构定稿

目标：

- 明确 canonical data model
- 明确外部兼容边界
- 明确 CI / tracing / dataset 三条主线

交付物：

- 本计划文档
- ADR（可后续补）

### Phase 1: TraceEvent v2 与 artifact 升级

目标：

- 将现有 `steps.jsonl` 从 phase log 升级为可承载 agent trace 语义的事件流
- 保持向后兼容

新增字段最小集合：

- `run_id`
- `task_id`
- `candidate_id`
- `model`
- `prompt_ref`
- `tool_name`
- `tool_call_id`
- `retrieval_refs`
- `artifact_refs`
- `token_usage`

要求：

- 运行时自动补齐 `run_id` / `task_id`
- 可从 `run_metadata.json` 推断 `candidate_id`
- 旧 trace reader 不失效

### Phase 2: 执行与评分解耦

目标：

- 支持“先执行、后重评分”
- evaluator 本身产生独立 artifact

交付物：

- `run execute --no-score`
- `run score --evaluator ...`
- `runs/<run_id>/evaluators/<evaluator_id>/...`

当前状态：

- 已支持 `score_run(..., evaluator_names=...)`
- 已支持 `run score --evaluator ...`
- 已支持输出 `runs/<run_id>/evaluators/<name>.json`
- `execute_managed_run(..., score_enabled=False)` 已落地
- 已支持 `run execute --no-score`

### Phase 3: Dataset 化

目标：

- 将 `task_set` 从一次性执行脚本升级为带版本的 eval corpus

交付物：

- `datasets/` 目录结构
- `DatasetVersion` schema
- `task_set -> dataset case` 的兼容层

当前状态：

- 已新增 `DatasetCase` / `DatasetVersion` schema
- failure dataset 已按正式 schema 输出
- 已新增 `task_set -> dataset case` 基础兼容层

### Phase 4: CI Gate

目标：

- 将 benchmark / observation 能力接成正式质量门

交付物：

- `smoke` 工作流
- `regression` 工作流
- `nightly benchmark-suite` 工作流
- gate policy 配置

当前状态：

- 已新增 `.github/workflows/smoke.yml`
- 已新增 `.github/workflows/regression.yml`
- 已新增 `.github/workflows/nightly-benchmark-suite.yml`
- 当前先以分层 pytest 套件替代正式 gate policy 配置

### Phase 5: OTel Exporter

目标：

- 将内部 trace/event 映射到 OTel 语义

交付物：

- OTLP exporter
- trace schema mapping 文档

当前状态：

- 已新增 OTel 风格 JSON exporter 骨架
- 已提供 `run export-trace` CLI
- OTLP 直连与语义映射文档仍待补

### Phase 6: Phoenix / Langfuse 接入

目标：

- 提供 UI 级 replay、trace exploration、evaluator inspection

原则：

- 本地文件仍为真相源
- 外部平台为镜像与分析层，而非唯一存储

当前状态：

- 已支持 `otel-json`
- 已支持 `phoenix-json` adapter skeleton
- 已支持 `langfuse-json` adapter skeleton
- 尚未接入真实 SDK / API transport

### Phase 7: Dataset 飞轮

目标：

- 从失败 run、回归 case、人工标注中持续增长数据集

交付物：

- failed-run case extraction
- annotation ingestion
- regression set / hard case set / adversarial set

当前状态：

- 已支持从 failed runs 提取基础 dataset JSON
- failure dataset 已切换到正式 schema 输出
- 已新增 `dataset extract-failures` CLI
- annotation ingestion 与 dataset promotion 仍待补

## 7. 当前执行策略

本次会话不尝试一次性推进所有阶段，而是先完成一个最小但高杠杆切片：

### Slice 1: TraceEvent v2 基础落地

范围：

- 扩展 `TraceEvent` schema
- 让 trace 自动携带 `run_id` / `task_id` / `candidate_id`
- 为后续 OTel/Phoenix/Langfuse 接入预留 `prompt_ref` / `tool_name` / `tool_call_id` / `retrieval_refs` / `artifact_refs` / `token_usage`
- 保持现有 runtime 与 tests 的兼容性

为什么先做这一步：

- 风险低
- 向后兼容空间大
- 对后续 evaluator tracing、dataset 化、exporter 都是前置条件

当前状态：

- 已完成第一批 schema 字段扩展
- 已支持自动注入 `run_id` / `task_id` / `candidate_id`
- 已补充覆盖测试
- CLI 扩展写入与 exporter 接入留待下一阶段

## 8. 验收标准

### Slice 1 验收标准

- 现有 `run execute` 路径继续产出 `steps.jsonl`
- 新事件字段可写入并通过 schema 校验
- trace 至少自动带上 `run_id`、`task_id`，并在存在时带上 `candidate_id`
- 相关测试通过

## 9. 非目标

本轮不做：

- 直接接入 Phoenix / Langfuse SDK
- 重构 benchmark 核心流程
- 完整数据集系统
- 完整 CI workflow

这些工作需要建立在 TraceEvent v2 与 evaluator artifact 结构稳定之后再推进。
