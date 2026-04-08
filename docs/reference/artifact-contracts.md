# Meta-Harness Artifact Contracts

更新时间：2026-04-08

## 1. 目标

本文档定义 Meta-Harness 在文件系统中的 artifact contract，保证：

- 所有关键对象可回放
- API 和数据库只做投影
- archive / compact / export 不破坏事实源语义

## 2. 顶层目录

当前保留：

- `configs/`
- `candidates/`
- `runs/`
- `archive/`
- `task_sets/`
- `reports/`

按需物化：

- `datasets/`
- `exports/`
- `reports/exports/`

## 3. Candidate Contract

目录：

```text
candidates/<candidate_id>/
  candidate.json
  effective_config.json
  proposal.json
  code.patch
  candidate_fingerprint.txt
```

要求：

- `candidate.json` 必须存在
- `effective_config.json` 必须存在
- `proposal.json` 可选
- `code.patch` 可选
- `candidate_fingerprint.txt` 用于去重和幂等

兼容规则：

- 可新增字段
- 不可删除 `candidate_id/profile/project/created_at`

## 3.1 Proposal Contract

目录：

```text
proposals/<proposal_id>/
  proposal.json
  proposal_evaluation.json
  code.patch
```

要求：

- `proposal.json` 必须存在
- `proposal_evaluation.json` 必须存在
- `code.patch` 可选

说明：

- `proposal_evaluation.json` 记录 ranking、selection reason、是否被采纳、是否已物化
- proposal-only 和 materialize-afterwards 共享同一 evaluation artifact

## 4. Run Contract

目录：

```text
runs/<run_id>/
  run_metadata.json
  effective_config.json
  score_report.json
  evaluators/
  tasks/
  artifacts/
  workspace/
```

要求：

- `run_metadata.json` 必须存在
- `effective_config.json` 必须存在
- `tasks/` 必须存在
- `artifacts/` 必须存在
- `score_report.json` 可选
- `workspace/` 可选
- `evaluators/` 可选

## 5. Task Contract

目录：

```text
runs/<run_id>/tasks/<task_id>/
  task_result.json
  steps.jsonl
  <phase>.stdout.txt
  <phase>.stderr.txt
  intervention.json
  benchmark_probe.stdout.txt
```

要求：

- `task_result.json` 在 task 完成后必须存在
- `steps.jsonl` 只要发生 trace 事件就必须存在
- stdout/stderr 文件按 phase 输出，可选

## 6. Trace Contract

文件：

- `runs/<run_id>/tasks/<task_id>/steps.jsonl`

要求：

- 每行一个 JSON object
- 每个 object 至少有 `step_id/phase/status/timestamp`
- `run_id/task_id` 必须可从事件本身或目录上下文推断

兼容策略：

- 新字段追加，不删除现有关键字段
- reader 必须忽略未知字段

## 7. Score Contract

文件：

- `runs/<run_id>/score_report.json`
- `runs/<run_id>/evaluators/<name>.json`

要求：

- `score_report.json` 是最终聚合结果
- evaluator 文件表示单 evaluator 输出
- evaluator 文件允许是 report 兼容格式
- 若使用 envelope，建议附带 `trace_grade`、`profiling`、`trace_artifact`、`artifact_refs`
- `trace_artifact` 指向 `runs/<run_id>/evaluators/<name>.trace.jsonl` 时，文件应保存 evaluator 自身的 trace/profiling 事件
- profiling 至少应能表达 evaluator 输入规模或执行明细，例如 trace event 数、task 数、command evaluator 子命令耗时

Phase 1 计划：

- 为 evaluator 文件补统一 envelope

## 8. Workspace Contract

文件：

- `runs/<run_id>/artifacts/workspace.json`

作用：

- 记录 `source_repo`
- 记录 `workspace_dir`
- 记录 patch 应用结果

规则：

- `workspace/` 可被 compaction 删除
- `workspace.json` 不可因 compaction 被删除

## 9. Failure Contract

文件：

- `runs/<run_id>/error_signatures.json`

作用：

- 缓存失败签名抽取结果

规则：

- 如果缺失，可从 trace 重建
- 不是唯一事实源

## 10. Archive Contract

目录：

```text
archive/
  runs/
  candidates/
  cleanup_logs/
```

规则：

- archive 是冷存储，不是删除
- archived object 必须保持原目录结构
- cleanup log 必须记录操作类型、目标、来源路径和过滤条件

## 11. Compaction Contract

规则：

- compaction 允许删除 `workspace/`
- 若显式配置，允许删除大体积 artifacts
- `run_metadata.json`、`effective_config.json`、`score_report.json`、`artifacts/workspace.json` 不可删除
- compaction 后必须写 `artifacts/compaction.json`

## 12. Dataset Contract

Phase 0 约定，Phase 1 落地：

```text
datasets/<dataset_id>/<version>/
  dataset.json
  manifest.json
```

要求：

- dataset version 必须冻结
- case 数量、schema version、source summary 必须明确

## 13. Benchmark Contract

当前 benchmark report 落盘为：

```text
reports/benchmarks/<experiment_id>.json
reports/benchmark-suites/<suite_id>.json
```

要求：

