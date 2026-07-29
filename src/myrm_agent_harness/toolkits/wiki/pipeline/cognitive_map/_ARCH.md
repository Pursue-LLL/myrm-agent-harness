# cognitive_map/

## Overview
Deterministic OKF cognitive map writers for `wiki/index.md`, `wiki/log.md`, and `wiki/hot.md`.
Zero-LLM refresh after compile, maintain, import, pending approve, and repair-types events.
Hot context is consumed only inside `WikiQueryEngine.query()` — not injected into agent system prompts.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public exports for refresh service, events, and hot reader | ✅ |
| events.py | Types | `WikiMapEventType` enum (incl. `RAW_SUPERSEDE`) and `WikiMapEvent` dataclass for log entries | ✅ |
| snapshot.py | Core | Zero-LLM `HotSnapshot` builder and hot.md renderer | ✅ |
| writer.py | Core | Atomic index/log/hot writers, `read_hot_context`, stats helpers | ✅ |
| index_routing.py | Core | Parse/score `wiki/index.md`; `INDEX_ROUTING_SECTION`; CJK-aware terms via retrieval tokenizer | ✅ |

## Key Dependencies

- `core.structure` (WikiStructure paths, sidecar helpers, concept listing)
- `core.frontmatter_contract` (page type grouping for index.md)
