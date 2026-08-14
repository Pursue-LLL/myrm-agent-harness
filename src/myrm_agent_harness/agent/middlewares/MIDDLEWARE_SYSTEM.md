# Middleware System Design

> Agent 框架内建中间件栈。在 LangChain `AgentMiddleware` 链上实现安全、上下文、工具拦截、审批与并发控制；与用户可配 `hooks/` 互补（hooks=业务/用户生命周期，middlewares=框架内建逻辑）。

---

## 设计目标

1. **单一工具拦截点**：`tool_interceptor_middleware` 编排所有 guard，避免分散 patch
2. **可组合**：各 middleware 独立文件，通过 `_factory/builder.py` 或 Server 注入组装
3. **安全 fail-closed**：`safety_dispatcher` 未知工具默认串行；security 层验证 tool result
4. **Cache 安全**：context/progress/replan 类 middleware 通过 `request.override` 注入 HumanMessage，不污染 system 前缀

---

## 中间件栈（概念顺序）

```
请求进入 Agent 图
    │
    ▼
┌─────────────────────────────────────────┐
│ context_pipeline_middleware (context_pipeline/) │  ← 上下文压缩/摘要链
│ memory_context_middleware (memory_context/)  │  ← 用户记忆注入（编排）
│   └─ memory_context_format.py         │  ← stable/learned 格式化纯函数
│ progress_middleware / goal_focus_middleware │  ← todo 焦点 / active goal 提醒
│ moa_advisor_middleware (opt-in)             │  ← agent 环轻量顾问 fan-out
│ replan_middleware                         │  ← 动态重规划
│ GuardrailMiddleware (guardrails/)       │  ← 技能边界等
│ security_*_middleware                   │  ← 安全边界/护栏
│ subagent_limit / concurrency_limiter    │  ← 委派 fan-out 限制
│ tool_history_hygiene.py                 │  ← ToolMessage dedup + within/cross-turn tool_call_id re-id
│ dangling_tool_call_middleware           │  ← 悬空 tool_call 修复
│ skill_attenuation_middleware (tooling/)  │  ← skill attenuation + runtime intent gating
│ filesystem_search_middleware            │  ← glob/grep 注入
│ tool_interceptor_middleware (tooling/)  │  ← ★ 工具执行主拦截点
│   └─ tool_executor (timeout/retry)      │
│   └─ approval/ + approval_interception/ │  ← HITL 审批
│ completion_guard                        │  ← 完成门控 + 外部证据门控 + 混合消息 guard
│ rate_limit                              │  ← Provider 429 主动节流
│ concurrency/ (safety_dispatcher + router)│  ← 工具并发安全路由
│ debug_logger_middleware (dev)           │
└─────────────────────────────────────────┘
    │
    ▼
  ToolNode / LLM
```

实际顺序以 `_factory/builder.py` 与 Server `factory.py` 装配为准；上图为逻辑分层。

---

## 子系统

