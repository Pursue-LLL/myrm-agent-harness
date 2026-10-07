# context_management/

## Overview
Context management module. Industry theory: [CONTEXT_ENGINEERING.md](CONTEXT_ENGINEERING.md). Prompt cache practice: [PROMPT_CACHE_PRACTICE.md](PROMPT_CACHE_PRACTICE.md).

Detailed design: [CONTEXT_MANAGEMENT_SYSTEM.md](CONTEXT_MANAGEMENT_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| CONTEXT_ENGINEERING.md | L2 | Industry context-engineering theory (Manus, Anthropic, Factory Research) | — |
| CONTEXT_MANAGEMENT_SYSTEM.md | L2 | Detailed context-management system design (processor chain, compression pipeline, retention) | — |
| PROMPT_CACHE_PRACTICE.md | L2 | Framework prompt-cache implementation practices | — |
| __init__.py | Package | Context management module. | — |
| context.py | Core | Agent runtime context definition. Provides a type-safe context container for passing user, session,  | ✅ |
| preheat.py | Utility | Prefix cache preheat and idle keep-alive for explicit-cache providers (Anthropic, Qwen). Three patterns: agent-init preheat (`schedule_init_preheat`), post-compaction re-warming (`preheat_prefix_cache`), and idle keep-alive (`CacheKeepAliveManager` — periodic 4-min probes to prevent 5-min TTL eviction). Uses max_tokens=0 per Anthropic best practice with max_tokens=1 fallback. | ✅ |
| pre_compact_service.py | Core | MemoryPreCompactService — default ContextPreCompactCallback; semantic recall before compaction. | ✅ |
| salient_tool_filter.py | Utility | Deterministic Salient Tool Output Filter & Verbatim Evidence Extractor for preserving high-severity tool outputs before context compaction without LLM cost. | ✅ |

| Submodule | Description |
|-----------|-------------|
| archive_checkpoint/ | Lite-LLM archive summary checkpoints: Protocol store, EpisodicMemory persistence, bounded async `ArchiveSummaryService`. |
| branching/ | Distills trial-and-error lessons from abandoned branches to roam into new forks. See [branching/_ARCH.md](branching/_ARCH.md). |
| collaboration/ | Manages shared cloud session snapshots, security gates, and team steering. See [collaboration/_ARCH.md](collaboration/_ARCH.md). |
| compression_flush/ | 多智能体与长会话上下文压缩即时持久化刷盘协议与内存沙箱套件。 See [compression_flush/_ARCH.md](compression_flush/_ARCH.md). |
| dependency_expansion/ | 全链路跨栈架构依赖展开图谱与任务复杂度自适应双轨调度套件。 See [dependency_expansion/_ARCH.md](dependency_expansion/_ARCH.md). |
| downshift/ | Context threshold model downshift governor and deterministic handover memo protocol (token % and WU dual triggers, zero-API SessionNotes extraction, Fallback-Up circuit breaker). |
| epoch/ | Compiles and orders tool definitions deterministically for Prompt Cache. See [epoch/_ARCH.md](epoch/_ARCH.md). |
| handover/ | Central bus orchestrating cross-device session handover and terminal attachment. See [handover/_ARCH.md](handover/_ARCH.md). |
| infra/ | Context management infrastructure: shared types, token estimation, budget management, session locks, archive references, cache policy. |
| instructions/ | Recursively resolves project instructions upward along directory tree and claims legacy skills. See [instructions/_ARCH.md](instructions/_ARCH.md). |
| isolation/ | Guards context against cross-project data bleed and asserts task alignment. See [isolation/_ARCH.md](isolation/_ARCH.md). |
| loyalty/ | Manages user-centric loyalty layers and cross-model test-time RL alignment. See [loyalty/_ARCH.md](loyalty/_ARCH.md). |
| message_tree/ | Manages in-place branching, sibling version switching, and path resolution. See [message_tree/_ARCH.md](message_tree/_ARCH.md). |
| mobility/ | Serializes, packs, and validates portable workspace state capsules. See [mobility/_ARCH.md](mobility/_ARCH.md). |
| multimodal_redaction/ | Unified pipeline for direct-tool scrubbing and multimodal attachment degradation. See [multimodal_redaction/_ARCH.md](multimodal_redaction/_ARCH.md). |
| pairing/ | Generates dynamic pairing tickets and formatted QR code bootstrap payloads. See [pairing/_ARCH.md](pairing/_ARCH.md). |
| pinning/ | Guarantees zero-pruning preservation of pinned contexts and constructs inspector cards. See [pinning/_ARCH.md](pinning/_ARCH.md). |
| pipeline/ | Ordered context processors for filtering, active per-step tool-result pruning, cache-TTL pruning, pre-compaction recall, compression, session notes, summarization, post-compaction refetch guard, normalization, and explicit cache markers. Filter and Compress consume compression_intent via retention_helpers. |
| project_state/ | 面向长期项目的动态事实状态账本与上下文投影流水线套件。 See [project_state/_ARCH.md](project_state/_ARCH.md). |
| rotation/ | Orchestrates three-tier runtime parameter assembly and MCP connection caching. See [rotation/_ARCH.md](rotation/_ARCH.md). |
| session_tree/ | Manages session timeline branching, message cloning, and in-place rewind. See [session_tree/_ARCH.md](session_tree/_ARCH.md). |
| steering/ | Manages serialized in-flight human steering messages for a specific session. See [steering/_ARCH.md](steering/_ARCH.md). |
| strategies/ | Three-tier context reduction strategies: Filter, Compress, Summarize. `Summarize` enforces structural validation via `with_structured_output` to eliminate JSON parsing fragility. |
| tagging/ | Manages tag catalog, session associations, queries, and auto-classification. See [tagging/_ARCH.md](tagging/_ARCH.md). |
| tracking/ | Observation and tracking: artifact tracking, task metrics, archive refetch cost, restore-block events, and archive read budgets. |
| working_memory/ | Local Working Memory Block: low-overhead in-memory workbench for goals, subtasks, traps, and turn-tail prompt cache-safe rendering. |

## Key Dependencies

- `agent` (types, event_log)
- `infra` (delivery, tracing)
- `utils` (token_economics)
