# compactor/

## Overview
Priority-aware message compression: four-level strategy (deduplicate → skip-compressed → truncate → remove) with structured offload, integrity enforcement, and smart fallback for extreme overflow.

## File Index

| File | Role | Description |
|------|------|-------------|
| `__init__.py` | Package | Re-exports public API. |
| `compactor.py` | Core | Main orchestrator: `should_compress`, `compress_messages_async`, `compress_tool_message_async`, `find_tool_message_pairs`. |
| `compact_rules.py` | Config | Per-tool compression rules (line-based format for easy grep). |
| `deduplication.py` | Utility | `deduplicate_tool_results` — hash-based duplicate detection. |
| `integrity_guard.py` | Guard | `ensure_tool_pair_integrity` — guarantees every retained AI tool call has a matching ToolMessage. |
| `pre_compact_context.py` | Helper | Preserves injected recall HumanMessage across compression/summarization paths. |
| `smart_fallback.py` | Fallback | Last-resort budget-aware degradation when essential content alone exceeds token budget. |
| `tool_stats.py` | Utility | `extract_tool_stats` — extracts structural stats from tool outputs. |

## Key Dependencies

- `..compression.compression_formatting` (format helpers)
- `..tool_call_groups` (cross-domain: group construction)
- `..priority_signals` (cross-domain: focus/goal matching)
- `...infra.schemas` (ContextConfig, CompactToolCall, etc.)
- `...infra.message_priority` (MessagePriority, classify_message_priority)
- `...pipeline.base` (ProcessorContext — used by pre_compact_context)