| 子目录/文件 | 职责 |
|-------------|------|
| `tooling/` | 工具执行子系统：`tool_interceptor_middleware.py`（唯一编排入口；GraphInterrupt on stuck）、`tool_executor.py`（超时、重试、指数退避）、`tool_history_hygiene.py`（within-AIMessage re-id → ToolMessage keep-last dedup → cross-turn re-id；导出 `sanitize_tool_history()`）、`dangling_tool_call_middleware.py`（修复 strict provider 400）、`skill_attenuation_middleware.py`（skill attenuation + runtime intent-aware narrowing via `tool_choice.allowed_tools`）、`_tool_guards.py`/`_tool_helpers.py`（拦截辅助）、`_mutation_verifier.py`（文件变更 per-turn 验证 → SSE）、`_skill_failure_tracking.py`（技能失败事件跟踪）、`_tool_execution_lifecycle.py`（执行生命周期 hook）、`_runtime_tool_governance.py`（回合级工具面收敛 UI intent gate + readonly intent gate）、`_skill_tool_choice.py`（attenuation tool_choice 构建） |
| `_session_context.py` | Middleware 链共享 ContextVar |
| `approval/` | HITL 审批队列、batch、scheduler、correction_learning |
| `approval_interception/` | 审批拦截识别与注入 |
| `guardrails/` | Provider 链 + `GuardrailMiddleware` |
| `completion/` | 完成验证门子系统：`completion_guard.py`（代码任务完成验证门 + 外部证据缺失门控（web/browser/MCP：PTC bash `skills.mcp_*` 或 Direct FC `mcp__{server}__{tool}`；本地代码任务豁免）；Mixed Message Guard（保留变异调用 `is_mutating_tool` registry fail-closed + 交互/UI 承载工具，仅剥离确定无副作用无交互的只读工具；证据缺失时保留只读 tool_calls 防未核实内容直达用户））、`completion_guard_safety.py`（effectful 工具判定 SSOT，供 Mixed Message Guard 与 server Cron 后验消费） |
| `context_pipeline/` | `context_pipeline_middleware.py`（桥接 `context_management/pipeline/`）、`context_pipeline_helpers.py`（压缩意图/cache feedback/schema fingerprint） |
| `memory_context/` | `memory_context_middleware.py`（记忆上下文注入编排，首轮 LLM 前 idempotent 注入）、`memory_context_format.py`（注入格式化纯函数：stable SystemMessage / learned UNTRUSTED HumanMessage） |
| `concurrency/` | `concurrency_limiter.py`（按 agent_type Semaphore）、`concurrency_router.py`（智能并发路由：host-serial MCP lane + canonical path + `build_tool_execution_stages`）、`safety_dispatcher.py`（safe→concurrent / unsafe→serial） |
| `security/` | `security_boundary_middleware.py`（SECURITY_BOUNDARY_SYSTEM_RULES 注入）、`security_guardrail_middleware.py`（八层防御：circuit-breaker cognition / prompt guard / PII / leak / canary / history redact） |
| `subagent_limit_middleware.py` | 单轮 delegate 上限 |
| `filesystem_search_middleware.py` | 工作区搜索工具注入 |
| `progress_middleware.py` | 活跃 todo 焦点注入（末位 HumanMessage） |
| `goal_focus_middleware.py` | ACTIVE goal objective 注入（末位 HumanMessage；跳过 continuation/wrap-up 轮） |
| `moa_advisor_middleware.py` | Agent 环 MoA 顾问叠加（`moa_overlay_active` + 渐进 SSE `moa_ref_done` + 瞬态 HumanMessage 尾注入 + `privacy_filter` display/full 分流） |
| `replan_middleware.py` | 动态重规划循环 |
| `rate_limit.py` | Provider 级主动 sleep |
| `debug_logger_middleware.py` | 完整消息 debug 日志 |

---

## 与 hooks 边界

| | `middlewares/` | `hooks/` |
|--|------------------|----------|
| 配置方 | 框架/Server 装配 | 用户 profile YAML |
| 时机 | LangGraph middleware 链 | 生命周期事件（pre/post tool 等） |
| 典型用途 | 安全、压缩、审批 | 自定义脚本、业务回调 |

---

## 与 security 边界

- **检测/验证实现**在 `agent/security/`（如 `tool_result_validator`）
- **middleware 层**只做编排与注入；`middlewares/__init__.py` 再导出部分 security 符号供便捷 import

---

## 扩展指南

1. 新 guard → 独立模块，由 `tool_interceptor_middleware` 注册顺序
2. 新 middleware → 独立文件 + `_ARCH.md` 行 + 本文档栈说明
3. 禁止在 middleware 内写业务 REST/OAuth 逻辑 → Server `AgentExtension`

---

## 参考资料

- [middlewares/_ARCH.md](_ARCH.md) — 完整文件清单
- [context_management/CONTEXT_MANAGEMENT_SYSTEM.md](../context_management/CONTEXT_MANAGEMENT_SYSTEM.md)
- [security/SECURITY_SYSTEM.md](../security/SECURITY_SYSTEM.md)