- `reports/benchmarks/<experiment_id>.json` 必须包含 `experiment/baseline/best_variant/variants/report_summary`
- 每个 variant 至少要有 `name/candidate_id/run_id/run_ids/score/delta_from_baseline`
- suite report 必须包含 `suite/results`

## 13.1 Export Artifact Contract

当前集成导出结果可落盘为：

```text
reports/exports/integrations/<integration_name>/<run_id>.json
```

要求：

- artifact 至少包含 `run_id/destination/format/integration`
- `integration` 至少包含 `status_code/attempt_count/ok/failure_kind/retryable/retry_exhausted/error`
- job 触发的 integration export，其 `result_ref.path` 应优先指向这份 artifact，而不是瞬时返回值

## 14. Loop Contract

目录：

```text
reports/loops/<loop_id>/
  loop.json
  iteration_history.jsonl
  iterations/<iteration_id>/
    iteration.json
    proposal_input.json
    proposal_output.json
    selected_candidate.json
    benchmark_summary.json
    experience_summary.json
    next_round_context.json
    proposer_context/
      manifest.json
```

要求：

- `loop.json` 必须存在
- `iteration_history.jsonl` 必须存在
- `iterations/<iteration_id>/` 下的 7 个 JSON artifact 必须齐全
- `iterations/<iteration_id>/proposer_context/manifest.json` 必须存在
- `loop.json.iteration_count` 应与 `iteration_history.jsonl` 的记录数一致

## 15. Contract Validator

从 2026-04-08 起，公开 artifact contract 不再只靠人工目检。

实现入口：

- `src/meta_harness/artifact_contracts.py`

当前覆盖：

- `proposal`
- `dataset`
- `loop`
- `evaluator`

CLI 用法：

```bash
PYTHONPATH=src python -m meta_harness.artifact_contracts \
  --artifact proposal=proposals/<proposal_id> \
  --artifact dataset=datasets/<dataset_id>/<version> \
  --artifact loop=reports/loops/<loop_id> \
  --artifact evaluator=runs/<run_id>/evaluators/command.json
```

返回：

- 标准输出为 JSON summary
- 任一 artifact 缺少必需文件或关键 JSON 结构无效时，进程返回非零退出码

Smoke 复用约定：

- `scripts/demo_public_flow.sh` 会在公开 demo 路径末尾调用 validator
- 结果会写入 `reports/demo_public_validation.json`

要求：

- `loop.json` 必须存在
- `iteration_history.jsonl` 必须存在
- 每轮 iteration 目录必须至少包含 `iteration.json`
- `experience_summary.json` 作为下一轮经验写回摘要存在
- `next_round_context.json` 必须包含 `experience_summary_path`
```

要求：

- experiment report 必须能关联原始 spec 与候选/运行结果
- suite report 必须能回溯到各 experiment
- benchmark winner 必须能回溯到 candidate / run

## 14. Export Contract

导出不是 canonical artifact。

允许格式：

- `otel-json`
- `phoenix-json`
- `langfuse-json`

规则：

- export 失败不影响 run 完整性
- export payload 必须可从 canonical artifacts 重新生成

## 15. Job Contract

目录：

```text
reports/jobs/
  <job_id>.json
```

规则：

- job record 是异步编排状态的 canonical artifact
- job 结果只引用目标对象，不复制目标 artifact 内容
- job 删除或清理不应影响 run/candidate/dataset/benchmark 本体

最小字段：

- `job_id`
- `job_type`
- `status`
- `job_input`
- `result_ref`
- `error`
- `created_at`
- `started_at`
- `completed_at`

## 16. Loop Contract

目录：

```text
reports/loops/<loop_id>/
  loop.json
  iteration_history.jsonl
  iterations/
    <iteration_id>/
      iteration.json
      proposal_input.json
      proposal_output.json
      selected_candidate.json
      benchmark_summary.json
      proposer_context/
        manifest.json
      next_round_context.json
```

要求：

- `loop.json` 必须存在
- `iteration_history.jsonl` 必须存在
- 每轮迭代目录必须存在 `iteration.json`
- `proposal_input.json`、`proposal_output.json`、`selected_candidate.json`、`benchmark_summary.json`、`next_round_context.json` 应作为最小闭环工件输出
- `proposer_context/manifest.json` 必须存在，用于给 proposer 暴露经过筛选的历史文件系统视图
- 若 `benchmark_summary.json.evaluation.benchmark_skipped=true` 或 `executor.status=validation_failed`，则必须同时保留 `evaluation.validation`

规则：

- loop artifact 不替代 `runs/`、`candidates/`、`proposals/`
- loop 只记录纵向搜索编排结果，底层执行事实仍以 run/candidate/proposal artifact 为准
- loop artifact 必须能追溯到 `candidate_id`、`run_id`、`proposal_id`
- 若通过 job API 触发，job `result_ref.path` 应指向 `reports/loops/<loop_id>/loop.json`

## 17. 数据库投影规则

数据库可索引：

- run summary
- candidate summary
- benchmark summary
- dataset summary
- gate execution history

数据库不可成为唯一来源：

- trace body
- stdout/stderr
- patch body
- effective config

## 18. 校验要求

Phase 1 起建议增加 artifact validator：

- run validator
- candidate validator
- dataset validator
- benchmark validator

最少校验：

- 必需文件存在
- JSON 可解析
- schema version 合法
- 关键 ref 可追溯
