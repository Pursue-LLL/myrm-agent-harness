# workspace_arbitrage Architecture Documentation

## [POS]
所属模块：`myrm_agent_harness.agent.context_management.workspace_arbitrage`
核心职责：会话内联就地工作台挂件交互、跨模型成本-性能智能套利调度、双模人格温控修饰与反静默降级预算熔断防护套件。

## 模块结构
| 文件 | 职责 |
|---|---|
| `arbitrage_types.py` | 强类型契约、挂件规范、路由决策、人格温控配置与预算状态定义 |
| `inline_deck_manager.py` | 会话内联微型工作台挂件（Diff/Slider/Approval/Terminal）注册与交互状态机 |
| `cost_performance_arbitrage_router.py` | 任务复杂度启发式探测器、L1/L2 动态模型套利路由与无损升降级通道 |
| `dual_persona_switcher.py` | 严谨工作态与温暖陪伴态双模温控提示词修饰器与风格注入器 |
| `anti_downgrade_budget_guard.py` | 供应商模型指纹监控、多维联合劣化判定与软硬预算熔断防护盾 |
| `workspace_arbitrage_suite.py` | 统一协调门面 `WorkWithChatUnifiedWorkspaceDeckAndMultiModelCostArbitrageSuite` |
| `__init__.py` | 包级公共符号门面导出 |
