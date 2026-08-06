# strategies/

## Overview
Three-tier context reduction strategies: Filter, Compress, Summarize.

## File & Submodule Index

| File | Role | Description |
|------|------|-------------|
| `__init__.py` | Package | Namespace package. |
| `filter.py` | Facade | Tool result filter facade. Truncates large tool outputs and generates smart previews via structural extraction. |
| `tool_call_groups.py` | Shared | Cross-domain utility: `ToolCallGroup`, `build_tool_call_groups`. Used by compactor, filters, and infra. |
| `priority_signals.py` | Shared | Cross-domain utility: group-level focus/goal signal matchers. Used by compactor and retention_helpers. |

| Submodule | Description |
|-----------|-------------|
| `compactor/` | Priority-aware message compression: four-level strategy, smart fallback, integrity guard, deduplication, and pre-compact helpers. |
| `compression/` | Compression guards: anti-thrash protection, effectiveness tracking, and formatting utilities. |
| `filters/` | Content-type detection, structural and semantic filtering implementations. |
| `session_notes/` | Real-time structured session notes. Zero-API-cost compression source. |
| `summary/` | Summarization strategy: LLM-based structured summarize, quality audit, message reconstruction, prompt templates, circuit breaker, and progress timeout. |

## Key Dependencies

- `..infra` (schemas, message_priority, retention_helpers)
- `..pipeline` (ProcessorContext)
- `utils` (token counting, logging)
