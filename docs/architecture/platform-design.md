# Meta-Harness 通用平台设计

## 1. 目标

本项目不是为单一任务重写一个 Agent，而是构建一个可复用的 **Meta-Harness 平台**。

平台负责统一：

- 任意 Harness 的运行编排
- 轨迹记录与归档
- 多目标评估
- 基于历史经验的候选优化
- 工作流级复用与项目级覆写

平台不直接承载某个任务的业务逻辑。任务差异通过 `Workflow Profile`、`Project Overlay`、`Evaluator` 和 `Contract` 注入。

## 2. 核心设计原则

1. **平台通用，任务专有**  
   平台只定义“怎么运行和优化 Harness”，不写死“任务应该怎么做”。

2. **文件系统是真相源**  
   每次运行的源码、配置、轨迹、评分都落盘，数据库只做索引和检索。

3. **配置分层继承**  
   使用 `platform defaults < workflow profile < project overlay < candidate patch < runtime flags` 的优先级。

4. **先离线进化，后在线自适应**  
   第一阶段只做离线优化回路，避免噪声直接污染线上默认配置。

5. **可回放、可比较、可回滚**  
   每个 candidate 和 run 都必须可追踪 lineage，可做 diff，可单独 replay。

## 3. 复用模型

平台分为三层复用：

### 3.1 平台层 `core`

所有工作流共享：

- 编排器
- 运行时上下文
- 轨迹记录
- 归档
- 评分聚合
- 优化器
- 检索与查询
- 契约校验
- 通用工具适配

### 3.2 工作流层 `workflows`

某类任务共享：

- 状态机
- Prompt 模板
- 允许的工具
- 默认评估器
- 任务专有 contract
- 默认预算与停止条件

示例：

- `demo_public`
- `coding_agent`
- `rag_reasoning`

### 3.3 项目层 `projects`

单个项目的轻量覆写：

- 命名与风格偏好
- 依赖黑白名单
- 仓库专属命令
- 领域术语
- 项目特有 evaluator 参数

示例：

- `demo_workspace`
- `legacy_monolith`

## 4. 核心对象

### 4.1 WorkflowProfile

描述一类任务如何运行：

- `name`
- `description`
- `prompts`
- `allowed_tools`
- `default_budget`
- `contracts`
- `evaluators`

### 4.2 ProjectOverlay

描述单项目如何覆写默认策略：

- `name`
- `workflow`
- `overrides`
- `repo_commands`
- `style_preferences`
- `dependency_policy`

### 4.3 Candidate

一个可执行 Harness 候选：

- `candidate_id`
- `workflow`
- `project`
- `config_patch`
- `lineage`
- `notes`

### 4.4 Run

某个 candidate 在一组任务上的一次执行：

- `run_id`
- `candidate_id`
- `profile`
- `project`
- `started_at`
- `output_dir`

### 4.5 Trace

任务执行轨迹：

- `step_id`
- `phase`
- `prompt_ref`
- `tool_call_refs`
- `retrieval_refs`
- `token_usage`
- `latency_ms`
- `status`

### 4.6 ScoreReport

标准化评估结果：

- `correctness`
- `cost`
- `maintainability`
- `architecture`
- `human_collaboration`
- `composite`

## 5. 目录结构

```text
meta-harness/
  configs/
    platform.json
    profiles/
      base.json
      demo_public.json
    projects/
      demo_public.json
  docs/
  src/
    meta_harness/
      cli.py
      schemas.py
      config_loader.py
      registry.py
      archive.py
      runtime.py
      candidates.py
      optimizer.py
      failure_index.py
  tests/
  runs/
  candidates/
```

第一阶段只实现最小子集：

- 配置分层加载
- profile 注册
- run 初始化与目录落盘
- 基础 run metadata 归档

第二阶段扩展：

- `TraceEvent` schema
- task 级 `steps.jsonl` 轨迹落盘
- evaluator 插件接口
- `score_report.json` 评分归档
- `command` 型 evaluator

第三阶段扩展：

- run archive 查询
- run diff
- 错误签名提取
- 相似失败查询

第四阶段扩展：

- workflow runtime
- candidate / champion 管理
- optimize propose / shadow-run skeleton

## 6. 运行模型

