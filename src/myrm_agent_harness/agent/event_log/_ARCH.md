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
| logger.py | Core | Integration façade. Injected into BaseAgent via ``event_log_backend`` param. | ✅ |
| protocols.py | Core | Protocol contract. Framework provides FileEventLogBackend; | ✅ |
| trace_builder.py | Core | Read-side aggregation logic. Merges llm_request + token_usage into LLMCallRecord with start/end times and prompt_preview. Propagates fault-side attribution (fault_side/error_kind/recovery_actions/diagnostic_result) into error entries and ToolCallRecord, and computes the first-irrecoverable point (earliest error after the last successful tool call). Pairs tool_start/tool_end by tool_call_id (fallback FIFO for legacy events) and carries message_id through to ToolCallRecord for instruction lineage. Read-side compatible with streaming `tasks_steps` events (`_handle_tool_calls` / `_handle_tool_result`): a step naming a tool is recorded as one lineaged ToolCallRecord, `*_error` steps close the matching open record by tool_name+messageId, and same-call events dedup across sources. | ✅ |
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
