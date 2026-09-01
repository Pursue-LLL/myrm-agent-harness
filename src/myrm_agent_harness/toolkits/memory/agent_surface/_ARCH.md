# agent_surface/

## Overview

Agent-visible memory I/O layer: LangChain tools, MCP adapter, recall sanitize SSOT,
citations bridge, corpus policy, and wiki/memory write boundary.

Parent index: [../_ARCH.md](../_ARCH.md). System design: [../MEMORY_SYSTEM.md](../MEMORY_SYSTEM.md).

## File Index

| File | Role | Description | I/O/P |
| --- | --- | --- | --- |
| `__init__.py` | Package | Agent-facing memory I/O package marker. | — |
| `memory_agent_tools.py` | Core | Agent tool factory: memory_search/save/manage. | ✅ |
| `_memory_agent_tool_descriptions.py` | Core | LLM-visible tool description SSOT (EN/ZH). | ✅ |
| `memory_search_policy.py` | Core | Corpus ACL, write bounds, and optional wiki/sessions backends. | ✅ |
| `memory_search_execution.py` | Core | memory/wiki/sessions search execution. | ✅ |
| `memory_recall_formatting.py` | Core | Recall sanitize SSOT, save ack, source_error suffix. | ✅ |
| `memory_recall_budget.py` | Core | Recall output budget guardrails. | ✅ |
| `memory_citations.py` | Core | cited_memory_ids SSE bridge (sources via tool metadata → SourceTracker). | ✅ |
| `tool_result_sources.py` | Core | Pack/unpack metadata.sources for memory_search wiki/sessions results. | ✅ |
| `mcp_server.py` | Core | MCP adapter (recall/list/store/manage). | ✅ |
| `wiki_memory_boundary.py` | Core | Wiki vs memory write boundary heuristics. | ✅ |
| `transient_fact_boundary.py` | Core | Transient business state memory write boundary heuristics. | ✅ |

## Key Dependencies

- `../manager.py`, `../types.py`, `../conversation_search/`
- `core`, `infra`, `utils`
