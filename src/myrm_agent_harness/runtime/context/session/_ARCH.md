# runtime/context/session/

## Overview
Session-level context lifecycle domain: active-session detection for runtime context cleanup, volume-backed pinned context files, and checkpoint/message synchronization SSOT for rewind/truncate/edit-resend flows.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Aggregate facade re-exporting session activity, pins, and continuity helpers | ✅ |
| session_activity.py | Core | Active-session ID loading for session-aware context cleanup | ✅ |
| session_context_pins.py | Core | Volume-backed pinned file registry (pinned_context_files.json per session) | ✅ |
| session_continuity.py | Core | Checkpoint/message SSOT for rewind/truncate/edit-resend flows | ✅ |

## Module Dependencies

- `langgraph`
- `pydantic`
