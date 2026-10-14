# runtime/context/session/

## Overview
Session-level context lifecycle domain: volume-backed pinned context files and checkpoint/message synchronization SSOT for rewind/truncate/edit-resend flows.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Aggregate facade re-exporting pins and continuity helpers | ✅ |
| session_context_pins.py | Core | Volume-backed pinned file registry (pinned_context_files.json per session) | ✅ |
| session_continuity.py | Core | Checkpoint/message SSOT for rewind/truncate/edit-resend flows | ✅ |
| event_sourcing_store.py | Core | Runtime context session event-sourcing persistence layer. | ✅ |

## Module Dependencies

- `langgraph`
- `pydantic`
