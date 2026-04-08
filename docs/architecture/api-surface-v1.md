# Meta-Harness API Surface v1

更新时间：2026-04-07

## 1. 目标

本文档定义 Meta-Harness 产品化第一阶段的 API 面，用于：

- 驱动 UI
- 驱动外部 CI / automation
- 替代直接读写本地目录的上层集成

设计原则：

- API 对象必须能映射到本地 artifact
- CLI 和 API 共用 service 层
- 长时运行任务统一走 async job 模型

## 2. 风格

- 协议：HTTP JSON
- 认证：Bearer token
- 时间：RFC3339 UTC
- 标识：字符串 id
- 幂等创建：支持 `Idempotency-Key`

## 3. 资源模型

首批资源：

- profiles
- projects
- workflows
- optimize
- candidates
- runs
- evaluators
- benchmarks
- datasets
- annotations
- champions
- gate-policies
- jobs
- integrations

## 4. 基础对象

## 4.1 Error

```json
{
  "error": {
    "code": "run_not_found",
    "message": "run 'abc123' not found",
    "details": {}
  }
}
```

## 4.2 Job

用于异步执行：

- run create+execute
- run score
- benchmark run
- benchmark suite run
- optimize loop
- dataset build
- export tasks

字段：

- `job_id`
- `type`
- `status`
- `created_at`
- `started_at`
- `completed_at`
- `result_ref`
- `error`

状态：

- `queued`
- `running`
- `succeeded`
- `failed`
- `cancelled`

读取行为：

- `GET /jobs`
- `GET /jobs/{job_id}`

当 `result_ref` 可解析时，返回对象可附带 `result_preview`，用于直接展示：

- run 的 `composite`
- benchmark experiment 的 `best_variant`
- benchmark suite 的 `best_by_experiment`
- loop 的 `loop_id`、`best_candidate_id`、`best_run_id`、`iteration_count`

## 5. Profiles / Projects

### GET /profiles

返回可用 profile 列表。

### GET /profiles/{profile_name}

返回 profile 配置和派生 defaults。

### GET /projects

返回可用 project overlay 列表。

### GET /projects/{project_name}

返回 project 配置和 workflow 绑定。

## 5.1 Workflows

### GET /workflows/inspect

输入：

- `workflow_path`

返回：

- `workflow_id`
- `step_count`
- `primitive_ids`
- `evaluator_packs`

### POST /workflows/compile

用途：

- 把 workflow spec 编译为当前 runtime 可执行的 task set

请求示例：

```json
{
  "workflow_path": "configs/workflows/news_aggregation.json",
  "output_path": "task_sets/generated/news_aggregation.task_set.json"
}
```

响应数据：

- `workflow_id`
- `output_path`
- `task_set`

### POST /workflows/run

用途：

- 使用 workflow service 解析 workflow、自动绑定 evaluator pack、编译 task set 并执行 run
- 长时执行统一返回 job envelope

请求示例：

```json
{
  "reports_root": "reports",
  "workflow_path": "configs/workflows/news_aggregation.json",
  "profile": "base",
  "project": "demo",
  "config_root": "configs",
  "runs_root": "runs"
}
```

异步/内联 job 结果引用：

- `target_type = run`
- `target_id = <run_id>`
- `path = runs/<run_id>/score_report.json`

### POST /workflows/benchmark

用途：

- 使用 workflow service 解析 workflow、自动绑定 evaluator pack、编译 task set 并运行 benchmark
- 返回 benchmark experiment 级结果，并记录 job result_ref

请求示例：

```json
{
  "reports_root": "reports",
  "workflow_path": "configs/workflows/news_aggregation.json",
  "profile": "base",
  "project": "demo",
  "spec_path": "configs/benchmarks/news_aggregation_ab.json",
  "config_root": "configs",
  "runs_root": "runs",
  "candidates_root": "candidates",
  "focus": "workflow"
}
```

异步/内联 job 结果引用：

- `target_type = benchmark_experiment`
- `target_id = <experiment>`
- `path = reports/benchmarks/<experiment>.json`

### POST /workflows/benchmark-suite

用途：

- 使用 workflow service 解析 workflow、自动绑定 evaluator pack、编译 task set 并运行 benchmark suite
- 返回 suite 级结果，并记录 suite 级 result_ref

请求示例：

```json
{
  "reports_root": "reports",
  "workflow_path": "configs/workflows/news_aggregation.json",
  "profile": "base",
  "project": "demo",
  "suite_path": "configs/benchmarks/news_aggregation_suite.json",
  "config_root": "configs",
  "runs_root": "runs",
  "candidates_root": "candidates"
}
```

异步/内联 job 结果引用：

- `target_type = benchmark_suite`
- `target_id = <suite>`
- `path = reports/benchmark-suites/<suite>.json`

## 5.2 Optimize

### POST /optimize/propose

用途：

- 基于失败样本生成 proposal，并可选直接物化 candidate
- 返回 job envelope，`result_ref` 指向 proposal 或 candidate artifact

### POST /optimize/loop

用途：

- 通过统一 search loop 入口执行离线 optimize loop
- CLI / API 共用 `optimize_loop_service`
- job 结果引用 loop 级 artifact，而不是单轮 run artifact

请求示例：

```json
{
  "reports_root": "reports",
  "config_root": "configs",
  "runs_root": "runs",
  "candidates_root": "candidates",
  "proposals_root": "proposals",
  "task_set_path": "task_sets/demo/failure_repair.json",
  "profile": "demo_public",
  "project": "demo_openclaw",
  "plugin_id": "web_scrape",
  "proposer_id": "heuristic",
  "max_iterations": 4,
  "focus": "retrieval"
}
```

