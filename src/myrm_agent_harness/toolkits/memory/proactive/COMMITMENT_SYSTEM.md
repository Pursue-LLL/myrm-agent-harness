# Commitment System

## Design Goal

Detect implicit follow-up items from multi-turn conversations (events, deadlines, care
check-ins, open loops) and deliver them through a host-controlled store and scheduler.
The harness provides extraction and types only; persistence and UI live in the host app.

## Architecture

```
Host app (session hook, REST API, heartbeat/cron)
        │
        ▼
Harness (CommitmentExtractor, types, CommitmentStore Protocol)
        ├── extraction.py   → LLM structured extraction (injected LLM callback)
        ├── types.py        → CommitmentRecord, CommitmentKind, lifecycle enums
        └── protocols.py    → CommitmentStore persistence contract
```

## Extraction Categories

| Kind | Example user signal |
|------|---------------------|
| `event_check_in` | "I have an interview on Friday" |
| `deadline_check` | "Report due Monday" |
| `care_check_in` | "My mom is sick" |
| `open_loop` | "Still waiting for the client reply" |

## Host Integration

1. After a conversation turn batch, call `CommitmentExtractor.extract()` with messages and an async LLM function.
2. Implement `CommitmentStore` (SQLite, Postgres, etc.) in the host layer.
3. On heartbeat or cron ticks, call `list_due()` and deliver `suggested_text` to the user channel.
4. Expose list/dismiss/snooze APIs for a settings panel if desired.

## Boundaries

- **Harness**: extraction engine, Pydantic models, `CommitmentStore` Protocol — zero `agent/` imports.
- **Host**: when to extract, where to store, delivery channel, rate limits, GUI.
- **Not for**: explicit user-scheduled reminders (use cron/kanban in the host instead).
