# dynamic_workflow/topology_pruner/

## 架构概述

模型能力阶梯感知自适应编排拓扑修剪与折叠子系统（DSH 架构自适应范式）。
根据底层模型智能水平（Tier 1 SOTA 长推理 / Tier 2 强基模 / Tier 3 轻量小模型）和任务复杂度动态裁决：
将冗长的多子代理拓扑自适应折叠为单 Agent 深度推理直接执行（Direct Execution），大幅节省轮次延迟与 Token 浪费。
上级目录：[../_ARCH.md](../_ARCH.md)。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 门面 | 导出 ModelTierAdaptiveTopologyPruner、数据模型与单例入口 | ✅ |
| `types.py` | 契约 | 强类型数据模型：ModelIntelligenceTier、PruningStrategy、TopologyPruningEvaluation | ✅ |
| `pruner.py` | 核心 | 模型阶梯识别、任务复杂度分析、自适应折叠算法与 Token/轮次节省估算 | ✅ |
