# Meta-Harness 发布素材模板

更新时间：2026-04-09

这是一份仓库维护者使用的发布模板，不是面向首次阅读者的主入口文档。

这份文档把对外发布最常用的三类素材放在一起：

1. GitHub Release 文案
2. 社媒首发文案
3. 一页发布清单

默认定位：

> Meta-Harness 是论文 *Meta-Harness: End-to-End Optimization of Model Harnesses* 的工程化实现，一个面向 AI workflow 优化的 artifact-first control-plane kernel。

## 1. GitHub Release 文案

建议标题：

```text
Meta-Harness 0.1.0: An Artifact-First Control Plane for AI Workflow Optimization
```

建议正文：

```md
Meta-Harness is now available as an open-source engineering implementation of the paper *Meta-Harness: End-to-End Optimization of Model Harnesses*.

This repository is not a one-off experiment script. It is an artifact-first platform kernel for optimizing AI workflows, where candidate, run, score, benchmark, proposal, shadow-run, and trace export all live inside the same replayable system.

## What is included

- A complete closed loop: `candidate -> run -> score -> benchmark -> propose -> shadow-run`
- Dataset lifecycle support: build, annotation ingestion, derive-split, and promotion
- OTLP / Phoenix / Langfuse request envelopes and integration export artifacts
- `lineage-first` governance semantics for candidate and loop artifacts
- Experimental product-facing surfaces around API, auth context, job execution, projection, and dashboard views

## Fastest way to try it

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
bash scripts/demo_public_flow.sh .demo-output
```

That single script runs a full public demo flow and produces:

- runs
- candidates
- proposals
- datasets
- loop artifacts
- benchmark report
- OTEL trace export
- artifact contract validation output

## Read this next

- README: repository overview
- `docs/research/paper-mapping.md`: how the repository maps to the paper
- `docs/guides/reproducibility.md`: shortest reproducible path
- `docs/reference/artifact-contracts.md`: canonical artifact semantics

## Current scope

Meta-Harness is ready to be shared as a research-engineering repository and platform kernel.

It is not yet a fully mature product platform. The following areas remain intentionally marked as experimental:

- protocol-grade OTLP transport
- official Phoenix / Langfuse SDK or hosted API integration
- multi-workspace / multi-role authorization
- real background queue scheduling and recovery
- projection-store integration into main query paths
- deeper dashboard drill-down for lineage / trace / export
```

## 2. 社媒首发文案

### 2.1 中文长版

```text
开源一个最近在做的项目：Meta-Harness。

它不是一个一次性 Agent 脚本，而是把 AI workflow 优化过程落成可回放 artifact 的 control-plane kernel。核心闭环是：

candidate -> run -> score -> benchmark -> propose -> shadow-run

这个仓库来自论文《Meta-Harness: End-to-End Optimization of Model Harnesses》的工程化实现。我们把论文里的 harness 优化思路落成了一套可运行、可比较、可归档的系统，主线聚焦在 artifact contract、dataset/proposal 生命周期和可复现的闭环。

如果只想看它能不能跑，最短路径就是：

bash scripts/demo_public_flow.sh .demo-output

跑完会直接得到 runs / candidates / proposals / datasets / loop artifacts / benchmark report / trace export / validation report。

适合：
- 持续优化 AI workflow / Agent 的工程团队
- 想把实验过程从“脚本 + 经验”变成“artifact + contract”的研究工程读者
- 想从论文思路继续往平台内核推进的开发者

仓库地址：
https://github.com/codefromkarl/meta-harness
```

### 2.2 中文短版

```text
开源 Meta-Harness：一个把 AI workflow 优化过程落成可回放 artifact 的 control-plane kernel。

不是一次性脚本，而是完整闭环：
candidate -> run -> score -> benchmark -> propose -> shadow-run

最短 demo：
bash scripts/demo_public_flow.sh .demo-output

适合做 Agent / workflow 持续优化、研究工程复现和平台内核扩展。

https://github.com/codefromkarl/meta-harness
```

### 2.3 英文短版

```text
Open-sourced Meta-Harness: an artifact-first control-plane kernel for AI workflow optimization.

It already ships a real loop:
candidate -> run -> score -> benchmark -> propose -> shadow-run

Fastest demo:
bash scripts/demo_public_flow.sh .demo-output

Built as an engineering implementation of the Meta-Harness paper, with lineage-first artifacts, request envelopes, and a reproducible optimization loop centered on replayable artifacts.

https://github.com/codefromkarl/meta-harness
```

## 3. 一页发布清单

发布前：

- README 首页、复现指南、发布清单、论文映射链接都可打开
- `bash scripts/demo_public_flow.sh .demo-output` 可跑通
- `reports/benchmarks/demo_public_budget_headroom.json` 仍存在
- `LICENSE` 存在且首页已引用
- 开源口径仍明确标注 experimental 边界

发布时：

- 贴 GitHub Release 文案
- 贴中文长版或短版社媒文案
- 确认仓库地址仍为 `https://github.com/codefromkarl/meta-harness`
- 如有截图，优先放 dashboard shell 或 demo 输出目录截图

发布后：

- 检查外部读者是否能按 README 跑通最短 demo
- 收集第一批 issue，优先分流到：
  - OTLP transport
  - Phoenix / Langfuse 正式接入
  - workspace / role model
  - background worker / recovery
  - projection-store query integration
  - dashboard deeper drill-down

## 4. 建议配图

如果只准备一张图，优先级建议是：

1. `.demo-output` 目录树截图
2. README 里的闭环架构图
3. dashboard shell 首页截图

如果只准备一句定位，建议直接用：

```text
An artifact-first control-plane kernel for AI workflow optimization.
```
