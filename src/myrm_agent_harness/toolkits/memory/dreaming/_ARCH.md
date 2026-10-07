# dreaming/

## Overview
Grounded Dreaming and Surgical Session Memory Unlearning toolkit. Performs idle-time cross-session fact consolidation into the human-readable Dream Diary, and enables precision erasure of session-derived long-term memories without damaging raw chat logs.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Dreaming and precision unlearning component facade. | — |
| `models.py` | Core | Typed data models for dream diary entries, session fragments, and surgical unlearn audit reports. | ✅ |
| `engine.py` | Core | GroundedDreamingEngine — cross-session clustering, consensus reinforcement, and cognitive diary generation. | ✅ |
| `unlearn.py` | Core | SurgicalSessionMemoryUnlearner — precision erasure of session-derived vector indices and relational memories. | ✅ |
| `provenance.py` | Core | 记忆溯源与安全治理核心组件。为认知事实提供不可篡改的消息级双向溯源锚点、 阻断敏感凭据进入长期记忆的红线拦截器，以及杜绝跨项目上下文污染的作用域隔离门禁。 | ✅ |
| `scheduler.py` | Core | 记忆认知闲时整合调度中心。管理人类睡眠期记忆整合生理机制的后台模拟， 涵盖空闲交互超时判定、夜间定时窗口检测、REM 历史会话窗口回溯重放管道， 以及多项目隔离作用域做梦编排。 | ✅ |
