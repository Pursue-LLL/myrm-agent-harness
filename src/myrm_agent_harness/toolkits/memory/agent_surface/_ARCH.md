# agent_surface/

## Overview

Agent-visible memory I/O layer: LangChain tools, MCP adapter, recall sanitize SSOT,
citations bridge, corpus policy, and wiki/memory write boundary.

Parent index: [../_ARCH.md](../_ARCH.md). System design: [../MEMORY_SYSTEM.md](../MEMORY_SYSTEM.md).

## File Index

| File | Role | Description | I/O/P |
| --- | --- | --- | --- |
| `__init__.py` | Package | Agent-facing memory I/O package marker. | — |
| `memory_agent_tools/` | Package | Agent tools: memory_search/save/manage (factory, one module per tool, shared category mapping). | ✅ |
| `_memory_agent_tool_descriptions.py` | Core | LLM-visible tool description SSOT (EN/ZH). | ✅ |
| `memory_search_policy.py` | Core | Corpus ACL, write bounds, and optional wiki/sessions backends. | ✅ |
| `memory_search_execution.py` | Core | memory/wiki/sessions search execution with domain-scoped pruning and heuristic fallback. | ✅ |
| `memory_recall_formatting.py` | Core | Recall sanitize SSOT, save ack, source_error suffix. | ✅ |
| `memory_recall_budget.py` | Core | Recall output budget guardrails. | ✅ |
| `memory_citations.py` | Core | cited_memory_ids SSE bridge (sources via tool metadata → SourceTracker). | ✅ |
| `tool_result_sources.py` | Core | Pack/unpack metadata.sources for memory_search wiki/sessions results. | ✅ |
| `mcp_server/` | Package | MCP adapter (recall/list/store/manage), one module per tool plus per-request context. | ✅ |
| `wiki_memory_boundary.py` | Core | Wiki vs memory write boundary heuristics. | ✅ |
| `transient_fact_boundary.py` | Core | Transient business state memory write boundary heuristics. | ✅ |
| `write_failure_feedback.py` | Core | Model-facing result for a failed save/manage call: explicit "Not saved" rejection for write-scan rejections, protected-memory refusal text, generic fallback otherwise (shared by tools and MCP). | ✅ |
| `rule_write_boundary.py` | Core | Agent-facing rejection message for writes to user-protected (`is_user_protected`) memories; the guard itself lives in `MemoryManager.update_memory`. | ✅ |

## Key Dependencies

- `../manager.py`, `../types.py`, `../conversation_search/`
- `core`, `infra`, `utils`
