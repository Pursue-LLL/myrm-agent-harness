# agent_operations/

## Overview
Agent-Owned 多智能体协同操作体系（Agent-Owned Multi-Agent Operations Fabric）：
收敛并隔离多 Agent 协同中的 Provider 设置、模型参数、能力解析（Capability Resolver）、白名单（Allowlist）与操作级错误堆栈（Agent-Scoped Error Stack），维护标准化 List-form Agent 花名册（Agent Roster）。

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Facade | 门面导出 `AgentOwnedOperationsFabric`、`AgentOwnedExecutionContext`、`AgentProviderConfig`、`AgentScopedError`、`AgentRosterEntry` | — |
| `types.py` | Core | 核心数据模型：Agent 专属 Provider 配置、隔离错误栈模型、List-form 花名册条目与全生命周期持有上下文 | ✅ |
| `fabric.py` | Core | 协同操作总线：提供 Agent 上下文注册、能力解析校验、操作级错误隔离捕获、隔离执行沙箱与全景花名册导出 | ✅ |
