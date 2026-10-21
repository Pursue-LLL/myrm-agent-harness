# advisor_channel/

## 架构概述

双模型实时旁路军师评审通道模块（Topic 12 · 第 17 项）：对标 `oh-my-pi` (omp.sh) 核心机制，为智能体（Doer）挂载独立模型与专属 Context 窗口的 Advisor 军师角色，在不污染主智能体上下文的前提下，并行审查每轮 Tool Call 与计划意图，按 `aside`（静默旁白提示）、`concern`（潜在隐患预警）与 `blocker`（高危动作硬阻断熔断）三级分层实时注入纠偏，防范长任务注意力衰退、破坏性操作与逻辑跑偏。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 入口 | 模块门面与外部公开 API 导出 | ✅ |
| `types.py` | 核心 | 三级干预层级契约（aside/concern/blocker）、干预实体、配置与审查结果模型（0 Any） | ✅ |
| `engine.py` | 核心 | 双模型旁路军师实时审查引擎：快速规则探针、破坏性模式 fail-safe 阻断与结构化分级决策 | ✅ |

## 依赖关系

- 上级模块：[../_ARCH.md](../_ARCH.md)
- 业务消费层：Server `app/services/agent/advisor_channel_service.py`
