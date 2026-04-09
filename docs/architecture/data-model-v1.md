# Meta-Harness Data Model v1

更新时间：2026-04-09

## 1. 目标

本文档定义 Meta-Harness 的 canonical data model v1，用于约束：

- 文件系统中的 canonical artifacts
- 后续 API / service 层对象
- 数据库索引层投影
- 外部 observability / dataset / benchmark 集成映射

本版本遵循以下原则：

- 文件系统是事实源
- 数据库是投影，不是主存储
- API 返回对象必须能追溯到本地 artifact
- 外部平台只做镜像与分析层，不做唯一存储

## 2. 模型分层

v1 分 4 层：

1. Execution
2. Evaluation
3. Dataset
4. Governance

## 3. Execution 层

## 3.1 WorkflowProfile

职责：

- 定义某类任务的默认运行策略
- 定义可用工具、预算、默认 evaluators、优化阈值和 runtime 约束

事实源：

- `configs/profiles/<profile>.json`

最小字段：

- `name`
- `defaults`
- `description`

说明：

- v1 暂不要求单独 artifact 化 profile metadata
- API 层把 profile 作为只读配置对象暴露

## 3.2 ProjectOverlay

职责：

- 覆盖 workflow profile 的默认值
- 注入项目级 runtime、evaluation、optimization、integration 配置

事实源：

- `configs/projects/<project>.json`

最小字段：

- `name`
- `workflow`
- `overrides`

## 3.3 Candidate

职责：

- 表示一个可执行的 harness variant
- 承载 config patch、code patch、proposal metadata 和 lineage 信息

canonical artifact：

- `candidates/<candidate_id>/candidate.json`
- `candidates/<candidate_id>/effective_config.json`
- `candidates/<candidate_id>/proposal.json`
- `candidates/<candidate_id>/code.patch`
- `candidates/<candidate_id>/candidate_fingerprint.txt`

最小字段：

- `candidate_id`
- `profile`
- `project`
- `notes`
- `parent_candidate_id`
- `proposal_id`
- `source_proposal_ids`
- `iteration_id`
- `source_iteration_ids`
- `source_run_ids`
- `source_artifacts`
- `lineage`
- `code_patch_artifact`
- `created_at`

扩展字段建议：

- `status`
- `tags`
- `proposal_strategy`
- `source_run_ids`
- `source_dataset_versions`

说明：

- `lineage` 是 candidate lineage 的 canonical envelope，用于更稳定地表达 proposal / iteration / run / artifact 来源
- `parent_candidate_id`、`proposal_id`、`source_proposal_ids`、`iteration_id`、`source_iteration_ids`、`source_run_ids`、`source_artifacts` 仍保留为兼容字段，但应与 `lineage` 保持同步
- 治理语义采用 `lineage-first`：新增 contract、投影和外部集成优先直接读取 `lineage`，不再以扁平兼容字段作为主接口
- 面向 catalog / API 的 candidate 投影应优先直接暴露 `lineage`，而不是要求调用方自行从扁平字段重建

## 3.4 Run

职责：

- 表示 candidate 或 profile/project 在某个 task set 或 dataset 上的一次执行

canonical artifact：

- `runs/<run_id>/run_metadata.json`
- `runs/<run_id>/effective_config.json`
- `runs/<run_id>/score_report.json`
- `runs/<run_id>/evaluators/`
- `runs/<run_id>/tasks/`
- `runs/<run_id>/artifacts/`

最小字段：

- `run_id`
- `profile`
- `project`
- `candidate_id`
- `created_at`

扩展字段建议：

- `source_type`
- `source_ref`
- `dataset_id`
- `dataset_version`
- `benchmark_experiment`
- `git_commit`
- `trigger`
- `status`

## 3.5 TaskExecution

职责：

- 表示 run 内单个 task 的执行结果

canonical artifact：

- `runs/<run_id>/tasks/<task_id>/task_result.json`
- `runs/<run_id>/tasks/<task_id>/*.stdout.txt`
- `runs/<run_id>/tasks/<task_id>/*.stderr.txt`
- `runs/<run_id>/tasks/<task_id>/steps.jsonl`

最小字段：

- `task_id`
- `scenario`
- `difficulty`
- `weight`
- `expectations`
- `success`
- `completed_phases`
- `failed_phase`
- `workdir`

## 3.6 TraceEventV2

职责：

- 作为 run/task 级执行事件流的 canonical 记录格式

canonical artifact：

- `runs/<run_id>/tasks/<task_id>/steps.jsonl`

最小字段：

- `step_id`
- `phase`
- `status`
- `run_id`
- `task_id`
- `candidate_id`
- `timestamp`
- `latency_ms`
- `error`

扩展字段：

- `session_ref`
- `prompt_ref`
- `tool_name`
- `tool_call_id`
- `retrieval_refs`
- `artifact_refs`
- `token_usage`
- `model`
- `metadata`

说明：

- 当前代码已经支持 `session_ref`、`prompt_ref`、`tool_name`、`tool_call_id`、`retrieval_refs`、`artifact_refs`、`token_usage`、`model`
- v1 保持对现有 `steps.jsonl` 的向后兼容

## 3.7 WorkspaceArtifact

职责：

- 记录 run workspace 的来源和 patch 应用状态

canonical artifact：

- `runs/<run_id>/artifacts/workspace.json`

最小字段：

- `source_repo`
- `workspace_dir`
- `patch_applied`
- `patch_already_present`
- `code_patch_artifact`

## 4. Evaluation 层

## 4.1 EvaluatorRun

职责：

- 记录单个 evaluator 针对某个 run 的一次评分执行

canonical artifact：

