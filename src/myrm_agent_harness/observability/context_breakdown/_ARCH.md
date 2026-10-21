# Context Breakdown Architecture

## Overview
本子包实现上下文用量高精度七分类解析与 60%/90% 性能警戒线判定核心架构（`WorkBuddyContextUsageBreakdownHUD`），彻底解决真实库实测中 69% 记录系统/记忆/规则余量为 0 的黑盒痛点，对齐 WorkBuddy 与 dsh-context 双重最佳工程实践。

## Core Invariants
1. **真实注入标记全量解析**：
   - 彻底摆脱失效的 `<system_prompt>`、`<memory_context>` 假设，精准解析真实系统中的 `<user_memory_context`（记忆）、`<workspace_context` 与 `<sandbox_environment_snapshot`（工作区规则）、`<bound_skills>`（首条消息技能目录）、以及 `tool_results`（工具输出）。
2. **七分类结构化归因**：
   - 将上下文完整分解为：系统设定、长期记忆、工作区规则、技能目录、工具定义、工具返回、对话历史及残余余量。
3. **60% 与 90% 双警戒线机制**：
   - 60% 警戒线（WARNING_60）：进入注意力衰减区间，主动告警建议压缩上下文或新开会话；
   - 90% 警戒线（CRITICAL_90）：进入极高风险区间，提示系统将触发深度自动压缩或熔断；
4. **口径分离与锚定**：
   - 并列计算各分项估算值（Estimated ≈）与提供商上报实际总量（Provider Exact），杜绝数据失真。

## File Layout
| 文件 | 类型 | 职责 | 状态 |
| :--- | :--- | :--- | :--- |
| `models.py` | 核心实现 | `ContextBreakdownSnapshot`, `ContextCategoryShare`, `ContextAlertLevel`, `ContextBreakdownResolver` 决策解析器 | ✅ |
| `__init__.py` | 门面导出 | 聚合导出模块内所有模型与解析器类 | ✅ |
| `_ARCH.md` | 架构文档 | 模块定位、核心不变量与文件表 | ✅ |
