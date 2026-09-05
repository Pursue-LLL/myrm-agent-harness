# memory/

## Overview

Pluggable memory system for AI agents.

Agent-visible I/O implementations live under ``agent_surface/``; root ``memory_*.py`` / ``mcp_server.py`` paths are stable import facades.

Detailed design: [MEMORY_SYSTEM.md](MEMORY_SYSTEM.md)

## File & Submodule Index

| File                     | Role     | Description                                                                                                   | I/O/P |
| ------------------------ | -------- | ------------------------------------------------------------------------------------------------------------- | ----- |
| __init__.py              | Package  | Pluggable memory system for AI agents.                                                                        | —     |
| manager.py               | Core     | Public import path for ``MemoryManager`` and memory error types. | ✅    |
| setup.py                 | Core     | Out-of-the-box local memory factory. Combines SQLite and embedded Qdrant to provide zero-config               | ✅    |
| types.py                 | Core     | Memory type system foundation. Provides MemoryType, MemoryStatus, exact mutation outcome DTOs, profile attribute snapshots, BaseMemory (with trace_id), and all typed memory schemas. | ✅    |
| config.py                | Core     | Memory configuration — functional switches and retrieval params only.                                         | ✅    |
| memory_agent_tools.py    | Facade   | Stable import path → ``agent_surface/memory_agent_tools.py``. | —     |
| _memory_agent_tool_descriptions.py | Facade | Stable import path → ``agent_surface/_memory_agent_tool_descriptions.py``. | — |
| memory_search_policy.py  | Facade   | Stable import path → ``agent_surface/memory_search_policy.py``. | — |
| memory_search_execution.py | Facade | Stable import path → ``agent_surface/memory_search_execution.py``. | — |
| memory_recall_budget.py  | Facade   | Stable import path → ``agent_surface/memory_recall_budget.py``. | — |
| memory_recall_formatting.py | Facade | Stable import path → ``agent_surface/memory_recall_formatting.py``. | — |
| memory_citations.py      | Facade   | Stable import path → ``agent_surface/memory_citations.py``. | — |
| mcp_server.py            | Facade   | Stable import path → ``agent_surface/mcp_server.py``. | — |
| wiki_memory_boundary.py  | Facade   | Stable import path → ``agent_surface/wiki_memory_boundary.py``. | — |
| transient_fact_boundary.py | Facade | Stable import path → ``agent_surface/transient_fact_boundary.py``. | — |
| _assistant_retrieval.py  | Internal | Two-Pass Assistant Retrieval for assistant-reference queries (MemPalace enhancement).                         | ✅    |
| adaptive.py              | Core     | Adaptive dual-channel selection logic. Analyzes query characteristics (token count,                           | ✅    |
| backup.py                | Core     | Provides BackupMetadata, BackupResult, RestoreResult.                                                         | ✅    |
| chunking.py              | Core     | Chunking utilities for ConversationMemory. Provides configurable strategies                                   | ✅    |
| compression.py           | Core     | Transparent payload compression and external BLOB storage for ConversationMemory raw_exchange fields.         | ✅    |
| ephemeral.py             | Core     | Ephemeral and read-only memory managers for subagent isolation.                                               | ✅    |
| health.py                | Core     | Memory system diagnostics — instance-level health and maintenance reports.                                    | ✅    |
| intent_recognizers.py    | Core     | Query intent recognition for adaptive type weighting.                                                         | ✅    |
| metrics.py               | Core     | Memory search quality metrics — lightweight, thread-safe counters.                                            | ✅    |
| observability.py         | Core     | Business-neutral memory operation, influence, retrieval trace (with typed stream warning codes), memory-space DTOs, and MemoryOperationSink protocol for app-layer dashboards and logs. | ✅    |
| query_analyzer.py        | Core     | Bilingual (EN/CN) query pattern recognition for temporal markers, person names, quoted phrases, preference queries, and assistant reference detection. Integrated into main retrieval path via search_service. | ✅    |
| query_sanitizer.py       | Core     | Agent Memory query preprocessing layer.                                                                       | ✅    |
| reliability.py           | Core     | Framework-safe memory reliability DTOs for probe results, repair plans, repair execution results, archive restore plans/results, import dry-run mappings, import plans, and recall benchmark summaries with IR metrics (ndcg, mrr, precision, latency percentiles). | ✅    |
| result_booster.py        | Core     | Result boosting for memory retrieval (MemPalace enhancement).                                                 | ✅    |
| security.py              | Core     | Public facade for memory security preflight scanning used by app-layer import and archive restore review flows. | ✅    |
| retriever.py             | Core     | RRF retriever for multi-source memory search with 3-tier deterministic tie-breaking (score descending -> hit_count descending -> id ascending) and white-box RecallDebugTrace (HitSource). rank(): geometric scoring → correction-chain suppression → hard cutoff → MMR → normalization. fuse(): RRF scoring → correction-chain suppression → MMR → deterministic normalization with hit attribution. | ✅    |
| session.py               | Core     | Conversation-level memory buffer. Buffers memory writes during a session and batch-flushes                    | ✅    |
| session_post_process.py  | Core     | Unified post-session task runner (memory consolidation + proactive extraction). | ✅ |
| signals.py               | Core     | Context signal calculator for memory retrieval scoring. Provides normalized [0,1] factors                     | ✅    |
| text_utils.py            | Core     | Unified multi-language tokenization for memory retrieval. Uses re.UNICODE                                     | ✅    |
| tool_capture.py          | Core     | Tool-scoped memory capture hook. Detects user edicts and repeated tool failures, auto-creates procedural rules. | ✅    |

| Submodule   | Description                                                                       |
| ----------- | --------------------------------------------------------------------------------- |
| agent_surface/ | Agent-visible I/O: tools, MCP, recall sanitize SSOT, citations, corpus policy, wiki boundary. See [agent_surface/_ARCH.md](agent_surface/_ARCH.md). |
| \_manager/  | Composable ``MemoryManager`` implementation modules.                               |
| \_internal/ | Internal implementation details — not part of the public API.                     |
| cognitive/  | Cognitive memory consolidation layer.                                             |
| conversation_search/ | Protocol-backed conversation recall tool, source refs, scope/lineage DTOs, **expand_message_id window**, format `message_id`, MemoryManager provider. |
| graph/      | Graph Store — async graph storage with SQLite CTE backend.                        |
| integration/ | Integration Memory — pulls data from third-party services into local memory for cross-source semantic retrieval. |
| protocols/  | Storage-agnostic protocols for the memory system.                                 |
| relational/ | Relational Store — abstract interface and SQLite implementation.                  |
| strategies/ | Optional memory strategies: forgetting, extraction, deduplication, consolidation, preference stability, recurrence-triggered consolidation, staleness review. |
| proactive/ | Proactive follow-up track — LLM implicit commitment extraction, `CommitmentStore` protocol, heartbeat delivery. See [COMMITMENT_SYSTEM.md](proactive/COMMITMENT_SYSTEM.md). |

## Key Dependencies

- `core`
- `infra`
- `utils`
