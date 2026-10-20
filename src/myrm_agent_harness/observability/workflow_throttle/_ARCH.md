# observability/workflow_throttle/

## Overview
海量并发 Agent 编排流水线实时 Token 燃速度量与阶梯式动态风控限流熔断引擎（Massive Workflow Token Burn Monitoring & Tiered Throttle Suite）。
结合滑窗算法对上百个并行子 Agent 的并发 Token 吞吐进行平滑燃速（Tokens/sec、Cost/hour）估算，并基于多阶段阶梯策略提供 50% 关注提示、80% 自适应模型降级（Adaptive Model Tiering）与并发限流、以及 100% 安全挂起保护（Safety Halt）。

## File & Module Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package Facade | 聚合导出燃速度量数据结构与多阶梯预算治理器。 | ✅ |
| `models.py` | Data Contracts | 定义 `BudgetLadderTier`、`WorkflowTokenBurnSample` 与 `BudgetLadderVerdict` 强类型契约。 | ✅ |
| `burn_governor.py` | Core Engine | 实现 `WorkflowTokenBurnGovernor`，负责滑动窗口燃速平滑统计、分级预算门禁裁决与限流因子动态计算。 | ✅ |

## Architectural Constraints
1. **零 Any 类型**：严格采用 Python 强类型与不可变 dataclass 契约。
2. **渐进式风控阶梯**：
   - `<50%`：`NORMAL`，全速运行；
   - `50%~80%`：`TIER1_NOTICE`，软提示，不截流；
   - `80%~100%`：`TIER2_DEGRADED`，`throttle_factor=0.5`，建议切换高性价比经济模型；
   - `>=100%`：`TIER3_SUSPENDED`，`throttle_factor=0.0`，无损挂起当前流水线，拒绝盲目透支扣款。
