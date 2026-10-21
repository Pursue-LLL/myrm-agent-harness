# mcp_scope_gate/

## 架构概述

MCP 发现工具按数字员工/Agent 作用域严格隔离门禁（Employee/Agent-Scoped MCP Tool Discovery Gate）：
对标 StaffDeck PR #199 (`backend/app/a2a/codex_adapter.py`, `backend/app/agents/branching.py`)，杜绝多 Agent 协同体系中 MCP 外部工具被全局无差别广播或越权调用：
1. **显式策略绑定**：每个数字员工 / Agent Profile 声明自身绑定的 `allowed_mcp_servers` 与细粒度 `tool_allowlist_map`；
2. **动态发现过滤（Fail-Closed）**：在动态枚举 MCP 工具时，非授权 Server 或不在白名单内的工具自动从候选集物理裁剪遮蔽；若未配置策略，默认 Fail-Closed 拦截全部候选工具；
3. **调用时硬校验**：`ipc_proxy._check_scope_gate` 在每次 PTC 调用时用 `MCPIPCRequest.agent_id` 调用 `verify_tool_invocation`，防止通过模型幻觉或直接名称注入跨员工调用未授权工具，越权时抛出 `EmployeeToolScopeViolationError`；`agent_id` 由 `prepare_mixin` 从 `get_agent_id()` 注入，与会话 ID 分离。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 门面 | 统一导出数字员工 MCP 作用域门禁与领域类型 | ✅ |
| `types.py` | 核心 | 员工作用域策略、过滤判定结果与越权异常契约 | ✅ |
| `scope_gate.py` | 核心 | 线程安全策略注册、动态发现工具裁剪与调用权限门禁校验器 | ✅ |
