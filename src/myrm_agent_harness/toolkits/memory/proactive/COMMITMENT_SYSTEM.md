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
3. On heartbeat or cron ticks: expire stale items, enforce `max_per_day` via `count_sent_rolling`, then `list_due()` and deliver `suggested_text`.
4. Mark `SENT` only after the agent produces a non-`[SILENT]` heartbeat response (host delivery ack).
5. When delivery is skipped (`[SILENT]` or empty), snooze injected items for a cooldown (host default: 6h) instead of re-injecting every heartbeat tick.
6. Gate extraction and heartbeat injection on the user's memory enable setting (opt-in, default off).
7. Expose list/dismiss/snooze APIs for a settings panel if desired.

## Delivery Limits

| Parameter | Default | Role |
|-----------|---------|------|
| `max_per_day` | 3 | Rolling 24h cap on SENT items per agent/user |
| `max_per_heartbeat` | 3 | Max items injected per heartbeat run |
| `expire_after_hours` | 72 | Grace after `due_window.latest_ms` before auto-expire |
| `failed_delivery_snooze` | 6h | Host snooze after `[SILENT]` / empty heartbeat ack |

## Boundaries

- **Harness**: extraction engine, Pydantic models, `CommitmentStore` Protocol — zero `agent/` imports.
- **Host**: when to extract, where to store, delivery channel, rate limits, GUI.
- **Not for**: explicit user-scheduled reminders (use cron/kanban in the host instead).
