# ralph_loop/

## 架构概述

Ralph 式 Fresh-Agent 多轮循环执行模块（Topic 12 · 第 15 项）：基于 DeepSeek-Harness 与 DSH 五模式之 Ralph 模式，实现长任务每轮启动无历史会话（inheritsParentContext=False）的 Fresh Child Agent，依靠跨轮共享工作区物理文件与严格受限的结构化五字段（`status/summary/evidence/next_steps/blocker`，硬顶 1500 字符）交接信息流转，并强制实施至少尝试满三轮阻断防御规则（Min-3-Round Rule），杜绝早衰阻塞与上下文膨胀导致的注意力衰退。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 入口 | 模块门面与外部公开 API 导出 | ✅ |
| `types.py` | 核心 | 结构化五字段交接契约、轮次记录与会话配置数据模型（0 Any） | ✅ |
| `protocol.py` | 核心 | 五字段容量清洗与截断、Min-3-Round 阻断防御评估与 Fresh 启动提示词装配 | ✅ |
| `runner.py` | 核心 | Ralph 多轮循环生命周期协调器：轮次递进、交接归档与全局单例工厂 | ✅ |

## 依赖关系

- 上级模块：[../_ARCH.md](../_ARCH.md)
- 业务消费层：Server `app/services/agent/ralph_workflow_service.py`
