# profiles/

## Overview
Agent Profile 存储后端。定义 AgentProfile 数据结构、CRUD Protocol 及开箱即用的 Local（YAML + SQLite）/ InMemory 实现。

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | 统一导出 Profile 模块公开 API | — |
| types.py | Core | AgentProfile / BuiltInAgent 数据结构定义 | ✅ |
| protocols.py | Core | AgentProfileBackend Protocol（CRUD 契约） | ✅ |
| local_backend.py | Impl | YAML 文件 + SQLite 索引的本地持久化实现 | ✅ |
| memory_backend.py | Impl | Dict-backed 内存实现（测试 / 临时场景） | ✅ |
| exceptions.py | Support | ProfileNotFoundError / ProfileAlreadyExistsError | ✅ |

## Dependencies
- `myrm_agent_harness.toolkits.memory.config` — AgentMemoryPolicy 类型
