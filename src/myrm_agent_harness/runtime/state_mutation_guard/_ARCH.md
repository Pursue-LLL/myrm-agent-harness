# state_mutation_guard/

## Overview
会话状态并发变异写隔离、无锁冲突防护与事件管道生命周期安全包装套件.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | 会话状态并发变异写隔离、无锁冲突防护与事件管道生命周期安全包装套件. | — |
| `mutation_guard_types.py` | Core | 并发状态变异隔离与安全事件管道类型定义模块. | ✅ |
| `safe_event_channel.py` | Core | 生命周期受控安全事件管道模块. | ✅ |
| `session_state_mutator.py` | Core | 会话状态并发变异隔离与乐观并发仲裁合并模块. | ✅ |
| `task_lifecycle_sentinel.py` | Core | 异步 Task 生命周期强绑定上下文管理器模块. | ✅ |
