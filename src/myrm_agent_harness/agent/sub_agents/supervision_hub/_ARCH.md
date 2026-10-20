# supervision_hub/

## 架构概述

子代理实时监管抽屉引擎（Live Subagent Supervision Hub）——基于 `oh-my-pi` Agent Hub 架构设计，在多智能体并发任务（fan-out tasks）运行中提供高可见性与精准治理能力：
1. **Roster 实时花名册聚合**：跟踪所有并行 Worker 的活动状态（running/parked/stuck/done/failed/interrupted）、Token 消耗与运行耗时；
2. **Live Transcript 环形流缓冲区**：为每个 Subagent 维护线程安全的执行轨迹与工具调用日志（上限 100 条）；
3. **三大单点干预动作**：
   - `steer`：不打断父 Agent，向卡住或偏离方向的 Worker 注入实时纠偏指令；
   - `kill`：单点终止挂死/僵尸 Worker，父 Agent 继续执行其余分支；
   - `revive`：将已停靠（parked）或被意外中断的 Worker 从 Checkpoint 恢复入队。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 门面 | 统一导出 Hub 协调器、缓冲区与领域数据结构 | ✅ |
| `types.py` | 核心 | 状态枚举、Transcript 条目、Roster 项与动作结果契约 | ✅ |
| `transcript_buffer.py` | 核心 | 线程安全单 Worker 实时执行轨迹环形缓冲区（固定容量上限） | ✅ |
| `coordinator.py` | 核心 | 会话级花名册聚合、Transcript 收集与三大干预动作调度器 | ✅ |
