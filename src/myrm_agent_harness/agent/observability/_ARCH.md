# observability/

## Overview
Framework-level observability layer. Business layer subscribes to EventBus

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Framework-level observability layer. Business layer subscribes to EventBus | ✅ |
| catchup.py | Core | Extracts structured summary (files touched, tools used, etc.) from agent messages for the Catchup feature. | ✅ |
| event_bus.py | Core | Framework-level event bus. Business layer subscribes for transport adapters. | ✅ |
| tool_call_broadcaster.py | Core | Framework-level Hook listener. Automatically publishes tool call events to EventBus | ✅ |
| types.py | Config | Pure data structure definitions for observability subsystem. | ✅ |

## Key Dependencies

- `backends`
- `utils`