异步/内联 job 结果引用：

- `target_type = loop`
- `target_id = <loop_id>`
- `path = reports/loops/<loop_id>/loop.json`

### POST /optimize/materialize-proposal/{proposal_id}

用途：

- 将 proposal artifact 物化为 candidate artifact

## 6. Candidates

### GET /candidates

支持过滤：

- `profile`
- `project`
- `status`
- `experiment`
- `benchmark_family`

### POST /candidates

用途：

- 从 profile/project 创建 candidate
- 支持 `config_patch`
- 支持 `code_patch`
- 支持 `proposal`

请求示例：

```json
{
  "profile": "demo_public",
  "project": "demo_public",
  "notes": "benchmark candidate",
  "config_patch": {},
  "proposal": {
    "strategy": "benchmark_variant",
    "experiment": "web_scrape_audit",
    "variant": "selector_only"
  }
}
```

### GET /candidates/{candidate_id}

返回 candidate metadata、effective config、proposal 和关联 run ids。

### POST /candidates/{candidate_id}/promote

把 candidate 提升为当前 champion。

请求建议字段：

- `reason`
- `evidence_run_ids`
- `promoted_by`

## 7. Runs

### GET /runs

支持过滤：

- `profile`
- `project`
- `candidate_id`
- `status`
- `experiment`
- `benchmark_family`

### POST /runs

用途：

- 初始化 run
- 可选立即执行 task set
- 可选立即评分

请求模式：

1. `profile + project`
2. `candidate_id`

请求示例：

```json
{
  "candidate_id": "abc123",
  "task_set_path": "task_sets/demo/failure_repair.json",
  "score_enabled": true,
  "async": true
}
```

同步返回：

- `run_id`
- `status`

异步返回：

- `job_id`
- `run_id`

### GET /runs/{run_id}

返回：

- metadata
- effective_config
- score
- tasks summary
- evaluators summary
- artifact refs

### GET /runs/{run_id}/tasks

返回 task execution 列表。

### GET /runs/{run_id}/tasks/{task_id}

返回单 task 的执行明细。

### GET /runs/{run_id}/trace

返回合并后的 trace events。

支持过滤：

- `task_id`
- `phase`
- `status`

### POST /runs/{run_id}/score

对已有 run 触发评分。

请求示例：

```json
{
  "evaluators": ["basic", "command"],
  "async": true
}
```

### POST /runs/{run_id}/export-trace

导出 trace 到指定格式。

请求字段：

- `format`: `otel-json|phoenix-json|langfuse-json`
- `destination`: `download|integration`

### POST /runs/{run_id}/archive

归档单个 run。

### POST /runs/{run_id}/compact

压缩单个 run 的 workspace / artifacts。

## 8. Evaluators

### GET /evaluators

返回已注册 evaluators 及能力描述。

### GET /runs/{run_id}/evaluators

返回 run 上每个 evaluator 的执行结果。

### GET /runs/{run_id}/evaluators/{evaluator_name}

返回单 evaluator report。

## 9. Benchmarks

### GET /benchmarks

返回 benchmark experiments 列表。

### POST /benchmarks

触发单次 benchmark。

请求字段：

- `profile`
- `project`
- `task_set_path`
- `spec_path`
- `focus`
- `auto_compact_runs`
- `async`

### POST /benchmark-suites

触发 benchmark suite。

### GET /benchmarks/{experiment_id}

返回 experiment 汇总：

- baseline
- best_by_quality
- best_by_stability
- ranking
- variants

### GET /benchmarks/{experiment_id}/variants/{variant_name}

返回某个 variant 的 runs、scores、mechanism、stability。

## 10. Datasets

### GET /datasets

返回 dataset 列表。

### POST /datasets

构建 dataset version。

支持来源：

- `task_set`
- `failed_runs`
- `manual_import`

### GET /datasets/{dataset_id}

返回 dataset 元数据和版本列表。

### GET /datasets/{dataset_id}/versions/{version}

返回完整 dataset version。

### GET /datasets/{dataset_id}/versions/{version}/cases

分页返回 cases。

## 11. Annotations

### POST /annotations

创建 annotation。

### GET /annotations

按 target 检索 annotations。

过滤条件：

- `target_type`
- `target_ref`
- `label`

## 12. Champions

### GET /champions

返回当前所有 profile/project 的 champion 映射。

### GET /champions/{profile}/{project}

返回某个 profile/project 当前 champion。

## 13. Gate Policies

### GET /gate-policies

返回所有 gate policies。

### POST /gate-policies

创建 gate policy。

### GET /gate-policies/{policy_id}

返回单条 policy。

### POST /gate-policies/{policy_id}/evaluate

对某次 run 或 benchmark 执行 gate 评估。

请求字段：

- `target_type`
- `target_ref`

## 14. Integrations

### GET /integrations

返回集成配置状态。

### POST /integrations/{name}/test

执行 health check。

首批集成目标：

- `otlp`
- `phoenix`
- `langfuse`
- `object_store`

## 15. Service 层映射

API 不应直接调用 CLI。建议拆成：

- `profile_service`
- `candidate_service`
- `run_service`
- `score_service`
- `benchmark_service`
- `dataset_service`
- `gate_service`
- `integration_service`

CLI 只做参数解析和输出格式化。

## 16. v1 非目标

- GraphQL
- WebSocket 实时推送
- 细粒度对象级权限控制
- 跨区域分布式调度
- 外部平台 webhook 双向同步
