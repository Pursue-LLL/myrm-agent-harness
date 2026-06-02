# session_notes/

## Overview
Real-time structured session notes. Asynchronously maintains notes during conversation, serving as zero-API-call summaries during compression. Injects a **HumanMessage** with `[System note: Session Notes Summary]` prefix when compacting — preserves prompt cache by not altering the SystemMessage prefix. Skipped on Resume/HITL for cache preservation. Calls `notify_compaction()` to reset cache-break detector baseline.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Real-time structured session notes. Asynchronously maintains notes during conversation, serving as z | ✅ |
| prompts.py | Core | Session Notes LLM prompt templates. Supports incremental merge (new messages + current notes) and fu | ✅ |
| schemas.py | Config | Session Notes type system foundation. Defines structured data models for notes, section templates, a | ✅ |
| trigger.py | Core | Dual-threshold trigger strategy: token growth + tool call count. Suppresses updates during prolonged tool usage (>35 calls) to avoid cache breaks in unproductive loops. | ✅ |
| updater.py | Core | Session Notes core update engine. Manages the async update lifecycle: incremental merges, periodic f | ✅ |

## Key Dependencies

- `observability`
- `utils`
