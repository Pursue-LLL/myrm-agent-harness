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
| integrity_gate.py | Core | Session enclosure and anti-silent-corruption verification gate (assert_log_integrity, verify_session_enclosure, verify_sequence_continuity). | ✅ |
| logger.py | Core | Integration façade. Injected into BaseAgent via ``event_log_backend`` param. Persists error events from `stream_executor._emit_fatal_error` and `run_agent_loop`'s outer except (fault_side/error_kind/diagnostic_result/recovery_actions) so trace reconstruction sees LLM fatal errors. Recursively redacts PII/credentials in nested event payloads (tool args/results, error diagnostics) before persistence. Implements non-destructive safe field capping (<=64KB) and runs session enclosure and continuity integrity gates on close. | ✅ |
| protocols.py | Core | Protocol contract. Framework provides FileEventLogBackend; | ✅ |
| trace_builder.py | Core | Read-side aggregation logic. Merges llm_request + token_usage into LLMCallRecord with start/end times, prompt_preview, attempt, and retry_count. Evaluates pure heuristic anomaly detection (tool_loop, token_surge, retry_backoff). Propagates fault-side attribution (fault_side/error_kind/recovery_actions/diagnostic_result) into error entries and ToolCallRecord, and computes the first-irrecoverable point. Pairs tool_start/tool_end by tool_call_id. | ✅ |
| _common.py | Core | Shared helpers (`_str_or_none`, `_int_or_zero`) and the `_EVENT_META_KEYS` bookkeeping-key set used to strip event metadata from `input_data`. | ✅ |
| _pairing.py | Core | Tool-call pairing state machine: `_PendingTool` tracks a `tool_start` awaiting its terminal event; `_pop_pending` prefers exact `tool_call_id` match. | ✅ |
| _llm.py | Core | LLM call aggregation: `_PendingLLMRequest` queues each `llm_request`; `_handle_token_usage` pairs it FIFO with the next `token_usage` event, extracting attempt and retry_count into `LLMCallRecord`. | ✅ |
| _tasks_steps.py | Core | Merges streaming `tasks_steps` progress events into the trace. | ✅ |
| _context_doctor.py | Core | Pure function token breakdown (system, chat, tool, file) and hotspot analyzer for execution traces. | ✅ |
| llm_observability.py | Core | Passive llm_request event recording with truncated prompt preview for replay. | ✅ |
| trace_types.py | Config | TraceAnomaly data structure for heuristic diagnosis. LLMCallRecord includes attempt and retry_count. ToolCallRecord carries fault_side + tool_call_id/message_id; ExecutionTrace carries anomalies and first_irrecoverable_index/timestamp. | ✅ |
| types.py | Config | Single source of truth for event log data structures. | ✅ |

| Submodule | Description |
|-----------|-------------|
| backends/ | Event log backends — built-in storage implementations. |
| dataset_export/ | Export pipeline — convert traces to ShareGPT/Alpaca/OpenAI JSONL with PII redaction, quality filtering, and dedup. |

## Key Dependencies

- `infra`
- `utils`
