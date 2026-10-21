# context_management/

## Overview
Context management module. Industry theory: [CONTEXT_ENGINEERING.md](CONTEXT_ENGINEERING.md). Prompt cache practice: [PROMPT_CACHE_PRACTICE.md](PROMPT_CACHE_PRACTICE.md). Placement SSOT (dynamic vs frozen prefix): [docs/PROMPT_CACHE_PLACEMENT.md](../../../../docs/PROMPT_CACHE_PLACEMENT.md).

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
| capability_matrix/ | 情境感知型渐进式能力即时推荐与交互式快捷指令全景面板核心引擎（Item 38 P0）。 See [capability_matrix/_ARCH.md](capability_matrix/_ARCH.md). |
| compression_flush/ | 多智能体与长会话上下文压缩即时持久化刷盘协议与内存沙箱套件。 See [compression_flush/_ARCH.md](compression_flush/_ARCH.md). |
| dependency_expansion/ | 全链路跨栈架构依赖展开图谱与任务复杂度自适应双轨调度套件。 See [dependency_expansion/_ARCH.md](dependency_expansion/_ARCH.md). |
| desktop_repl/ | In-process scripted REPL over a mock desktop SDK that only records actions; it does not drive a real desktop and is not wired to `DesktopSession` or any agent tool. See [desktop_repl/_ARCH.md](desktop_repl/_ARCH.md). |
| downshift/ | Context threshold model downshift governor and deterministic handover memo protocol (token % and WU dual triggers, zero-API SessionNotes extraction, Fallback-Up circuit breaker). |
| infra/ | Context management infrastructure: shared types, token estimation, budget management, session locks, archive references, cache policy. |
| omni_reference/ | Core engine for 5-dimensional omni-@ references parsing, context slice extraction, and prompt injection formatting. See [omni_reference/_ARCH.md](omni_reference/_ARCH.md). |
| pipeline/ | Ordered context processors for filtering, active per-step tool-result pruning, cache-TTL pruning, pre-compaction recall, compression, session notes, summarization, post-compaction refetch guard, normalization, and explicit cache markers. Filter and Compress consume compression_intent via retention_helpers. |
| prefix_caching_ledger/ | Prefix caching aligned context layout and hidden reasoning token ledger suite (Item 308). See [prefix_caching_ledger/_ARCH.md](prefix_caching_ledger/_ARCH.md). |
| scratchpad_promotion/ | Quick scratchpad draft to full project seed transformation engine for dual-track workspace architectures. See [scratchpad_promotion/_ARCH.md](scratchpad_promotion/_ARCH.md). |
| strategies/ | Three-tier context reduction strategies: Filter, Compress, Summarize. `Summarize` enforces structural validation via `with_structured_output` to eliminate JSON parsing fragility. |
| tracking/ | Observation and tracking: artifact tracking, task metrics, archive refetch cost, restore-block events, and archive read budgets. |
| two_stage_search_extract/ | Two-stage ranked snippet triage and selective deep web extract suite (Item 327). See [two_stage_search_extract/_ARCH.md](two_stage_search_extract/_ARCH.md). |
| working_memory/ | Local Working Memory Block: low-overhead in-memory workbench for goals, subtasks, traps, and turn-tail prompt cache-safe rendering. |

## Key Dependencies

- `agent` (types, event_log)
- `infra` (delivery, tracing)
- `utils` (token_economics)
