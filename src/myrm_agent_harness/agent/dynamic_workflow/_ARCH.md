# dynamic_workflow/ — Dynamic Workflow Engine

## Overview
The Dynamic Workflow Engine is an orchestration layer in Harness. It breaks the context limits of single-agent execution by dynamically generating Python orchestration scripts. These scripts run in the PTC (Programmatic Tool Calling) sandbox and spawn multiple sub-agents concurrently.

## Architecture

```
User Request (use_workflow=True)
       ↓
Server API (stream_loop.py)
       ↓
Dynamic Workflow Engine (__init__.py)
       ↓
LLM generates Python Script (using concurrent.futures & spawn_subagent)
       ↓
PTC Sandbox Execution
       ↓
SpawnSubagentTool (tools.py)
       ↓
WorkflowEventStore (store.py) — Checks SQLite for cached result
       ↓ (Cache Miss)
Parent Agent (_spawn_child())
       ↓
Subagent Completes → Saves to SQLite
       ↓
Python Script Aggregates Results
       ↓
Final Output to User
```

## File Index

| File | Role | Description |
|------|------|-------------|
| `__init__.py` | Engine | Core entry point (`run_dynamic_workflow_stream`). Prompts the LLM to generate the orchestration script. |
| `store.py` | Persistence | `WorkflowEventStore` provides SQLite-based Event Sourcing for durable execution and crash recovery. Uses the Harness unified SQLite hardening profile (`CACHE`). |
| `tools.py` | PTC Tool | `SpawnSubagentTool` bridges the PTC Python script to the Harness parent agent (`_spawn_child`), making it idempotent via the store and passing down context/tools. |
| `_ARCH.md` | Doc | This architecture document. |

## Key Design Decisions

1. **Code-as-Orchestrator**: Complex logic (loops, branches, parallelism) is pushed to Python code, keeping the LLM context clean.
2. **Durable Execution**: The SQLite Event Store guarantees that if the Python script crashes, restarting it will instantly replay completed sub-agent tasks from cache. This is powered by a deterministic `workflow_id` derived from the HTTP session's `chat_id` and `message_id`, ensuring absolute idempotency during network retries. Connections are hardened via the unified `harden_connection_sync(CACHE)` profile for WAL journaling, concurrent write safety, and proper fallback on filesystems that cannot host WAL.
3. **PTC Integration**: Leverages existing PTC infrastructure to expose the `spawn_subagent` capability to the generated script securely.
