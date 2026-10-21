# diagnostic_stream/

## Overview
run-stream 协议诊断事件分离与正常消息流解耦（Run-Stream Diagnostic Event Separation）核心子包。
打破传统 Agent 流式输出中重试告警、上下文滑窗截断、MCP 延迟突增与沙箱退避等内部诊断事件混入用户聊天气泡的污染痛点，在协议层与调度层实现物理双轨流式分发（`channel="message"` vs `channel="diagnostic"`），保障面向用户的回答纯净自然，同时赋予开发者面板与 ACP 会话 Hook 毫秒级白盒洞察力。

## Architecture & Responsibilities

- `models.py`:
  - `DiagnosticSeverity`: 诊断严重等级枚举 (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`)；
  - `DiagnosticCategory`: 诊断领域枚举 (`RETRY`, `CONTEXT_TRUNCATION`, `MCP_LATENCY`, `SANDBOX_PRESSURE`, `MODEL_DEGRADE`, `CUSTOM`)；
  - `DiagnosticEvent`: 结构化诊断事件实体，包含时间戳、影响明细与错误代码；
  - `StreamPacket`: 双轨流数据包。
- `dispatcher.py`:
  - `DiagnosticStreamDispatcher`: 线程安全双轨多路复用派发器，支持独立的正轨用户消息订阅与旁路诊断订阅，提供历史过滤检索与多维分布统计。
- `__init__.py`: 统一门面导出。

## File Index

| File | Role | Description | I/O/P |
|---|---|---|---|
| `models.py` | 数据模型 | DiagnosticSeverity/Category 枚举与 DiagnosticEvent/StreamPacket 契约 | ✅ |
| `dispatcher.py` | 核心引擎 | 线程安全双轨多路复用派发器，杜绝诊断事件污染用户对话消息流 | ✅ |
| `__init__.py` | 模块入口 | 聚合导出核心模型与派发器接口 | ✅ |