一次最小运行遵循：

1. 读取平台默认配置
2. 加载 `WorkflowProfile`
3. 叠加 `ProjectOverlay`
4. 生成 `RunSpec`
5. 创建 `runs/<run_id>/`
6. 写入 `run_metadata.json`
7. 写入 `effective_config.json`
8. 预留 `tasks/`、`artifacts/` 目录

当前阶段不实现在线 serving 和生产级 agent orchestration，但已具备离线 optimize loop。
当前 MVP 已具备最小运行闭环：`candidate -> run init/execute -> score -> archive -> failure query -> optimize propose/shadow-run -> optimize loop`。

## 6.1 当前已实现命令

- `mh profile list`
- `mh run init`
- `mh run trace`
- `mh run score`
- `mh run list`
- `mh run show`
- `mh run diff`
- `mh run failures`
- `mh run execute`
- `mh candidate create`
- `mh candidate promote`
- `mh optimize propose`
- `mh optimize shadow-run`
- `mh optimize loop`

## 7. 配置继承

配置合并规则：

- 字典递归合并
- 标量值后者覆盖前者
- 数组默认整体覆盖，不做拼接

示例：

```json
{
  "budget": {
    "max_turns": 12,
    "max_tokens": 120000
  },
  "retrieval": {
    "top_k": 8
  }
}
```

项目覆写可以只改一小部分：

```json
{
  "budget": {
    "max_turns": 16
  }
}
```

最终有效配置会变成：

```json
{
  "budget": {
    "max_turns": 16,
    "max_tokens": 120000
  },
  "retrieval": {
    "top_k": 8
  }
}
```

## 8. MVP 范围

### 8.1 第一阶段

- Python 项目骨架
- `profile list` CLI
- `run init` CLI
- 配置分层合并
- `runs/` 目录归档
- 基础单元测试

### 8.2 第二阶段

- `TraceEvent` 数据模型
- `steps.jsonl` 事件归档
- evaluator 注册与装载
- `run score` CLI
- `score_report.json` 输出
- `command_evaluators` 配置注入

### 8.3 第三阶段

- `run list/show/diff`
- `error_signatures.json`
- 基于关键词的相似失败查询

### 8.4 第四阶段

- `run execute`
- `candidate create/promote`
- `champions.json`
- `optimize propose`
- `optimize shadow-run`

### 8.5 暂不实现

- 实际模型调用
- 高级任务状态机
- 复杂评估器
- 自主优化闭环
- 数据库存储

## 9. 后续演进路径

`Search Loop Blueprint` 中定义的统一 loop 主轴、proposer 抽象、task plugin 和 integration outer-loop 复用已经在当前仓库中落地。当前阶段更值得继续推进的是生产化与治理收口：

- 更完整的 trace schema 与 loop lineage
- evaluator 扩展、多维评分与 Pareto 聚合
- 更丰富的 archive 检索与相似失败搜索增强
- 自动 shadow validation 策略
- promote 审批流
- 数据库存储 / 向量检索
- 人工审批 UI / dashboard

## 11. MVP 状态

当前实现已经满足平台级 MVP：

- 可以基于 profile/project 或 candidate 初始化 run
- 可以执行 JSON task set 并记录 `steps.jsonl`
- 可以进行基础评分与 command evaluator 评分
- 可以查询 run、比较 run、检索相似失败
- 可以创建 candidate、promote champion
- 可以基于失败样本生成优化候选，并做 shadow run
- 可以通过统一 `mh optimize loop` 入口运行离线 search loop，并写入 `reports/loops/`
- integration outer-loop 已复用统一 loop service，而不是单独维护完整迭代状态机

当前尚未覆盖的是“生产级”能力，而不是 MVP 缺口：

- 更强的模型驱动 proposer / agent loop
- 更强的优化策略
- 数据库存储和向量检索
- 人工审批 UI / dashboard

## 10. 当前实现策略

当前仓库为空，因此优先构建一个可以直接扩展的最小平台，而不是抢先写任务逻辑。

第一版将采用：

- Python
- Typer CLI
- Pydantic 数据模型
- pytest 测试
- JSON 配置和归档

这样后续新增工作流时，只需要补充 profile 和 overlay，不需要重写平台内核。
