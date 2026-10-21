# agent/sub_agents/multiplexer/

## 架构概述

持久化多智能体会话多路复用器（Agent Session Multiplexer）与跨智能体互视/指导机制（tmux 架构范式）。
提供多并发持久会话管理、环形日志切片缓冲、无头工作者标记、跨 Agent 互视（`inspect_agent_session`）与动态指导注入（`instruct_agent`）。
上级目录：[../_ARCH.md](../_ARCH.md)。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 门面 | 导出 AgentSessionMultiplexer、快照模型及 inspect/instruct 门面工具 | ✅ |
| `types.py` | 契约 | 强类型数据模型：MultiplexerSession、InspectSnapshot、InstructResult、AgentInstruction | ✅ |
| `session_multiplexer.py` | 核心 | 线程安全多路复用引擎：会话增删查、环形日志窗口、工件记录、互视快照与指令队列 | ✅ |
| `inspect_instruct_tools.py` | 工具 | LangChain 元工具工厂：`inspect_agent_session` 与 `instruct_agent` | ✅ |
