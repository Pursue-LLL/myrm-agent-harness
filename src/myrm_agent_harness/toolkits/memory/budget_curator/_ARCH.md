# budget_curator/

## Overview
双轨冻结快照记忆预算仪表盘、原子批量腾挪策展操作符与长程会话回溯锚点套件。

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | 双轨冻结快照记忆预算仪表盘、原子批量腾挪策展操作符与长程会话回溯锚点套件。 | ✅ |
| `atomic_curator.py` | Core | 原子批量腾挪策展操作符与防混淆事务门禁，杜绝半成功坏账与子串匹配误删。 | ✅ |
| `budget_meter.py` | Core | 声明式记忆上下文预算计量器，渲染可视化预算仪表盘标头并监控容量水位。 | ✅ |
| `scroll_navigator.py` | Core | 长程会话回溯锚点协议，围绕指定消息 ID 穿透拉取前后连续上下文窗口。 | ✅ |
| `types.py` | Types | 双轨冻结快照记忆预算仪表盘、原子批量腾挪策展操作符与长程会话回溯锚点核心类型。 | ✅ |

## Key Dependencies

- None (self-contained within the package and the standard library)
