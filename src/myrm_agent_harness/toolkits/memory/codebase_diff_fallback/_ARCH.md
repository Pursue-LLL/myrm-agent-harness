# toolkits/memory/codebase_diff_fallback 模块架构

## 架构概述

代码库记忆大 Diff 分级降级引擎：对标 `codebase-memory #2269` 实践与 3000 文件硬上限截断防线，提供四层自适应漏斗降级流水线（Micro、Moderate、Large、Massive）、依赖锁定文件与静态资产噪音折叠、以及 API 截断平滑拓扑聚类保底，彻底杜绝大规模变更引起的 AST 内存溢出（OOM）、Token 预算击穿与进程挂死。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `models.py` | 核心 | 定义 `DiffVolumeTier`、`DiffCategory`、`DiffFileEntry`、`DirectoryAggregate`、`LargeDiffFallbackConfig`、`DiffFallbackVerdict` 等强类型领域模型 | — |
| `classifier.py` | 引擎 | `DiffPathClassifier`：路径类型智能识别（Lockfile、Generated、Assets、Docs、Config/Infra、CoreCode）与顶层目录提取 | — |
| `pipeline.py` | 引擎 | `LargeDiffFallbackPipeline`：四层漏斗判定、截断硬防护（3000-file cap）、分类噪音折叠与多级安全摘要生成 | — |
| `facade.py` | 门面 | `CodebaseDiffFallbackSuite`：统一协调门面，提供一键 diff 处理与 numstat 快速解析 | — |
| `__init__.py` | 入口 | 导出公共门面与数据模型 | — |

## 模块依赖

- 上游：`pydantic`
- 下游：`myrm-agent-server` 业务适配层、代码库增量索引管道
