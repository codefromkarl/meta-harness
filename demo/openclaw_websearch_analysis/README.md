# OpenClaw Websearch And Analysis Demo

这个 demo 展示如何把 `OpenClaw` 接入 `Meta-Harness`，并比较同一固定工作流在不同提示/预算策略下的收益差异。

目标流程：

1. 从 3 个打包在仓库内的 HTML 页面提取结构化信息
2. 汇总这些网页信息，生成 grounded 的比较结论
3. 对 `baseline`、`stable`、`high_accuracy` 三个 variant 做 benchmark

这里使用仓库内置的静态 HTML 页面，而不是直接访问公网，目的是：

- 降低一键 demo 的网络不确定性
- 让 benchmark 结果更容易复现
- 让 OpenClaw 只承担“解析页面内容并给出结构化答案”的责任

运行方式：

```bash
bash scripts/bootstrap.sh --require-openclaw
bash scripts/demo_openclaw_websearch_analysis.sh .openclaw-demo-output
```

主要产物：

- `.openclaw-demo-output/reports/benchmarks/`
- `.openclaw-demo-output/runs/`
- `.openclaw-demo-output/exports/`

关键配置入口：

- profile: [`../../configs/profiles/demo_openclaw.json`](../../configs/profiles/demo_openclaw.json)
- project: [`../../configs/projects/demo_openclaw.json`](../../configs/projects/demo_openclaw.json)
- benchmark: [`../../configs/benchmarks/demo_openclaw_websearch_analysis.json`](../../configs/benchmarks/demo_openclaw_websearch_analysis.json)
- task set: [`../../task_sets/demo/openclaw_websearch_analysis.json`](../../task_sets/demo/openclaw_websearch_analysis.json)
