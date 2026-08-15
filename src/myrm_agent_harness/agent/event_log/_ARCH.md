# event_log/

## Overview
Complements Checkpointer with full event history. Optional — omitting

Detailed design: [EVENT_LOG_SYSTEM.md](EVENT_LOG_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Complements Checkpointer with full event history. Optional — omitting | ✅ |
| analytics.py | Core | Designed for separation of concerns: | ✅ |
| analytics_queries.py | Core | Read-side analytics helpers for ``EventLogger``. | ✅ |
| cli_summary.py | Core | Provides generate_cli_summary. | ✅ |
| evidence_extractor.py | Core | Data mining engine for trace evidence. Runs periodically in idle_tasks to feed skill evolution. | ✅ |
| logger.py | Core | Integration façade. Injected into BaseAgent via ``event_log_backend`` param. Persists error events from `stream_executor._emit_fatal_error` and `run_agent_loop`'s outer except (fault_side/error_kind/diagnostic_result/recovery_actions) so trace reconstruction sees LLM fatal errors. Recursively redacts PII/credentials in nested event payloads (tool args/results, error diagnostics) before persistence. | ✅ |
| protocols.py | Core | Protocol contract. Framework provides FileEventLogBackend; | ✅ |
| trace_builder.py | Core | Read-side aggregation logic. Merges llm_request + token_usage into LLMCallRecord with start/end times and prompt_preview. Propagates fault-side attribution (fault_side/error_kind/recovery_actions/diagnostic_result) into error entries and ToolCallRecord, and computes the first-irrecoverable point (earliest error after the last successful tool call). Pairs tool_start/tool_end by tool_call_id (fallback FIFO for legacy events) and carries message_id through to ToolCallRecord for instruction lineage. Read-side compatible with streaming `tasks_steps` events: a step naming a tool is recorded as one lineaged ToolCallRecord, `*_error` steps close the matching open record by tool_name+messageId, and same-call events dedup across sources. Error-status steps carry the tool_call_id (matching the success path) so they merge into the lifecycle `tool_failure` record instead of creating a duplicate. Event classification lives in `_process_event`; the pairing/LLM/tasks_steps concerns are delegated to the `_pairing`/`_llm`/`_tasks_steps` helper modules below. | ✅ |
| _common.py | Core | Shared helpers (`_str_or_none`, `_int_or_zero`) and the `_EVENT_META_KEYS` bookkeeping-key set used to strip event metadata from `input_data` — isolated so trace_builder and its `_pairing`/`_llm`/`_tasks_steps` helpers share them without circular imports. | ✅ |
| _pairing.py | Core | Tool-call pairing state machine: `_PendingTool` tracks a `tool_start` awaiting its terminal event; `_pop_pending` prefers exact `tool_call_id` match and falls back to FIFO-by-name for id-less legacy streams (concurrent same-name tools never cross-pair); `_find_tool_record`/`_find_open_record_by_context` resolve existing records (by id, or by tool_name+messageId for id-less error steps); `_replace_tool_record` swaps frozen records with changes. | ✅ |
| _llm.py | Core | LLM call aggregation: `_PendingLLMRequest` queues each `llm_request`; `_handle_token_usage` pairs it FIFO with the next `token_usage` event and builds the `LLMCallRecord` timeline (start/end, duration, ttft, token counts), recording orphaned usage with the event's own metadata. | ✅ |
| _tasks_steps.py | Core | Merges streaming `tasks_steps` progress events (see `streaming.event_handlers._handle_tool_calls`) into the trace: a step naming a tool is recorded immediately, terminal/error-status steps refine or close the record. `input_data` uses the shared `_EVENT_META_KEYS` filter; steps with a terminal-but-successful status record `success=True`. | ✅ |
| llm_observability.py | Core | Passive llm_request event recording with truncated prompt preview for replay. | ✅ |
| trace_types.py | Config | LLMCallRecord includes start_time, end_time, prompt_preview for replay timeline. ToolCallRecord carries fault_side + tool_call_id/message_id + security_labels; ExecutionTrace carries first_irrecoverable_index/timestamp for post-mortem attribution. | ✅ |
| types.py | Config | Single source of truth for event log data structures. | ✅ |

| Submodule | Description |
|-----------|-------------|
| backends/ | Event log backends — built-in storage implementations. |
| dataset_export/ | Export pipeline — convert traces to ShareGPT/Alpaca/OpenAI JSONL with PII redaction, quality filtering, and dedup. |

## Key Dependencies

- `infra`
- `utils`
