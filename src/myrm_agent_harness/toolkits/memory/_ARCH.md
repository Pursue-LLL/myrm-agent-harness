# memory/

## Overview

Pluggable memory system for AI agents.

Detailed design: [MEMORY_SYSTEM.md](MEMORY_SYSTEM.md)

## File & Submodule Index

| File                     | Role     | Description                                                                                                   | I/O/P |
| ------------------------ | -------- | ------------------------------------------------------------------------------------------------------------- | ----- |
| __init__.py              | Package  | Pluggable memory system for AI agents.                                                                        | —     |
| _assistant_retrieval.py  | Internal | Two-Pass Assistant Retrieval for assistant-reference queries (MemPalace enhancement).                         | ✅    |
| adaptive.py              | Core     | Adaptive dual-channel selection logic. Analyzes query characteristics (token count,                           | ✅    |
| archival.py              | Core     | Provides ArchivalCandidate, ArchivalStrategy, TimeBasedArchivalStrategy.                                      | ✅    |
| backup.py                | Core     | Provides BackupMetadata, BackupResult, RestoreResult.                                                         | ✅    |
| cache.py                 | Core     | Memory query result caching with LRU eviction and auto-invalidation.                                          | ✅    |
| chunking.py              | Core     | Chunking utilities for ConversationMemory. Provides configurable strategies                                   | ✅    |
| compression.py           | Core     | Transparent payload compression and external BLOB storage for ConversationMemory raw_exchange fields.         | ✅    |
| config.py                | Core     | Memory configuration — functional switches and retrieval params only.                                         | ✅    |
| ephemeral.py             | Core     | Ephemeral and read-only memory managers for subagent isolation.                                               | ✅    |
| health.py                | Core     | Memory system diagnostics — instance-level health and maintenance reports.                                    | ✅    |
| intent_recognizers.py    | Core     | Query intent recognition for adaptive type weighting.                                                         | ✅    |
| manager.py               | Core     | Public import path for ``MemoryManager`` and memory error types. | ✅    |
| memory_agent_tools.py    | Core     | Agent memory tools: recall, save, manage. Includes write-quality guidance (when/what/how to save) in save description, recall context budget enforcement, and citation provenance with retrieval traces. | ✅    |
| memory_citations.py      | Core     | Citation/source bridge that converts recalled memories, retrieval traces, and conversation sources into UI-safe SSE metadata. | ✅    |
| memory_recall_budget.py      | Core     | Recall budget guardrails: limit normalization, output size accounting, and content truncation helpers.        | ✅    |
| memory_recall_formatting.py  | Core     | Recall formatting helpers: time filters, age labels, staleness checks, and channel provenance labels.         | ✅    |
| metrics.py               | Core     | Memory search quality metrics — lightweight, thread-safe counters.                                            | ✅    |
| observability.py         | Core     | Business-neutral memory operation, influence, retrieval trace, memory-space DTOs, and MemoryOperationSink protocol for app-layer dashboards and logs. | ✅    |
| cognitive/deriver.py     | Core     | Async Dialectic Reasoning Engine for implicit preference extraction.                                          | —     |
| query_analyzer.py        | Core     | Bilingual (EN/CN) query pattern recognition for temporal markers, person names, quoted phrases, preference queries, and assistant reference detection. Integrated into main retrieval path via search_service. | ✅    |
| query_sanitizer.py       | Core     | Agent Memory query preprocessing layer.                                                                       | ✅    |
| reliability.py           | Core     | Framework-safe memory reliability DTOs for probe results, repair plans, repair execution results, archive restore plans/results, import dry-run mappings, import plans, and recall benchmark summaries with IR metrics (ndcg, mrr, precision, latency percentiles). | ✅    |
| result_booster.py        | Core     | Result boosting for memory retrieval (MemPalace enhancement).                                                 | ✅    |
| security.py              | Core     | Public facade for memory security preflight scanning used by app-layer import and archive restore review flows. | ✅    |
| retriever.py             | Core     | RRF retriever for multi-source memory search. rank(): geometric scoring → correction-chain suppression → hard cutoff (min_relevance_score) → MMR → normalization. fuse(): RRF scoring → correction-chain suppression → MMR → normalization (hard cutoff omitted — RRF scores are rank-based, absolute thresholds inapplicable). | ✅    |
| session.py               | Core     | Conversation-level memory buffer. Buffers memory writes during a session and batch-flushes                    | ✅    |
| setup.py                 | Core     | Out-of-the-box local memory factory. Combines SQLite and embedded Qdrant to provide zero-config               | ✅    |
| signals.py               | Core     | Context signal calculator for memory retrieval scoring. Provides normalized [0,1] factors                     | ✅    |
| text_utils.py            | Core     | Unified multi-language tokenization for memory retrieval. Uses re.UNICODE                                     | ✅    |
| tool_capture.py          | Core     | Tool-scoped memory capture hook. Detects user edicts and repeated tool failures, auto-creates procedural rules. | ✅    |
| types.py                 | Core     | Memory type system foundation. Provides MemoryType, MemoryStatus, exact mutation outcome DTOs, profile attribute snapshots, BaseMemory and all typed memory schemas. | ✅    |

| Submodule   | Description                                                                       |
| ----------- | --------------------------------------------------------------------------------- |
| \_manager/  | Composable ``MemoryManager`` implementation modules.                               |
| \_internal/ | Internal implementation details — not part of the public API.                     |
| cognitive/  | Cognitive memory consolidation layer.                                             |
| conversation_search/ | Protocol-backed conversation recall tool, source refs, scope/lineage DTOs and MemoryManager provider. |
| graph/      | Graph Store — async graph storage with SQLite CTE backend.                        |
| integration/ | Integration Memory — pulls data from third-party services into local memory for cross-source semantic retrieval. |
| protocols/  | Storage-agnostic protocols for the memory system.                                 |
| relational/ | Relational Store — abstract interface and SQLite implementation.                  |
| strategies/ | Optional memory strategies: forgetting, extraction, deduplication, consolidation, preference stability, recurrence-triggered consolidation. |
| proactive/ | Proactive follow-up track — LLM implicit commitment extraction, `CommitmentStore` protocol, heartbeat delivery. See [COMMITMENT_SYSTEM.md](proactive/COMMITMENT_SYSTEM.md). |
| session_post_process.py | Unified post-session task runner (memory consolidation + proactive extraction). | ✅ |

| File (additional) | Role | Description | I/O/P |
| --- | --- | --- | --- |
| mcp_server.py | Core | MCP server adapter: wraps MemoryManager as 4 MCP tools (memory_recall, memory_list, memory_store, memory_manage) for external agent access via Streamable HTTP. recall supports categories/time/profile, list supports overview + paginated enumeration, store supports 5 categories, manage supports update/delete/correct/rate. | ✅ |

## Key Dependencies

- `core`
- `infra`
- `utils`
