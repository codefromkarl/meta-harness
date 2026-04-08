# Meta-Harness 论文映射

更新时间：2026-04-07

## 1. 目标

本文档说明：

- `meta-harness` 与论文 *Meta-Harness: End-to-End Optimization of Model Harnesses* 的关系
- 当前仓库哪些部分是论文思想的直接工程化落地
- 哪些部分是工程扩展，而不是论文原始内容的逐句实现

## 2. 论文核心命题

论文的核心命题可以概括为三点：

1. 需要优化的不只是模型或 prompt，还包括围绕模型运行的 harness
2. harness 的改进应建立在可比较、可评分、可回放的实验循环上
3. 历史执行结果、候选变体和优化提案，应成为下一轮搜索的输入

## 3. 当前仓库的对应实现

### 3.1 Harness 作为优化对象

论文概念：

- harness 不只是 prompt，而是信息组织、检索、执行与输出流程

仓库对应：

- `configs/profiles/`
- `configs/projects/`
- `candidates/<candidate_id>/effective_config.json`
- `candidates/<candidate_id>/code.patch`

工程含义：

- 一个 harness variant 可以是 config patch，也可以是 code patch
- variant 会被物化成 candidate，并进入统一执行与评分流程

### 3.2 可比较的实验循环

论文概念：

- 候选变体需要进入重复、可比较的评测回路

仓库对应：

- `runs/<run_id>/`
- `score_report.json`
- `benchmark` / `benchmark-suite`
- `observe`

工程含义：

- `candidate -> run -> score -> benchmark`
- 所有关键对象都以 artifact 形式落盘
- benchmark 支持 baseline / variant / ranking / stability

### 3.3 外层优化搜索

论文概念：

- 利用历史结果生成下一轮候选

仓库对应：

- `optimize propose`
- `proposals/<proposal_id>/proposal.json`
- `optimize materialize-proposal`
- `shadow-run`

工程含义：

- proposal 已成为独立 artifact
- 可以先提出 proposal，再决定是否物化为 candidate
- proposer 目前有两类：
  - 内建 failure-family / architecture recommendation 路径
  - 外接 `proposal_command` 路径

### 3.4 数据集飞轮

论文相关命题：

- 优化和评测需要依赖不断沉淀的数据集

仓库对应：

- `datasets/<dataset_id>/<version>/dataset.json`
- `manifest.json`
- annotation ingestion
- hard_case / adversarial split derivation
- dataset promotion

工程含义：

- dataset 不再只是 task set 的一次性附属
- dataset version、annotation、split、promotion 已有最小 artifact 闭环

## 4. 工程扩展部分

以下能力属于工程扩展，不是论文标题本身就直接要求的内容：

- artifact-first filesystem contract
- benchmark suite / stability / cost ranking
- gate policy / champion promotion
- white-box audit evaluator
- API / service 层
- dataset promotion target artifact

这些扩展的目的，是把论文中的优化循环变成一个可复用的平台内核，而不是只停留在实验脚本层面。

## 5. 当前仍未完全落地的论文工程部分

这些能力对“论文工程实现”很重要，但仍未完全收口：

- evaluator 自身 tracing / profiling 深化
- proposer registry / proposal ranking
- OTLP / Phoenix / Langfuse 的真实 transport
- gate 的自动执行与完整治理流

## 6. 如何理解本仓库的定位

最准确的表述是：

> `meta-harness` 不是论文的最小复刻脚本，而是将论文的 harness 优化思想工程化后形成的 artifact-first eval control plane。

也就是说：

- 它保留了论文最核心的优化循环
- 同时向“平台内核”方向扩展了数据模型、artifact 和治理能力
