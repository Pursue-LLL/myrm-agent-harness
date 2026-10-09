# handoff/

## Overview
Strongly typed cross-agent/cross-session handoff protocol with atomic exactly-once claim and durable session finalizer.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public interface for agent handoff management and session finalization. | ✅ |
| `engine.py` | Core | Unified facade for agent handoff management, exactly-once claim, and session finalization. | ✅ |
| `finalizer.py` | Core | Session finalizer responsible for extracting and persisting durable handoffs upon session close. | ✅ |
| `handoff_store.py` | Core | Persistent storage backend for agent handoff packets. | ✅ |
| `state_machine.py` | Core | State machine governing exactly-once claim and state transitions for agent handoffs. | ✅ |
| `types.py` | Types | Type definitions for cross-agent/cross-session typed handoff protocol. | ✅ |

## Key Dependencies

- External libraries: `pydantic`