- `runs/<run_id>/evaluators/<evaluator_name>.json`

v1 最小字段：

- `evaluator_name`
- `run_id`
- `started_at`
- `completed_at`
- `status`
- `report`

说明：

- 当前代码里 evaluator artifact 已收口为 envelope，并兼容读取历史裸 report
- envelope 允许附带 `trace_grade`、`profiling`、`trace_artifact`、`artifact_refs`
- 当前最小 tracing / profiling 形态为：`runs/<run_id>/evaluators/<name>.trace.jsonl` + envelope 中的 profiling 摘要
- v1 服务层继续兼容新旧两种磁盘格式

## 4.2 ScoreReport

职责：

- 记录聚合后的最终评分结果

canonical artifact：

- `runs/<run_id>/score_report.json`

最小字段：

- `correctness`
- `cost`
- `maintainability`
- `architecture`
- `retrieval`
- `human_collaboration`
- `composite`

## 4.3 BenchmarkExperiment

职责：

- 描述一次 benchmark 比较任务及其结果集合

v1 事实源：

- benchmark spec JSON
- benchmark 输出 payload
- `candidate.proposal` 中的 `experiment` / `variant`

建议最小字段：

- `experiment_id`
- `profile`
- `project`
- `baseline`
- `analysis_mode`
- `variants`
- `focus`
- `repeats`
- `dataset_ref`

说明：

- v1 暂不强制落成单一 canonical 文件
- Phase 1 可以引入 `benchmarks/<experiment_id>/manifest.json`

## 4.4 BenchmarkVariant

职责：

- 描述 benchmark 中一个待比较变体

最小字段：

- `name`
- `variant_type`
- `hypothesis`
- `implementation_id`
- `config_patch`
- `code_patch`
- `expected_signals`
- `tags`

## 5. Dataset 层

## 5.1 Dataset

职责：

- 表示一个长期存在的数据集命名空间

建议字段：

- `dataset_id`
- `title`
- `description`
- `owner`
- `tags`

## 5.2 DatasetVersion

职责：

- 表示某个稳定冻结的数据集版本

canonical artifact：

- Phase 0 文档定义
- Phase 1 计划落到 `datasets/<dataset_id>/<version>/dataset.json`

最小字段：

- `dataset_id`
- `version`
- `schema_version`
- `case_count`
- `cases`

扩展字段建议：

- `source_summary`
- `created_at`
- `created_by`
- `frozen`
- `split`

## 5.3 DatasetCase

职责：

- 表示单个可评测样本

最小字段：

- `source_type`
- `run_id`
- `profile`
- `project`
- `task_id`
- `phase`
- `step_id`
- `raw_error`
- `failure_signature`
- `scenario`
- `difficulty`
- `weight`
- `expectations`
- `phase_names`

当前已落地的扩展字段：

- `query`
- `expected_paths`
- `expected_rank_max`
- `expected_grounding_refs`
- `expected_answer_contains`

说明：

- 这些字段用于承载 retrieval / grounding 类 golden case
- `task_set -> dataset` 转换时，可从 task 的 `dataset_case` 映射得到
- 这样 dataset 不再只保存任务元信息，也可以保存可验证的结果期望

## 5.4 Annotation

职责：

- 记录人工标注、人工审核或人工裁决

v1 建议字段：

- `annotation_id`
- `target_type`
- `target_ref`
- `label`
- `value`
- `notes`
- `annotator`
- `created_at`

说明：

- 当前仓库未落地 annotation
- 该对象先在 API 文档中保留

## 6. Governance 层

## 6.1 JobResultRef

职责：

- 指向异步 job 的结果对象

建议字段：

- `target_type`
- `target_id`
- `path`

## 6.2 JobRecord

职责：

- 表示异步任务的状态与结果引用

建议 canonical artifact：

- `reports/jobs/<job_id>.json`

最小字段：

- `job_id`
- `job_type`
- `status`
- `requested_by`
- `job_input`
- `result_ref`
- `error`
- `created_at`
- `started_at`
- `completed_at`

状态：

- `queued`
- `running`
- `succeeded`
- `failed`
- `cancelled`

## 6.3 GatePolicy

职责：

- 定义 benchmark、regression、nightly、promotion 的阻断和放行规则

建议字段：

- `policy_id`
- `scope`
- `conditions`
- `waiver_rules`
- `notification_rules`
- `enabled`

## 6.4 Champion

职责：

- 记录某个 profile/project 当前推荐 candidate

事实源：

- `candidates/champions.json`

最小字段：

- `profile_project_key`
- `candidate_id`

扩展字段建议：

- `promoted_by`
- `promoted_at`
- `evidence_run_ids`
- `promotion_reason`

## 7. 事实源与投影规则

事实源：

- `configs/`
- `candidates/`
- `runs/`
- `archive/`
- `datasets/`（Phase 1 起）

数据库投影：

- run 列表
- candidate 列表
- benchmark 汇总
- dataset 检索
- gate 执行记录
- annotation 检索

规则：

- 删除或归档以文件系统为准
- 数据库故障不影响本地 run 执行
- API 返回对象需带 artifact 路径或稳定 ref

## 8. 兼容策略

- 当前 `CandidateMetadata`、`RunMetadata`、`TraceEvent`、`ScoreReport`、`DatasetVersion` 保持兼容
- 先在 service 层补充投影字段，不立即破坏现有磁盘格式
- 需要破坏性变更时，通过 `schema_version` 和 migration 脚本推进

## 9. 非目标

以下不属于 v1：

- 实时流式 trace viewer 协议
- 复杂 RBAC 细粒度权限
- 外部平台反向写入 canonical artifact
- 全量替换现有目录结构
