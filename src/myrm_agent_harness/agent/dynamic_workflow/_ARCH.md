# dynamic_workflow/ — Dynamic Workflow Engine

## Overview
The Dynamic Workflow Engine is the third-generation orchestration layer in Harness. It breaks the context limits of single-agent execution by dynamically generating Python orchestration scripts. These scripts run in the PTC (Programmatic Tool Calling) sandbox and spawn multiple sub-agents concurrently through the delegate path.

## Architecture

```
User Request (use_workflow=True)
       ↓
Server API (stream_loop.py → stream_lane_factory.py)
  - Budget gate: should_block_execution()
  - Token tracker: init_token_tracker() ... reset_token_tracker()
  - Agent factory: AgentFactory.create_general_agent(params)
       ↓
Dynamic Workflow Engine (__init__.py)
  - cancel_token checked at each phase boundary
       ↓
LLM generates Python Script (ORCHESTRATOR_PROMPT)
  - Error isolation templates (try/except per spawn)
  - Model tier guidance
  - Structured JSON output
       ↓
PTC Sandbox Execution
       ↓
SpawnSubagentTool (tools.py)
  - Delegates to parent_agent._spawn_child()
  - Full tool registry inherited from parent
  - cancel_token checked before each spawn
       ↓
WorkflowEventStore (store.py) — L2 persistent cache
  - Cache hit → skip spawn
  - Cache miss → spawn → save result
       ↓
Summarization LLM (SUMMARIZATION_PROMPT)
  - Aggregates stdout into user-readable Markdown
       ↓
SSE events (AgentEventType.MESSAGE / MESSAGE_END / STATUS)
  - Frontend renders progress steps + final Markdown
```

## File Index

| File | Role | Description |
|------|------|-------------|
| `__init__.py` | Engine | Core entry point (`run_dynamic_workflow_stream`). Prompts the LLM to generate the orchestration script, executes via PTC, then summarizes results. |
| `store.py` | Persistence | `WorkflowEventStore` provides SQLite-based Event Sourcing for durable execution and crash recovery. Uses the Harness unified SQLite hardening profile (`CACHE`). |
| `tools.py` | PTC Tool | `SpawnSubagentTool` bridges the PTC Python script to `parent_agent._spawn_child()` through the delegate path, inheriting full tool registry, catalog, and budget. |
| `_ARCH.md` | Doc | This architecture document. |

## Key Design Decisions

1. **Code-as-Orchestrator**: Complex logic (loops, branches, parallelism) is pushed to Python code, keeping the LLM context clean.
2. **Delegate Path Integration**: Sub-agents are spawned through `parent_agent._spawn_child()`, the same path used by `delegate_task_tool`. This inherits the full tool registry, catalog config, cancel_token, and budget — no "zero-tool" agents.
3. **Durable Execution**: The SQLite Event Store guarantees that if the Python script crashes, restarting it will instantly replay completed sub-agent tasks from cache. This is powered by a deterministic `workflow_id` derived from the HTTP session's `chat_id` and `message_id`, ensuring absolute idempotency during network retries. Connections are hardened via the unified `harden_connection_sync(CACHE)` profile for WAL journaling, concurrent write safety, and proper fallback on filesystems that cannot host WAL.
4. **PTC Integration**: Leverages existing PTC infrastructure to expose the `spawn_subagent` capability to the generated script securely.
5. **Aggregation Layer**: Raw stdout is summarized by a dedicated LLM call into user-readable Markdown, preventing raw script output from reaching users.
6. **Cancel Propagation**: `cancel_token` is checked at every phase boundary and passed to every `spawn_child()` call, ensuring the "Stop" button works.
7. **Budget & Cost Tracking**: Server brackets the DW execution with `should_block_execution()` (budget gate) and `init_token_tracker()` / `reset_token_tracker()` (cost tracking), matching the normal agent and consensus stream patterns.
8. **SSE Compatibility**: Events use standard `AgentEventType` values (`message`, `message_end`, `status`) so the frontend handler chain processes them correctly.
