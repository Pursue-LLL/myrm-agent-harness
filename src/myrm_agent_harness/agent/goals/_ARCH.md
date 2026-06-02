
# myrm_agent_harness/agent/goals 模块架构

Goal-based autonomous loop engine. Enables agents to pursue long-running objectives across multiple turns with strict budget control (4 dimensions: tokens, USD, time, turns), semantic completion auditing, and priority queueing for sequential execution.

## 核心概念

- **GoalBudget**: 4 维预算控制 — max_tokens / max_usd / max_time_seconds / max_turns
- **turns_used**: 精确的 turn 计数，每次 account_usage(turn_delta=1) 递增
- **ContinuationDecision**: 7-step guard chain 的结构化返回值，包含 verdict / reason / turns 指标
- **Semantic Judge**: 使用廉价 LLM 判断目标是否语义完成，三段式 prompt (角色 + DONE 条件 + JSON 输出格式)
- **resume_goal**: 恢复暂停/预算受限的 goal，可选重置 turns_used
- **Dynamic Subgoals**: 运行时动态追加的子目标，注入 Agent 的 Prompt 和 Semantic Judge 判断标准中，并享有最高优先级。
- **Constraints**: 硬约束列表 `constraints: list[str]`，每轮 continuation prompt 中以 "CONSTRAINTS (MUST NOT VIOLATE)" 区块醒目注入，judge criteria 中同步注入用于完成判定。
- **Priority Queue**: 当已有 ACTIVE goal 时，新 goal 自动进入 QUEUED 状态。当前 goal 终止后自动 dequeue 并启动下一个。支持拖拽排序和取消。
- **auto_approve**: 从队列 dequeue 出的 goal 跳过 PENDING_APPROVAL 人工审批阶段，实现无人值守串行执行。
- **Objective Hot-Edit**: 运行时修改 goal objective 文本，通过 SteeringToken 注入 `<untrusted_objective>` 标记的 steering 消息，agent 实时调整方向而不丢失进度。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| __init__.py | 辅助 | 模块导出 | ✅ |
| types.py | 核心 | Goal, GoalBudget, GoalStatus(含 QUEUED), ContinuationDecision, GoalExecutionSummary 等核心数据类型（含 priority, auto_approve, constraints 字段） | ✅ |
| protocols.py | 核心 | GoalProvider protocol — 含 account_usage(turn_delta), resume_goal, dequeue_next, get_queued_goals, create_goal(constraints), update_objective | ✅ |
| manager.py | 核心 | GoalManager 状态机 — 4 维预算检查、resume_goal、create_goal(自动入队)、dequeue_next、cancel_queued_goal、reorder_queue、update_constraints、update_objective、Prometheus metrics 记录 (goal_metrics) | ✅ |
| steering_prompts.py | 核心 | Goal 运行时 steering prompt 模板 — build_objective_updated_steering_message() 构建 objective 变更时注入的引导消息 | ✅ |
| storage.py | 核心 | SQLite 持久化 — 序列化/反序列化含 turns_used / max_turns / priority / auto_approve / constraints + 队列索引 | ✅ |
| continuation.py | 核心 | 7-step guard chain → 返回 ContinuationDecision，用 goal.turns_used | ✅ |
| audit.py | 核心 | 三段式 judge criteria + 行为引导 continuation prompt（含 Fidelity 防目标缩水、Evidence-based 防历史幻觉、Progress visibility 激活 planner_tool 进度推送、8 步 audit protocol、历史 learnings 注入） | ✅ |
| goal_interceptor.py | 核心 | Goal 拦截器，负责在执行前调用 PlannerAgent 生成计划；auto_approve=True 时跳过 interrupt | ✅ |
| verification/ | 核心 | 验收测试模块，提供准则解析(Gatekeeper)与运行时验证(Shell/Semantic)机制 | ✅ |
| GOAL_SYSTEM_DESIGN.md | 文档 | Goal 系统的详细设计文档 | - |
