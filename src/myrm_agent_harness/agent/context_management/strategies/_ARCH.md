# strategies/

## Overview
Three-tier context reduction strategies: Filter, Compress, Summarize.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Three-tier context reduction strategies: Filter, Compress, Summarize. | — |
| compact_rules.py | Core | Tool-specific compaction rules. Defines per-tool compression strategies in a line-based format for e | ✅ |
| compactor.py | Core | Message compactor. Priority-aware three-tier compression strategy with configurable priority classification, structured offload results, and archive write/reuse telemetry. | ✅ |
| compression_formatting.py | Core | Compression formatting utilities. Provides shared formatting functions used by compactor.py and smar | ✅ |
| deduplication.py | Core | Provides deduplicate_tool_results. | ✅ |
| filter.py | Core | Tool result filter. Truncates large tool outputs and generates smart previews via structural extract | ✅ |
| integrity_guard.py | Core | Tool pair integrity guard for compacted message histories. | ✅ |
| priority_signals.py | Core | Priority signal helpers for compression planning. | ✅ |
| smart_fallback.py | Core | Smart fallback strategy for extreme token overflow scenarios. | ✅ |
| summarizer.py | Core | Context summarizer. Pure in-memory summarization strategy using structured summary schema, cache-safe message-prefix invocation, and aux-model context guard (auto-trims messages when summarizer LLM has a smaller context window). | ✅ |
| summary_auditor.py | Core | Quality gate for the summarizer.  Runs *after* LLM generates a summary | ✅ |
| summary_builder.py | Core | Message reconstruction after summarisation. | ✅ |
| summary_parser.py | Core | Summary parsing and message formatting utilities. | ✅ |
| summary_prompts.py | Core | Summarization prompt templates. Defines structured JSON output format (with Handoff fields) and merg | ✅ |
| pre_compact_context.py | Core | Pre-compaction protected-zone helpers. Preserves injected recall HumanMessage across Compress, SessionNotes, and Summarize rebuild paths. | ✅ |
| tool_call_groups.py | Core | Provides ToolCallGroup, build_tool_call_groups. | ✅ |
| tool_stats.py | Core | Provides extract_tool_stats. | ✅ |

| Submodule | Description |
|-----------|-------------|
| filters/ | Filters module. |
| session_notes/ | Real-time structured session notes. Asynchronously maintains notes during conversation, serving as z |

## Key Dependencies

- `runtime`
- `utils`
