# notification/

## Overview

Cross-channel notification delivery toolkit. Protocol-first: the application layer
implements `NotificationSender`; the harness provides rate limiting and security.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `protocols.py` | Core | `NotificationSender` protocol contract | ✅ |
| `types.py` | Core | `NotifyTarget`, `NotifyResult`, `NotifyToolConfig`, `NotifySessionState` | ✅ |
| `tool.py` | Core | `create_channel_notify_tool` agent tool factory | ✅ |
| `__init__.py` | Package | Public exports | — |

## Dependencies

- No `agent/` imports (toolkits gate)
- Application layer injects concrete `NotificationSender` (e.g. server ChannelGateway)
