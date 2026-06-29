# notification/

## Overview

Cross-channel **outbound notification toolkit** (generic capability package). Protocol-first:
the application layer implements `NotificationSender`; the harness provides types, target
resolution, rate limiting, and whitelist security.

This is a **toolkit module** (import Protocol/types/engine directly), not an agent-tool
module. The optional LangChain adapter `create_channel_notify_tool` in `tool.py` is one
consumption form — wired by the application layer when an agent should call it.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `protocols.py` | Core | `NotificationSender` protocol contract | ✅ |
| `types.py` | Core | `NotifyTarget`, `NotifyResult`, `NotifyToolConfig`, `NotifySessionState` | ✅ |
| `tool.py` | Adapter | Optional LangChain adapter — `create_channel_notify_tool` factory | ✅ |
| `__init__.py` | Package | Public exports (Protocol, types, optional adapter) | — |

## Dependencies

- No `agent/` imports (toolkits gate)
- Application layer injects concrete `NotificationSender` (e.g. server ChannelGateway)
