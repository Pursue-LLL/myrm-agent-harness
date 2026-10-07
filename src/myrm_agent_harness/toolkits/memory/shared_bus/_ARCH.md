# shared_bus/

## Overview
跨 Agent 共享记忆总线、并发连接池与方案否决账本模块。

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | 跨 Agent 共享记忆总线、并发连接池与方案否决账本模块。 | ✅ |
| `bus.py` | Core | 跨 Agent 共享记忆总线中枢，集成方案否决账本、并发连接池、背压守卫与强化衰减打分器。 | ✅ |
| `concurrency_pool.py` | Core | 多 Agent 共享并发连接池与内存背压守卫，保障高并发读写不锁死、内存不击穿。 | ✅ |
| `decay_scorer.py` | Core | 命中频次正向强化与时间半衰期衰减联合打分器，实现常用常新、长期未用平滑遗忘。 | ✅ |
| `negative_ledger.py` | Core | 方案否决与禁忌决策专属账本，前置拦截已被废弃的方案，彻底杜绝 AI 重复踩坑。 | ✅ |
| `types.py` | Types | 跨 Agent 共享记忆总线、并发连接池、背压守卫与方案否决账本的核心类型定义。 | ✅ |

## Key Dependencies

- None (self-contained within the package and the standard library)
