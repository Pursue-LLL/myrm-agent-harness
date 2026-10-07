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
| active_compression/ | Core implementation of Active-Turn Live Context Compression Engine. See [active_compression/_ARCH.md](active_compression/_ARCH.md). |
| ambiguity_probe/ | Core implementation of Ambiguity Clarification Probe and Private Entity Graph Backtracking Engine. See [ambiguity_probe/_ARCH.md](ambiguity_probe/_ARCH.md). |
| architecture_gate/ | Core implementation of Architecture Planning Discussion-First and Intent Convergence Gate. See [architecture_gate/_ARCH.md](architecture_gate/_ARCH.md). |
| archive_checkpoint/ | Lite-LLM archive summary checkpoints: Protocol store, EpisodicMemory persistence, bounded async `ArchiveSummaryService`. |
| branch_summary/ | Core engine for Branch Summarization and Selective Merge-Back. See [branch_summary/_ARCH.md](branch_summary/_ARCH.md). |
| branching/ | Distills trial-and-error lessons from abandoned branches to roam into new forks. See [branching/_ARCH.md](branching/_ARCH.md). |
| cache_governor/ | Pre-flight economic governor guarding against negative ROI cache write premiums. See [cache_governor/_ARCH.md](cache_governor/_ARCH.md). |
| canonical_tool/ | Canonicalizer ensuring byte-level deterministic stability for tool prefixes. See [canonical_tool/_ARCH.md](canonical_tool/_ARCH.md). |
| canvas_deeplink/ | 跨会话画布深度直链共享、设计资产穿透与专业设计平台桥接核心引擎。 See [canvas_deeplink/_ARCH.md](canvas_deeplink/_ARCH.md). |
| channel_thread_session/ | Core implementation of Channel Thread to Session Dynamic Binding and Isolated Branching Engine. See [channel_thread_session/_ARCH.md](channel_thread_session/_ARCH.md). |
| clean_pod_archival/ | 核心引擎实现：单任务瞬态上下文防污染隔离、最终产物干净汇流与夜间定时无损资产沉淀。 See [clean_pod_archival/_ARCH.md](clean_pod_archival/_ARCH.md). |
| collaboration/ | Manages shared cloud session snapshots, security gates, and team steering. See [collaboration/_ARCH.md](collaboration/_ARCH.md). |
| compression_flush/ | 多智能体与长会话上下文压缩即时持久化刷盘协议与内存沙箱套件。 See [compression_flush/_ARCH.md](compression_flush/_ARCH.md). |
| context_diet/ | 静态 Persona 蒸馏、开局底噪透视与纯净创造力节食核心引擎。 See [context_diet/_ARCH.md](context_diet/_ARCH.md). |
| demand_hydration/ | 个人画像与专业偏好全域按需水合、动态即时召回与大模型原生创造力保鲜引擎。 See [demand_hydration/_ARCH.md](demand_hydration/_ARCH.md). |
| dependency_expansion/ | 全链路跨栈架构依赖展开图谱与任务复杂度自适应双轨调度套件。 See [dependency_expansion/_ARCH.md](dependency_expansion/_ARCH.md). |
| downshift/ | Context threshold model downshift governor and deterministic handover memo protocol (token % and WU dual triggers, zero-API SessionNotes extraction, Fallback-Up circuit breaker). |
| dual_branching/ | Core implementation of Dual-Branching Session Fork and In-Place Turn Rewind Engine. See [dual_branching/_ARCH.md](dual_branching/_ARCH.md). |
| dual_loop_steering/ | 内外双层循环实时代令引导、键盘意图分流与排队队列核心引擎。 See [dual_loop_steering/_ARCH.md](dual_loop_steering/_ARCH.md). |
| emergent_attention/ | 从行为中涌现的注意力清单、海量通知意图过滤器与言行错位智能对照引擎。 See [emergent_attention/_ARCH.md](emergent_attention/_ARCH.md). |
| epoch/ | Compiles and orders tool definitions deterministically for Prompt Cache. See [epoch/_ARCH.md](epoch/_ARCH.md). |
| file_watch/ | Gateway orchestrating workspace file mutation events and session context invalidation. See [file_watch/_ARCH.md](file_watch/_ARCH.md). |
| handoff_brief/ | Gateway orchestrating structured handoff briefs and cross-session state continuity. See [handoff_brief/_ARCH.md](handoff_brief/_ARCH.md). |
| handover/ | Central bus orchestrating cross-device session handover and terminal attachment. See [handover/_ARCH.md](handover/_ARCH.md). |
| harness_tax/ | 极紧凑 Working Memory 投影器、显式 Resource Loader 与超低 Harness Tax 控制引擎。 See [harness_tax/_ARCH.md](harness_tax/_ARCH.md). |
| inbound_shield/ | 核心引擎实现：长文本入站防御性分页挂载、大消息防爆 Working Memory 与智能摘要网关。 See [inbound_shield/_ARCH.md](inbound_shield/_ARCH.md). |
| infra/ | Context management infrastructure: shared types, token estimation, budget management, session locks, archive references, cache policy. |
| instructions/ | Recursively resolves project instructions upward along directory tree and claims legacy skills. See [instructions/_ARCH.md](instructions/_ARCH.md). |
| interrupt_preserver/ | Core implementation of Graceful Turn Interrupt and Queued Message Draft Preserver. See [interrupt_preserver/_ARCH.md](interrupt_preserver/_ARCH.md). |
| isolation/ | Guards context against cross-project data bleed and asserts task alignment. See [isolation/_ARCH.md](isolation/_ARCH.md). |
| loyalty/ | Manages user-centric loyalty layers and cross-model test-time RL alignment. See [loyalty/_ARCH.md](loyalty/_ARCH.md). |
| message_tree/ | Manages in-place branching, sibling version switching, and path resolution. See [message_tree/_ARCH.md](message_tree/_ARCH.md). |
| micro_compaction/ | Core implementation of Micro-Compaction and Amortized Turn Context Reclamation Engine. See [micro_compaction/_ARCH.md](micro_compaction/_ARCH.md). |
| million_token_ceiling/ | 百万 Token 超大上下文动态自适应压实、延迟与成本双轨绝对上限守卫引擎。 See [million_token_ceiling/_ARCH.md](million_token_ceiling/_ARCH.md). |
| mobility/ | Serializes, packs, and validates portable workspace state capsules. See [mobility/_ARCH.md](mobility/_ARCH.md). |
| multibot_governor/ | Core implementation of Multi-Bot Shared Group Chatter Governor. See [multibot_governor/_ARCH.md](multibot_governor/_ARCH.md). |
| multimodal_redaction/ | Unified pipeline for direct-tool scrubbing and multimodal attachment degradation. See [multimodal_redaction/_ARCH.md](multimodal_redaction/_ARCH.md). |
| owner_fencing/ | Core implementation of Durable Session Owner Fencing and Admission Control Engine. See [owner_fencing/_ARCH.md](owner_fencing/_ARCH.md). |
| pairing/ | Generates dynamic pairing tickets and formatted QR code bootstrap payloads. See [pairing/_ARCH.md](pairing/_ARCH.md). |
| pinning/ | Guarantees zero-pruning preservation of pinned contexts and constructs inspector cards. See [pinning/_ARCH.md](pinning/_ARCH.md). |
| pipeline/ | Ordered context processors for filtering, active per-step tool-result pruning, cache-TTL pruning, pre-compaction recall, compression, session notes, summarization, post-compaction refetch guard, normalization, and explicit cache markers. Filter and Compress consume compression_intent via retention_helpers. |
| privacy_mode/ | 核心引擎实现：会话级隐私模式：卸除全部工具硬门禁与擅自调用拦截。 See [privacy_mode/_ARCH.md](privacy_mode/_ARCH.md). |
| project_container/ | 核心引擎实现：统一项目全生命周期资产容器、会话物理拖拽归档与零噪音静默收纳。 See [project_container/_ARCH.md](project_container/_ARCH.md). |
| project_state/ | 面向长期项目的动态事实状态账本与上下文投影流水线套件。 See [project_state/_ARCH.md](project_state/_ARCH.md). |
| prompt_anchoring/ | Gateway orchestrating dual-layer system prompt assembly and tail redirection. See [prompt_anchoring/_ARCH.md](prompt_anchoring/_ARCH.md). |
| rotation/ | Orchestrates three-tier runtime parameter assembly and MCP connection caching. See [rotation/_ARCH.md](rotation/_ARCH.md). |
| rule_lifecycle/ | 核心引擎实现：智能体长期规则生命周期审计、过时失效嗅探与瘦身清洗中枢。 See [rule_lifecycle/_ARCH.md](rule_lifecycle/_ARCH.md). |
| sandwich_trajectory/ | Core implementation of Sandwich Trajectory Compression and Middle Turn Summarization Engine. See [sandwich_trajectory/_ARCH.md](sandwich_trajectory/_ARCH.md). |
| session_commit/ | 双阶段崩溃自愈会话自动提交与三维经验沉淀引擎。 See [session_commit/_ARCH.md](session_commit/_ARCH.md). |
| session_dom/ | 通用事件溯源会话 DOM、声明式生命周期与真回滚引擎核心实现。 See [session_dom/_ARCH.md](session_dom/_ARCH.md). |
| session_roaming/ | 跨设备会话实时漫游、团队协作接力与沙箱热镜像核心引擎。 See [session_roaming/_ARCH.md](session_roaming/_ARCH.md). |
| session_tree/ | Manages session timeline branching, message cloning, and in-place rewind. See [session_tree/_ARCH.md](session_tree/_ARCH.md). |
| shareable_fork/ | 核心引擎实现：具备交互式运行时状态的会话免密分享链接、多端只读/协作穿透与一键无损分叉。 See [shareable_fork/_ARCH.md](shareable_fork/_ARCH.md). |
| skill_sentinel/ | Core implementation of Active Skill Compaction Survival Sentinel and Reattachment Governor. See [skill_sentinel/_ARCH.md](skill_sentinel/_ARCH.md). |
| steering/ | Manages serialized in-flight human steering messages for a specific session. See [steering/_ARCH.md](steering/_ARCH.md). |
| steering_protocol/ | Core implementation of In-Flight Steering and Follow-Up Queue Injection Protocol Gateway. See [steering_protocol/_ARCH.md](steering_protocol/_ARCH.md). |
| strategies/ | Three-tier context reduction strategies: Filter, Compress, Summarize. `Summarize` enforces structural validation via `with_structured_output` to eliminate JSON parsing fragility. |
| subagent_scratchpad/ | 多代理共享草稿白板、子代理瞬态上下文隔离与轻量事实广播核心引擎。 See [subagent_scratchpad/_ARCH.md](subagent_scratchpad/_ARCH.md). |
| tagging/ | Manages tag catalog, session associations, queries, and auto-classification. See [tagging/_ARCH.md](tagging/_ARCH.md). |
| tracking/ | Observation and tracking: artifact tracking, task metrics, archive refetch cost, restore-block events, and archive read budgets. |
| transcript_enforcer/ | Hard gate enforcing append-only invariant on conversation message transcripts. See [transcript_enforcer/_ARCH.md](transcript_enforcer/_ARCH.md). |
| visual_pruner/ | Core engine for Visual Frame Context Pruning and Latency Squeezing. See [visual_pruner/_ARCH.md](visual_pruner/_ARCH.md). |
| working_memory/ | Local Working Memory Block: low-overhead in-memory workbench for goals, subtasks, traps, and turn-tail prompt cache-safe rendering. |
| workspace_guard/ | 显式工作区探索守卫与自主扫盘抑制核心引擎。 See [workspace_guard/_ARCH.md](workspace_guard/_ARCH.md). |
| worktree_isolation/ | Core implementation of Git Worktree Multi-Branch Parallel Session Isolation Engine. See [worktree_isolation/_ARCH.md](worktree_isolation/_ARCH.md). |

## Key Dependencies

- `agent` (types, event_log)
- `infra` (delivery, tracing)
- `utils` (token_economics)
