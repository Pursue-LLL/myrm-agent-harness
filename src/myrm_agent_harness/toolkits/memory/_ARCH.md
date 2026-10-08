# memory/

## Overview

Pluggable memory system for AI agents.

Agent-visible I/O implementations live strictly under ``agent_surface/`` (tools, MCP server, search policies, and recall formatting). Obsolete root facades have been completely removed.

Detailed design: [MEMORY_SYSTEM.md](MEMORY_SYSTEM.md)

## File & Submodule Index

| File                     | Role     | Description                                                                                                   | I/O/P |
| ------------------------ | -------- | ------------------------------------------------------------------------------------------------------------- | ----- |
| __init__.py              | Package  | Pluggable memory system for AI agents.                                                                        | —     |
| manager.py               | Core     | Public import path for ``MemoryManager`` and memory error types. | ✅    |
| setup.py                 | Core     | Out-of-the-box local memory factory. Combines SQLite and embedded Qdrant to provide zero-config               | ✅    |
| types.py                 | Core     | Memory type system foundation. Provides MemoryType, MemoryStatus, exact mutation outcome DTOs, profile attribute snapshots, BaseMemory (with trace_id), and all typed memory schemas. | ✅    |
| config.py                | Core     | Memory configuration — functional switches and retrieval params only.                                         | ✅    |
| _assistant_retrieval.py  | Internal | Two-Pass Assistant Retrieval for assistant-reference queries (MemPalace enhancement).                         | ✅    |
| adaptive.py              | Core     | Adaptive dual-channel selection logic. Analyzes query characteristics (token count,                           | ✅    |
| backup.py                | Core     | Provides BackupMetadata, BackupResult, RestoreResult.                                                         | ✅    |
| chunking.py              | Core     | Chunking utilities for ConversationMemory and extraction pipelines. Provides configurable strategies (fixed, turn, message, semantic, and episodes chunking via EpisodesChunker with idle-time gap detection and causal sliding overlap). | ✅    |
| cards.py                 | Core     | A-MEM card-box (Zettelkasten) network. Evidence-conclusion decoupling with EvidenceReference binding, bidirectional graph indexing (incoming_links), immutable evolution chain with lineage tracing, and knowledge subgraph traversal. | ✅    |
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
| mirror.py                | Core     | In-process dual-tier Hot/Cold memory cache with debounced asynchronous cold SQLite mirroring, starvation-proof hard timeout, failure rollback retry, and single-direction isolation. | ✅    |
| observability.py         | Core     | Business-neutral memory operation, influence, retrieval trace (with typed stream warning codes), memory-space DTOs, and MemoryOperationSink protocol for app-layer dashboards and logs. | ✅    |
| query_analyzer.py        | Core     | Bilingual (EN/CN) query pattern recognition for temporal markers, person names, quoted phrases, preference queries, and assistant reference detection. Integrated into main retrieval path via search_service. | ✅    |
| query_sanitizer.py       | Core     | Agent Memory query preprocessing layer.                                                                       | ✅    |
| reliability.py           | Core     | Framework-safe memory reliability DTOs for probe results, repair plans, repair execution results, archive restore plans/results, import dry-run mappings, import plans, typed recall warning codes (MemoryGatherWarningCode), and recall benchmark summaries with IR metrics (ndcg, mrr, precision, latency percentiles). | ✅    |
| result_booster.py        | Core     | Result boosting for memory retrieval (MemPalace enhancement).                                                 | ✅    |
| security.py              | Core     | Public facade for memory security preflight scanning used by app-layer import and archive restore review flows. | ✅    |
| retriever.py             | Core     | RRF retriever for multi-source memory search with 3-tier deterministic tie-breaking (score descending -> hit_count descending -> id ascending) and white-box RecallDebugTrace (HitSource). rank(): geometric scoring (type-prior preservation & L1-normalized dynamic multipliers) → correction-chain suppression → hard cutoff → MMR → normalization. fuse(): RRF scoring → correction-chain suppression → MMR → deterministic normalization with hit attribution. | ✅    |
| session.py               | Core     | Conversation-level memory buffer. Buffers memory writes during a session and batch-flushes                    | ✅    |
| session_post_process.py  | Core     | Unified post-session task runner (memory consolidation + proactive extraction). | ✅ |
| signals.py               | Core     | Context signal calculator for memory retrieval scoring. Provides normalized [0,1] factors                     | ✅    |
| text_utils.py            | Core     | Unified multi-language tokenization for memory retrieval. Uses re.UNICODE                                     | ✅    |
| tool_capture.py          | Core     | Tool-scoped memory capture hook. Detects user edicts and repeated tool failures, auto-creates procedural rules. | ✅    |
| tool_guidance.py         | Facade   | Facade re-exporting types and synthesis engine from `tool_guidance` domain subpackage.                         | ✅    |
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
| strategies/ | Optional memory strategies: forgetting, extraction, deduplication, consolidation, preference stability, recurrence-triggered consolidation, staleness review, and `four_layer_promotion` (Map-Reduce consolidation, tri-channel code assertions, and E->M->B anti-poisoning audit). |
| proactive/ | Proactive follow-up track — LLM implicit commitment extraction, `CommitmentStore` protocol, heartbeat delivery. See [COMMITMENT_SYSTEM.md](proactive/COMMITMENT_SYSTEM.md). |
| working_tree/ | ReTree topological self-correcting tree working memory engine, evidence DAG container, two-stage contradiction detector, and cascading backtracking repair engine. See [working_tree/_ARCH.md](working_tree/_ARCH.md). |
| governance/ | Unified four-dimensional memory governance engine (ProfileSlots, EventTimeline, DynamicFacts with 4-state reconciliation & TTL, bounded 2-hop SQLite CTE entity graph). See [governance/_ARCH.md](governance/_ARCH.md). |
| file_sync/ | Local-First Markdown File-as-Memory sync subsystem (LenientMarkdownParser, FileMemoryStore, MemoryAnchorFormatter, FileMemorySyncEngine). |
| prompt_cache_guard/ | In-Context Frozen Snapshot & Prompt Cache Stability Guard: immutable resident memory snapshotting, Read-Free toolsuite, zero-width Unicode filtering, and explicit capacity overflow gates. See [prompt_cache_guard/_ARCH.md](prompt_cache_guard/_ARCH.md). |
| external_providers/ | Pluggable external memory provider lifecycle & supersedes lineage pack: unified 5-stage contract (prefetch/inject/sync/extract/mirror), single active provider scheduling, 300ms circuit breaking, supersedes version chains, scope isolation, and 3D benchmark suite. See [external_providers/_ARCH.md](external_providers/_ARCH.md). |
| ripplemem/ | RippleMem Sparse Event Graph & Budgeted Active Recall Controller: normalized event units m=(r, v, p, l, t, c), dual-edge sparse graph indexing with super-node degree pruning & temporal decay, saturation fast-path gate, and bounded directional ripple spreading. |
| profile_notes/ | Dual-Layer Profile & Working Notes Memory Budget & Garbage Purge Guard: deterministic intake noise filtering (task progress, ephemeral numbers, error traces), dual-layer routing (USER <= 1375c, MEMORY <= 2200c), and multi-tier capacity watermark governance. |
| codegraph/ | CodeGraph Memory Asset & Pre-Modification Impact Analysis Engine: AST symbol topology extraction (classes, methods, functions, inheritance, calls), in-memory & SQLite persistent store with incremental synchronization, multi-hop BFS blast radius evaluation, and agent-facing risk prevention tool. |
| compaction/ | Token-Budget-Aware Codebase Semantic Memory Compaction Engine: AST-based and regex fallback code skeleton extractor (L1 signatures, L2 control flow, L3 full source), and dynamic budget-aware compactor with multi-tier adaptive downgrade. |
| decay/ | Ebbinghaus Temporal Decay & Tiered Storage Lifecycle Engine: dynamic exponential decay scoring S(t) = I * exp(-lambda*dt) * (1 + alpha*ln(1+f)), RFM frequency boost, hot-warm-cold three-tier storage transitions, decay-aware blended retrieval reranking, and cold archive export/revival. |
| evolution/ | Order-Invariant Memory Evolution & Causal Experience Gene Ledger: temporal order-invariance validation gates, asymptotic confidence decay and Darwinian gene reinforcement (proof_count), causal trial-error gene extraction (CausalGeneExtractor), and planning-stage mutation advice (ExperienceGeneLedger). |
| auto_recall/ | Targeted Experience Auto-Recall Trigger with Multi-Turn Dedup and Fail-Open Reranking Engine: 5 sensitive lifecycle triggers (task_start, skill_load, subagent_start, write_preflight, cron_start), 5-turn sliding window deduplication to prevent context fatigue, and SLA-bounded fail-open neural reranker fallback. |
| privacy_gate/ | Typed Memory Privacy Boundary & Allowlist Security Gate: static regex secret scanning (API keys, private keys, connection URIs, JWTs), .myrmignore exclusion and allowlist matching, safe semantic redaction, and hard veto enforcement. |
| drift_defense/ | Ground Truth Priority & Code Drift Stale Memory Defense: zero-LLM reference extraction, sub-5ms physical presence & symbol AST validation, prompt-level stale warning decoration, and confidence decay. |
| unload_guard/ | Desktop & WebUI Unload Graceful Flush Finalize Guard: zero-LLM crash-proof emergency snapshotting upon browser unload or window close, sub-millisecond markdown memorandum persistence, and startup restoration. |
| sovereign_migration/ | Sovereign Asset Package Cross-Machine Migration Protocol & One-Click Restore: portable bundle packaging (.myrmpkg), checksum verification, dynamic path relativization, atomic restoring, and competitor ingestion adapters (Hermes, Claude Code, Codex). |
| conflict_arbitration/ | Memory Conflict Semantic Arbitration & User-Confirmed Decision Freeze Gate: multi-source factual divergence detection (Merge vs Override vs Contradiction), human arbitration cards, cryptographic immutable freeze locks, and anti-tamper write gates. |
| openclaw_adapter/ | OpenClaw 2.0 Format Adapter & Crash Recovery Rescue Pipeline: multi-user & Swarm topology tree extraction, new SQLite/Memory schema mapping, read-only WAL isolation, integrity probe, and corrupted page auto-rescue. |
| dual_track_extraction/ | Dual-Track Memory Extraction Routing & Anti-Silent-Drop Gateway: dual-track classification (declarative facts vs procedural rules), automatic dispatch to ProceduralMemory, and transparent destiny reports defending against silent drop defects. |
| universal_mcp_bridge/ | Universal MCP Memory Bridge & External Client Config Generator: stdio/SSE dual-mode MCP server integration, plug-and-play client configuration generator (Claude Code, Cursor, VSCode/Cline, CodeBuddy, Hermes), unified user_id lease anchor, and instant bidirectional memory convergence. |
| vector_preflight/ | Vector Store Preflight Dimension Integrity & IPv4 Loopback Sanitizer: IPv4 loopback sanitization eliminating IPv6 ::1 container traps, preflight dynamic embedding dimension sampling, and rigid schema mismatch prevention. |
| self_verification/ | Memory Self-Verification Diagnostic Suite & Fact Update Benchmark: in-place fact mutation & contradiction elimination probe, zero-lexical-overlap semantic recall verification, procedural anti-silent-drop testing, and isolated sandbox execution with guaranteed rollback cleanup. |
| crystallization/ | Procedural Memory Crystallization Lifecycle & Self-Correction Governor: formation-stage two-factor importance gate (confidence x severity >= 0.70) filtering ephemeral noise, application-stage facet-scoped rule routing, and reflection-stage feedback loop penalizing same-session repeat errors with dynamic degradation and retirement. |
| intent_reflection/ | Lightweight Reflection Intent Filter & Playbook Activation Probe: tiered intent classification (Tier 0 Fast Path, Tier 1 Code Execution, Tier 2 Knowledge Content, Tier 3 Deep Reasoning), sub-millisecond heuristic bypass gating, sidecar neural probe delegation, and facet-scoped targeted playbook activation preventing context attention dilution and excessive vector retrieval. |
| override_stack/ | Playbook Dynamic User Override Stack & Ephemeral Bypass Gate: dynamic 3-level priority hierarchy (Level 1 Turn Prompt > Level 2 Session Decision > Level 3 Procedural Playbook), acute semantic contradiction detection, zero-mutation ephemeral bypass flagging, and transparent audit context notice injection preventing dogma-locked AI behavior. |
| persona_router/ | On-Demand Persona Skill & Anti-Pollution Context Router: persona-as-a-skill facet decoupling, intent-aware style suppression gate (100% zero-token suppression on technical CLI/code tasks), contextual persona injection for creative/business communication, and explicit /about-me directive handling preventing context attention dilution and token waste. |
| client_partition/ | Client-Isolated Workspace & Memory Namespace Partition Suite: memory scope level CLIENT derivation, zero-trust cross-client leakage firewall (CrossClientLeakGuard) screening retrieval candidates, and canonical containment workspace directory resolver (ClientWorkspaceResolver) preventing cross-client credential leaks and path traversal. |
| provenance_batch/ | Skill Memory Extraction Provenance Trace Link & Batch Learn Namespace Isolator: anchors extracted procedural rules to physical tool execution traces (ToolExecutionTrace) and turn snippets, and partitions batch learning IDs deterministically ({namespace}::{scope}::{raw_id}) eliminating cross-scope memory leakage and concurrent collision. |
| workspace_living/ | Living Workspace Governance & documentation synchronization toolkit (CausalIssueMerger, KnownIssueEntry, ADRMetadata, idempotent error signature deduplication). |
| action_impact/ | Future Action Impact Filtering Gate for Memory Extraction. See [action_impact/_ARCH.md](action_impact/_ARCH.md). |
| attribution/ | Full-Lifecycle Memory Attribution and Explainable Traceability Matrix. See [attribution/_ARCH.md](attribution/_ARCH.md). |
| budget_curator/ | 双轨冻结快照记忆预算仪表盘、原子批量腾挪策展操作符与长程会话回溯锚点套件。 See [budget_curator/_ARCH.md](budget_curator/_ARCH.md). |
| diagnostic/ | Automated Memory Diagnostic and Root Cause Inspector. See [diagnostic/_ARCH.md](diagnostic/_ARCH.md). |
| dialectic/ | 辩证推理深度用户表征与自适应会话步调动态节流套件。 See [dialectic/_ARCH.md](dialectic/_ARCH.md). |
| dreaming/ | Grounded dreaming (idle-time cross-session fact consolidation into the Dream Diary) and surgical session memory unlearning. See [dreaming/_ARCH.md](dreaming/_ARCH.md). |
| dual_tier/ | Dual-tier memory block engine package. See [dual_tier/_ARCH.md](dual_tier/_ARCH.md). |
| dual_track/ | Dual-Track Fact Decision and Verbatim Evidence Tracer Engine. See [dual_track/_ARCH.md](dual_track/_ARCH.md). |
| external_bridge/ | Bi-directional memory integration and safe prompt/skill file management for third-party developer agents (Cursor, Claude Code, Codex, Hermes, OpenClaw). See [external_bridge/_ARCH.md](external_bridge/_ARCH.md). |
| fact_editing/ | Hebbian Fact Injection and Linear Memory Editing package. See [fact_editing/_ARCH.md](fact_editing/_ARCH.md). |
| fast_ingest/ | Sub-5% Latency One-Pass Fast Ingestion and Async Deep Distillation Engine. See [fast_ingest/_ARCH.md](fast_ingest/_ARCH.md). |
| governor/ | Anti-Semantic-Aliasing memory governor and capacity management package. See [governor/_ARCH.md](governor/_ARCH.md). |
| graph_arbitration/ | Automated fact conflict arbitration state machine with causal lineage tracking. Dynamic edge weight decay and frequency reinforcement operator. See [graph_arbitration/_ARCH.md](graph_arbitration/_ARCH.md). |
| graph_rrf/ | Knowledge Graph and Vector Reciprocal Rank Fusion Memory Engine package. See [graph_rrf/_ARCH.md](graph_rrf/_ARCH.md). |
| handoff/ | Strongly typed cross-agent/cross-session handoff protocol with atomic exactly-once claim and durable session finalizer. See [handoff/_ARCH.md](handoff/_ARCH.md). |
| ltra/ | Listen-Translate-Remember-Act pipeline: quadruple fact distillation from diarized conversations with verbatim anchors, speaker alias resolution and confidentiality guards. See [ltra/_ARCH.md](ltra/_ARCH.md). |
| memops/ | MemOps 4-tuple standard semantic engine and zero-context benchmark package. See [memops/_ARCH.md](memops/_ARCH.md). |
| onboarding/ | Onboarding insight sampling and first-encounter reporting for users migrating from other agent tools (sliding-window sampling, local redaction, fact distillation). See [onboarding/_ARCH.md](onboarding/_ARCH.md). |
| paging/ | Agent-Driven Memory Paging with Hard Boundary Governance. See [paging/_ARCH.md](paging/_ARCH.md). |
| procedural/ | Procedural Memory and Engineering Workflow Governance Engine. See [procedural/_ARCH.md](procedural/_ARCH.md). |
| reembedding/ | ZeroDowntimeCrossDimensionReembeddingEngine package. See [reembedding/_ARCH.md](reembedding/_ARCH.md). |
| shared_bus/ | 跨 Agent 共享记忆总线、并发连接池与方案否决账本模块。 See [shared_bus/_ARCH.md](shared_bus/_ARCH.md). |
| social_curator/ | HighSignalSocialFeedCurator package. See [social_curator/_ARCH.md](social_curator/_ARCH.md). |
| task_state/ | Structured Task State Machine and Compaction Preservation Engine. See [task_state/_ARCH.md](task_state/_ARCH.md). |
| temporal/ | Temporal Validity and Fact Expiration Governance Engine. See [temporal/_ARCH.md](temporal/_ARCH.md). |
| tool_guidance/ | Deterministic, cache-stable synthesis of procedural tool memory (traps, edicts) into bounded, zero-LLM tool guidance. See [tool_guidance/_ARCH.md](tool_guidance/_ARCH.md). |
| world_model/ | L3 world model: four-dimension macro project entities (rules, environment, contract, domain knowledge) with versioned records and compact macro-context rendering. See [world_model/_ARCH.md](world_model/_ARCH.md). |
| zero_hallucination/ | Fault-transparent retrieval protocol and anti-fabrication prompt guard for memory queries. See [zero_hallucination/_ARCH.md](zero_hallucination/_ARCH.md). |
| git_okf/ | Git-native loader for Google OKF v0.2 knowledge bundles. See [git_okf/_ARCH.md](git_okf/_ARCH.md). |
| hybrid_engine/ | Orchestrates zero-config SQLite FTS5, offline synonym expansion,. See [hybrid_engine/_ARCH.md](hybrid_engine/_ARCH.md). |
| authoritative_conclusions/ | Context anchor formatter for authoritative conclusions. See [authoritative_conclusions/_ARCH.md](authoritative_conclusions/_ARCH.md). |
| business_templates/ | Pre-seeded industrial business experience templates. See [business_templates/_ARCH.md](business_templates/_ARCH.md). |
| dialectic_guard/ | State machine governing background dialectic inference liveness and lifecycle. See [dialectic_guard/_ARCH.md](dialectic_guard/_ARCH.md). |
| directory_dominance/ | Hierarchical retriever leveraging directory dominance ratios and sibling context bundling. See [directory_dominance/_ARCH.md](directory_dominance/_ARCH.md). |
| ephemeral_delta/ | In-memory, session-scoped transient buffer for prompt-cache-preserving deltas. See [ephemeral_delta/_ARCH.md](ephemeral_delta/_ARCH.md). |
| experience_injection/ | PostCallHook adapter injecting relevant procedure experiences into skill bodies. See [experience_injection/_ARCH.md](experience_injection/_ARCH.md). |
| experience_observability/ | Zero-refactor host lifecycle plugin adapter. See [experience_observability/_ARCH.md](experience_observability/_ARCH.md). |
| fact_supersession/ | Gate evaluating factual contradictions and routing low-confidence candidates into quarantine. See [fact_supersession/_ARCH.md](fact_supersession/_ARCH.md). |
| failure_retrieval/ | Error fingerprint extractor for failure-triggered session retrieval. See [failure_retrieval/_ARCH.md](failure_retrieval/_ARCH.md). |
| lifecycle_hotness/ | Compute deterministic 0.0–1.0 hotness score based on access frequency and recency decay. See [lifecycle_hotness/_ARCH.md](lifecycle_hotness/_ARCH.md). |
| lineage_search/ | Collapses multi-generation compacted or branched session continuations. See [lineage_search/_ARCH.md](lineage_search/_ARCH.md). |
| markdown_curator/ | Calculates bi-directional deltas between in-memory stores and Markdown mirrors. See [markdown_curator/_ARCH.md](markdown_curator/_ARCH.md). |
| peer_cognition/ | Self-evolving standing persona card engine and low-token context projector. See [peer_cognition/_ARCH.md](peer_cognition/_ARCH.md). |
| peer_gateway/ | Adaptive hash collision escalation algorithm for deterministic peer normalization. See [peer_gateway/_ARCH.md](peer_gateway/_ARCH.md). |
| procedure_experience/ | Fixed-count dual-node retriever for procedure-shaped experience memories. See [procedure_experience/_ARCH.md](procedure_experience/_ARCH.md). |
| progressive_sidecar/ | Seamless adapter linking Context VFS with L0/L1/L2 progressive sidecar disclosure. See [progressive_sidecar/_ARCH.md](progressive_sidecar/_ARCH.md). |
| queuefs/ | Asynchronous QueueFS engine managing named semantic tasks across sequential DAG stages. See [queuefs/_ARCH.md](queuefs/_ARCH.md). |
| relational_backtrack/ | Core backtracking engine for cross-session entity and temporal causal recall. See [relational_backtrack/_ARCH.md](relational_backtrack/_ARCH.md). |
| rule_cascade/ | Hierarchical deterministic rule cascade loader inspired by Claude Code. See [rule_cascade/_ARCH.md](rule_cascade/_ARCH.md). |
| session_commit/ | Orchestrates two-phase session archival, reliable boundary gating, and memory_diff auditing. See [session_commit/_ARCH.md](session_commit/_ARCH.md). |
| thinking_sanitizer/ | Sanitizer and egress guard for scrubbing reasoning blocks and drafts. See [thinking_sanitizer/_ARCH.md](thinking_sanitizer/_ARCH.md). |
| tiered_consensus/ | Manager engine governing tiered memory hierarchy and proposal consensus lifecycle. See [tiered_consensus/_ARCH.md](tiered_consensus/_ARCH.md). |
| two_layer_dialectic/ | Dual-layer context injection engine preserving LLM Prompt Cache while resolving contradictions. See [two_layer_dialectic/_ARCH.md](two_layer_dialectic/_ARCH.md). |

## Key Dependencies

- `core`
- `infra`
- `utils`
