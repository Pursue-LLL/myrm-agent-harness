# observability/turn_context_provenance/

## 架构概述

会话逐轮上下文注入来源清单、内容指纹快照与可复现审计套件。
针对每次智能体调用，旁路收集 System Prompt、Memory、Skill、MCP Server 与 Workspace File 等来源的 Chunk 清单，计算 SHA256 内容指纹与 Token 占用，并提供跨轮差异（Diff）比对，支撑问题复盘与工件模型溯源。

上级文档：[../_ARCH.md](../_ARCH.md)。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 门面 | 聚合导出注入来源分类、指纹快照模型与清单构建器 | ✅ |
| `models.py` | 模型 | 注入来源类型枚举、Chunk 节点、跨轮差异项与清单快照不可变数据模型定义 | ✅ |
| `manifest_builder.py` | 核心 | 上下文装配清单构建器，计算 SHA256 指纹与跨轮最小差异分析 | ✅ |
