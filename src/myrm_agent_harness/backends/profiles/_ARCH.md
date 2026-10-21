# profiles/

## Overview
Agent Profile 契约。定义 AgentProfile 数据结构与 CRUD Protocol；存储实现由宿主提供。

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | 统一导出 Profile 模块公开 API | — |
| types.py | Core | AgentProfile / BuiltInAgent / CommandBinding (multi-skill bundle) 数据结构定义 | ✅ |
| protocols.py | Core | AgentProfileBackend Protocol（CRUD 契约） | ✅ |

## Dependencies
- `myrm_agent_harness.toolkits.memory.config` — AgentMemoryPolicy 类型
