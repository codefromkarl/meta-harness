# ADR 0001: Artifact-First Source of Truth

状态：accepted

日期：2026-04-07

## 背景

Meta-Harness 当前已经围绕本地文件系统沉淀出以下能力：

- run metadata
- effective config
- task execution outputs
- trace events
- score reports
- candidate proposals

后续 roadmap 会引入：

- API / service 层
- 数据库索引层
- UI
- OTel / Phoenix / Langfuse 集成

如果不先冻结“事实源”，后续很容易把数据库或外部平台变成隐式主存储，破坏回放、归档和可迁移性。

## 决策

Meta-Harness 继续采用 artifact-first 模型：

- 文件系统中的 canonical artifacts 是事实源
- 数据库只做索引、聚合、权限和查询加速
- API 返回对象必须可追溯到 canonical artifacts
- 外部 observability / annotation / analytics 平台只做镜像与分析层

## 后果

正面结果：

- 本地运行不依赖数据库即可完成
- archive / compact / replay 语义清晰
- 外部集成失败不会破坏核心执行链路
- schema 演进更可控

代价：

- 需要维护文件到数据库的投影过程
- 查询复杂度会高于 database-first 平台
- 一些实时产品能力需要额外缓存或索引设计

## 实施要求

- 新增 service 层时，不允许只写数据库不写 artifact
- 新增外部集成时，不允许把外部 trace id 当作唯一主键
- 新增 gate / benchmark / dataset 能力时，必须定义对应 canonical artifact 或明确复用已有 artifact
