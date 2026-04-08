# Meta-Harness Gate Policy v1

更新时间：2026-04-07

## 1. 目标

本文档定义 Meta-Harness 的第一版质量门策略，用于把当前 smoke / regression / nightly benchmark workflow 升级为正式的 gate model。

目标：

- 区分 smoke、regression、benchmark、promotion 四类门
- 把“测试通过”与“评测放行”分开建模
- 为后续 API / UI / CI 提供统一策略对象

## 2. 作用范围

Gate policy 作用对象：

- 单个 run
- benchmark experiment
- benchmark suite
- candidate promotion

## 3. 类型

v1 定义 4 类 policy：

1. smoke
2. regression
3. benchmark
4. promotion

## 4. 默认策略

## 4.1 Smoke

目标：

- 快速确认核心路径没坏

默认检查：

- trace 写入可用
- run execute 可用
- run score 可用
- run export-trace 可用
- dataset extract-failures 可用

对应当前 workflow：

- `.github/workflows/smoke.yml`

放行条件：

- 指定测试全部通过

## 4.2 Regression

目标：

- 确认核心运行时和优化逻辑无回归

默认检查：

- runtime
- command evaluator
- observe
- benchmark
- optimize
- failure index

对应当前 workflow：

- `.github/workflows/regression.yml`

放行条件：

- 指定测试全部通过

## 4.3 Benchmark

目标：

- 判断实验结果是否满足质量、稳定性和成本要求

建议输入：

- `benchmark_experiment`
- `baseline`
- `best_variant`
- `ranking_score`
- `stability_assessment`
- `delta_from_baseline`

默认条件：

- 至少一个 valid variant
- `best_variant` 的 `ranking_score` 不低于 baseline
- 若声明了稳定性策略，需满足 `meets_min_repeats`
- 若是高分变体，不得被判定为 `is_high_score_unstable`

## 4.4 Promotion

目标：

- 决定 candidate 是否能成为 champion

默认条件：

- 至少有 1 个证据 run
- 若属于 benchmark candidate，需有 benchmark summary 支撑
- 不允许从 failed 或 partial run 直接 promotion
- 需记录 promotion reason 和 evidence

## 5. 策略对象

建议 schema：

```json
{
  "policy_id": "default-regression",
  "type": "regression",
  "scope": {
    "profile": "*",
    "project": "*"
  },
  "conditions": [],
  "waiver_rules": [],
  "notification_rules": [],
  "enabled": true
}
```

## 6. 条件表达

v1 建议支持以下条件类型：

- `test_suite_passed`
- `score_metric_gte`
- `score_metric_lte`
- `composite_delta_gte`
- `ranking_score_gte`
- `stability_flag_is`
- `run_status_is`
- `benchmark_has_valid_variant`
- `evidence_run_count_gte`

示例：

```json
{
  "kind": "ranking_score_gte",
  "path": "best_variant.ranking_score",
  "value": 14.0
}
```

## 7. 豁免规则

v1 支持有限豁免：

- 单次人工豁免
- 指定分支豁免
- 指定实验豁免

要求：

- 必须记录操作者
- 必须记录原因
- 必须带过期时间或一次性作用范围

## 8. 执行结果

每次 gate 评估建议产出：

- `policy_id`
- `target_type`
- `target_ref`
- `status`
- `evaluated_at`
- `passed_conditions`
- `failed_conditions`
- `waived_conditions`
- `evidence_refs`

当前实现还会额外产出：

- `gate_id`
- `artifact_path`
- `history_path`

状态：

- `passed`
- `failed`
- `waived`

## 9. 与现有 CI 的映射

当前 CI:

- smoke
- regression
- nightly benchmark suite

v1 映射方式：

- CI workflow 仍执行 pytest
- pytest 结果作为 gate 输入之一
- benchmark / promotion 通过独立 gate engine 判定

当前工程补充：

- `gate evaluate --persist-result` 会写入 `reports/gates/<gate_id>.json`
- 同时追加 `reports/gates/history.jsonl`
- `workflow benchmark --gate-policy <policy_id>` 可在 benchmark 后自动执行 gate
- `waiver_rules` 可将匹配失败条件转为 `waived`
- `notification_rules` 可记录通知事件，并支持 `webhook` / `slack_webhook` 最小真实投递

说明：

- 现阶段不要求在 GitHub Actions 内立即实现完整 gate engine
- Phase 1 先定义对象模型和执行规则

## 10. 第一版实施顺序

1. 先把 smoke / regression / nightly workflow 映射成 policy metadata
2. 为 benchmark 输出增加 gate-friendly summary 字段
3. 为 candidate promote 增加 evidence 参数
4. 在 service 层增加 `evaluate_gate_policy(...)`

## 11. 非目标

以下不属于 v1：

- 复杂 DSL
- 多级审批流
- 风险评分模型
- 自动回滚执行器
- 跨仓库联动 gate
