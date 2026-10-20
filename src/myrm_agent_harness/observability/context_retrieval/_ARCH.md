# observability/context_retrieval/

## 架构概述

上下文检索决策树与剪枝可观测性框架层，对标字节跳动火山引擎 OpenViking 的检索过程可观察理念，为分层知识检索与长程记忆搜索提供白盒化下钻决策树（RetrievalTreeNode）、剪枝判定留痕（PruningReason）与完整检索轨迹快照（VisitedPathTrace）。上级文档：[../_ARCH.md](../_ARCH.md)。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `models.py` | 模型 | 检索下钻树节点、剪枝原因枚举与全景轨迹数据契约 | ✅ |
| `tracer.py` | 引擎 | 上下文检索过程白盒化跟踪器与聚合快照构建器 | ✅ |
| `__init__.py` | 门面 | 模块对外公共符号门面统一导出 | ✅ |
