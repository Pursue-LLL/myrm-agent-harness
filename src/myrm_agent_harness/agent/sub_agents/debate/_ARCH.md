# debate/

## 架构概述

多智能体动态协同工作间与辩论流任务看板联动引擎（Multi-Agent Workroom: Dynamic Group Chat, Leader Decomposition & Kanban Sync）。
支持将项目组织为多角色智能体协同工作间，实现 Leader 自动拆解任务、专员并行辩论与交叉质询、防无效车轮战（Max-Round 自动收敛）、并将子任务状态实时双向绑定至 Kanban 看板。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 入口 | 门面导出：导出状态枚举、数据契约、Kanban 桥接器与辩论管理器 | ✅ |
| `types.py` | 核心 | 强类型契约：定义 `DebateRole`、`DebatePhase`、`DebateSubtaskStatus`、`DebateParticipant`、`DebateTurn`、`DebateSubtask` 与 `DebateRoomState` | ✅ |
| `kanban_bridge.py` | 核心 | 看板映射桥接：双向映射辩论子任务状态与 Kanban 看板状态（`READY`, `RUNNING`, `BLOCKED`, `IN_REVIEW`, `COMPLETED`），提供标准看板任务创建载荷构建 | ✅ |
| `manager.py` | 核心 | 辩论生命周期管理器：管理工作间创建、任务拆解、专员论点发布、防死循环车轮战自动收敛控制与共识结算 | ✅ |
| `synthesis_pattern/` | 核心 | 分层 Leader 自动任务分治、专员调研质询与决策权衡矩阵收敛编排预设（三段式咨询模板、子任务拓扑注入、Trade-off Matrix 加权打分与胜出推荐） | ✅ |
