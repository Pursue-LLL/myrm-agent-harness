
# myrm_agent_harness/agent/goals/verification 模块架构

提供目标验收（Acceptance Criteria）相关的动态拦截与准则验证能力。支持在 Agent 判定完成时拦截并执行验证逻辑，返回逐条 pass/fail 结果供前端可视化展示。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| __init__.py | 辅助 | 模块导出 | ✅ |
| base.py | 核心 | 定义 `BaseCriterion`、`VerificationResult`、`AggregatedVerificationResult` 基类 | ✅ |
| gatekeeper.py | 核心 | `VerificationGatekeeper` 验证协调器，顺序执行准则，返回逐条结果含计时 | ✅ |
| shell.py | 核心 | `ShellCriterion` 实现，在沙箱内运行终端命令判定通过与否 | ✅ |
| semantic.py | 核心 | `SemanticCriterion` 实现，将判断任务委托给 Server 层的 GoalProvider | ✅ |

## 数据流
1. `VerificationGatekeeper.verify_all()` → `AggregatedVerificationResult`（含逐条 `VerificationResult`）
2. `continuation.py` 调用 `GoalProvider.record_acceptance_results()` 持久化到 `goal.metadata`
3. SSE `GOAL_STATUS` 事件通过 `goal.to_dict()` 自动携带 `metadata.acceptance_results` 到前端

## 模块依赖
- 强依赖 `myrm_agent_harness.toolkits.code_execution.executors.base` 的沙箱执行能力。