# event_log/

## Overview
Complements Checkpointer with full event history. Optional — omitting

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Complements Checkpointer with full event history. Optional — omitting | ✅ |
| analytics.py | Core | Designed for separation of concerns: | ✅ |
| analytics_queries.py | Core | Read-side analytics helpers for ``EventLogger``. | ✅ |
| cli_summary.py | Core | Provides generate_cli_summary. | ✅ |
| evidence_extractor.py | Core | Data mining engine for Task-Adaptive Context. Runs periodically in idle_tasks | ✅ |
| logger.py | Core | Integration façade. Injected into BaseAgent via ``event_log_backend`` param. | ✅ |
| protocols.py | Core | Protocol contract. Framework provides FileEventLogBackend; | ✅ |
| trace_builder.py | Core | Read-side aggregation logic. Merges llm_request + token_usage into LLMCallRecord with start/end times and prompt_preview. | ✅ |
| llm_observability.py | Core | Passive llm_request event recording with truncated prompt preview for replay. | ✅ |
| trace_types.py | Config | LLMCallRecord includes start_time, end_time, prompt_preview for replay timeline. | ✅ |
| types.py | Config | Single source of truth for event log data structures. | ✅ |

| Submodule | Description |
|-----------|-------------|
| backends/ | Event log backends — built-in storage implementations. |
| dataset_export/ | Export pipeline — convert traces to ShareGPT/Alpaca/OpenAI JSONL with PII redaction, quality filtering, and dedup. |

## Key Dependencies

- `infra`
- `utils`
