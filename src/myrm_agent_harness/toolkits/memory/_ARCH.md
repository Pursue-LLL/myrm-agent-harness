# memory/

## Overview

Pluggable memory system for AI agents.

Agent-visible I/O implementations live strictly under ``agent_surface/`` (tools, MCP server, search policies, and recall formatting). Obsolete root facades have been completely removed.

Detailed design: [MEMORY_SYSTEM.md](MEMORY_SYSTEM.md)

## File & Submodule Index

| File                     | Role     | Description                                                                                                   | I/O/P |
| ------------------------ | -------- | ------------------------------------------------------------------------------------------------------------- | ----- |
| __init__.py              | Package  | Facade that re-exports only the names production code imports; everything else is imported from its defining submodule. | —     |
| manager.py               | Core     | Public import path for ``MemoryManager`` and memory error types. | ✅    |
| setup.py                 | Core     | Out-of-the-box local memory factory. Combines SQLite and embedded Qdrant to provide zero-config               | ✅    |
| types.py                 | Core     | Memory type system foundation. Provides MemoryType, MemoryStatus, exact mutation outcome DTOs, profile attribute snapshots, BaseMemory (with trace_id), and all typed memory schemas. | ✅    |
| config.py                | Core     | Memory configuration — functional switches and retrieval params only.                                         | ✅    |
| threshold_strategy.py    | Core     | Adaptive similarity-threshold strategies: the protocol and the library-size based default used by `RetrievalConfig`. | ✅    |
| _assistant_retrieval.py  | Internal | Two-Pass Assistant Retrieval for assistant-reference queries (MemPalace enhancement).                         | ✅    |
| adaptive.py              | Core     | Adaptive dual-channel selection logic. Analyzes query characteristics (token count,                           | ✅    |
| backup.py                | Core     | Provides BackupMetadata, BackupResult, RestoreResult.                                                         | ✅    |
| compression.py           | Core     | Transparent payload compression and external BLOB storage for ConversationMemory raw_exchange fields.         | ✅    |
| consolidation.py         | Core     | Hyper Consolidation Memory Block: 会话终态将工作记忆提取为 ProceduralMemory（自愈避坑规程，内置纯净性守卫过滤先验与未解决假说）与镜像为 EpisodicMemory 的 TaskDigest 资产并持久落盘。 | ✅    |
| cube.py                  | Core     | 统一异构记忆 MemCubeEnvelope 泛型容器、LifecycleTier 与 StoragePolicy 定义，提供 SHA256 验签防篡改与活跃度保真能力。 | ✅    |
| domain_types.py          | Core     | Three-domain memory partitions (User, Assistant, Task) and 9 fine-grained categories with semantic classification heuristics. | ✅    |
| scheduler.py             | Core     | 多层记忆生命周期调度器 MultiTierMemoryScheduler，负责多介质路由、全量封箱导出与防篡改导入。 | ✅    |
| ephemeral.py             | Core     | Ephemeral and read-only memory managers for subagent isolation.                                               | ✅    |
| health.py                | Core     | Memory system diagnostics — instance-level health and maintenance reports.                                    | ✅    |
| hermes_bridge.py         | Core     | Hermes & OpenViking zero-friction memory migration parser and bridge for Markdown/JSON imports.              | ✅    |
| intent_recognizers.py    | Core     | Query intent recognition and deterministic sub-graph router (5 query intents, ReDoS safety, zero-token cost). | ✅    |
| metrics.py               | Core     | Memory search quality metrics — lightweight, thread-safe counters.                                            | ✅    |
| observability.py         | Core     | Business-neutral memory operation, influence, retrieval trace (with typed stream warning codes), memory-space DTOs, and MemoryOperationSink protocol for app-layer dashboards and logs. | ✅    |
| query_analyzer.py        | Core     | Bilingual (EN/CN) query pattern recognition for temporal markers, person names, quoted phrases, preference queries, and assistant reference detection. Integrated into main retrieval path via search_service. | ✅    |
| query_sanitizer.py       | Core     | Agent Memory query preprocessing layer.                                                                       | ✅    |
| reliability.py           | Core     | Framework-safe memory reliability DTOs for probe results, repair plans, repair execution results, archive restore plans/results, import dry-run mappings, import plans, typed recall warning codes (MemoryGatherWarningCode), and recall benchmark summaries with IR metrics (ndcg, mrr, precision, latency percentiles). | ✅    |
| result_booster.py        | Core     | Result boosting for memory retrieval (MemPalace enhancement).                                                 | ✅    |
| security.py              | Core     | Public facade for memory security preflight scanning used by app-layer import and archive restore review flows. | ✅    |
| retriever.py             | Core     | RRF retriever for multi-source memory search with 3-tier deterministic tie-breaking (score descending -> hit_count descending -> id ascending) and white-box RecallDebugTrace (HitSource). rank(): geometric scoring (type-prior preservation & L1-normalized dynamic multipliers) → correction-chain suppression → hard cutoff → MMR → normalization. fuse(): RRF scoring → correction-chain suppression → MMR → deterministic normalization with hit attribution. | ✅    |
| retriever_scoring.py     | Core     | Per-candidate scoring mixed into `MemoryRetriever`: geometric signal fusion plus keyword, temporal and pattern boosts. | ✅    |
| session.py               | Core     | Conversation-level memory buffer. Buffers memory writes during a session and batch-flushes; refuses scan-blocked content when it is added (`MemoryTaintedError`) | ✅    |
| session_post_process.py  | Core     | Unified post-session task runner (memory consolidation + proactive extraction). | ✅ |
| signals.py               | Core     | Context signal calculator for memory retrieval scoring. Provides normalized [0,1] factors                     | ✅    |
| text_utils.py            | Core     | Unified multi-language tokenization for memory retrieval. Uses re.UNICODE                                     | ✅    |
| memory_search_policy.py   | Facade   | Facade re-exporting memory_search_policy from agent_surface for harness surface.                               | —    |

| Submodule   | Description                                                                       |
|-------------|-----------------------------------------------------------------------------------|
| `tool_guidance` | Tool memory procedural contract & deterministic synthesis subpackage.          |
| agent_surface/ | Agent-visible I/O: tools, MCP, recall sanitize SSOT, citations, corpus policy, wiki boundary. See [agent_surface/_ARCH.md](agent_surface/_ARCH.md). |
| _manager/  | Composable ``MemoryManager`` implementation modules.                               |
| _internal/ | Internal implementation details — not part of the public API.                     |
| cognitive/  | Cognitive memory consolidation layer.                                             |
| conversation_search/ | Protocol-backed conversation recall tool, source refs, scope/lineage DTOs, **expand_message_id window**, format `message_id`, MemoryManager provider. |
| graph/      | Graph Store — async graph storage with SQLite CTE backend.                        |
| integration/ | Integration Memory — pulls data from third-party services into local memory for cross-source semantic retrieval. |
| protocols/  | Storage-agnostic protocols for the memory system.                                 |
| relational/ | Relational Store — abstract interface and SQLite implementation.                  |
| strategies/ | Optional memory strategies: forgetting, extraction, deduplication, consolidation, preference stability, recurrence-triggered consolidation, and staleness review. |
| proactive/ | Proactive follow-up track — LLM implicit commitment extraction, `CommitmentStore` protocol, heartbeat delivery. See [COMMITMENT_SYSTEM.md](proactive/COMMITMENT_SYSTEM.md). |
| working_tree/ | ReTree topological self-correcting tree working memory engine, evidence DAG container, two-stage contradiction detector, and cascading backtracking repair engine. See [working_tree/_ARCH.md](working_tree/_ARCH.md). |
| file_sync/ | Local-First Markdown File-as-Memory sync subsystem (LenientMarkdownParser, FileMemoryStore, MemoryAnchorFormatter, FileMemorySyncEngine). |
| external_providers/ | Pluggable external memory provider lifecycle & supersedes lineage pack: unified 5-stage contract (prefetch/inject/sync/extract/mirror), single active provider scheduling, 300ms circuit breaking, supersedes version chains, scope isolation, and 3D benchmark suite. See [external_providers/_ARCH.md](external_providers/_ARCH.md). |
| profile_notes/ | Dual-Layer Profile & Working Notes Memory Budget & Garbage Purge Guard: deterministic intake noise filtering (task progress, ephemeral numbers, error traces), dual-layer routing (USER <= 1375c, MEMORY <= 2200c), and multi-tier capacity watermark governance. |
| decay/ | Ebbinghaus Temporal Decay & Tiered Storage Lifecycle Engine: dynamic exponential decay scoring S(t) = I * exp(-lambda*dt) * (1 + alpha*ln(1+f)), RFM frequency boost, hot-warm-cold three-tier storage transitions, decay-aware blended retrieval reranking, and cold archive export/revival. |
| sovereign_migration/ | Sovereign Asset Package Cross-Machine Migration Protocol & One-Click Restore: portable bundle packaging (.myrmpkg), checksum verification, dynamic path relativization, atomic restoring, and competitor ingestion adapters (Hermes, Claude Code, Codex). |
| handoff/ | Strongly typed cross-agent/cross-session handoff protocol with atomic exactly-once claim and durable session finalizer. See [handoff/_ARCH.md](handoff/_ARCH.md). |
| onboarding/ | Onboarding insight sampling and first-encounter reporting for users migrating from other agent tools (sliding-window sampling, local redaction, fact distillation). See [onboarding/_ARCH.md](onboarding/_ARCH.md). |
| tool_guidance/ | Deterministic, cache-stable synthesis of procedural tool memory (traps) into bounded, zero-LLM tool guidance. See [tool_guidance/_ARCH.md](tool_guidance/_ARCH.md). |
| ephemeral_delta/ | In-memory, session-scoped transient buffer for prompt-cache-preserving deltas. See [ephemeral_delta/_ARCH.md](ephemeral_delta/_ARCH.md). |
| two_layer_dialectic/ | Dual-layer context injection engine preserving LLM Prompt Cache while resolving contradictions. See [two_layer_dialectic/_ARCH.md](two_layer_dialectic/_ARCH.md). |
| chunking/ | Incremental Sliding Window Markdown Chunker Suite: semantic sliding window with 80-token overlap, content-hash incremental diffing, and line-level pointers. See [chunking/_ARCH.md](chunking/_ARCH.md). |

## Key Dependencies

- `core`
- `infra`
- `utils`
