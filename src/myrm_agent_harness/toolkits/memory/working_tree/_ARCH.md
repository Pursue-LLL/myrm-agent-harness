# working_tree/

## 架构概述

基于上海交通大学 2026 最新 ReTree 范式（arXiv:2608.10676v1）构建的拓扑树状自纠错工作记忆引擎。
彻底解决长程多跳搜索中的“上下文无界爆炸”与“错误事实级联污染”两大核心缺陷。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
| --- | --- | --- | --- |
| `__init__.py` | 核心 | 模块入口与公共类型导出 | ✅ |
| `models.py` | 核心 | 强类型数据模型与 DTO 契约（节点、有界摘要、冲突类型、修订审计） | ✅ |
| `tree.py` | 核心 | EvidenceTree DAG 容器、依赖传递遍历、子树投影与 KV Cache 友好切片 | ✅ |
| `detector.py` | 核心 | FastContradictionDetector 两阶段轻量冲突与时态演化初筛/Fast-LLM仲裁 | ✅ |
| `engine.py` | 核心 | TreeRepairEngine 原子四步回溯修复、证据热替换、级联软剪枝与震荡阻尼 | ✅ |

## 架构边界与约束

- **零 agent 依赖**：纯净独立算法与数据结构，不反向依赖上层 agent 或业务层。
- **纯标准库与轻量依赖**：严禁引入本地 Heavy ML 框架（如 DeBERTa、PyTorch），三端（Local / Desktop / Cloud）同构秒级启动。
- **零 Action Tool 暴露**：工作记忆管理属于元认知基础设施，不向大模型注册 Action Tool，避免浪费 Prompt 空间和污染决策空间。
- **前缀固化友好**：有界摘要切片稳定按时间戳正序输出，最大化大模型端 KV Cache 命中率。

