# context/

## Overview
Context lifecycle management — cleanup, config, metrics, tracking, reading, offload.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Context lifecycle management — cleanup, config, metrics, tracking, reading, offload. | — |
| aci_tool_contract_linter.py | Core | ACI (Agent-Computer Interface) tool contract and Goldilocks Zone prompt linter. | ✅ |
| agent_mention_dual_mode_router.py | Core | Agent mention dual-mode router coordinating read-only snapshots and bidi channels. | ✅ |
| agent_mention_types.py | Types | Agent mention dual-mode interaction types and communication contracts. | ✅ |
| agent_relay_handshake.py | Core | Bridges heterogeneous AI agents (Claude, Codex, DeepSeek) enabling zero-restatement handoffs without window overflow. | ✅ |
| agent_session_kernel.py | Core | Unified AgentSession Kernel implementation. | ✅ |
| agent_state_capsule.py | Core | Universal Agent State Capsule & Cross-Device Migration Bundle Engine. | ✅ |
| agent_state_capsule_types.py | Types | Data contracts and models for Universal Agent State Capsule. | ✅ |
| append_only_compaction_ledger_engine.py | Core | Append-only compaction ledger engine with atomic tool-pair cut points and split-turn fusion. | ✅ |
| append_only_compaction_types.py | Types | Types for append-only compaction ledger and atomic tool-pair cut-point engine. | ✅ |
| append_only_context_pipeline.py | Core | Append-only context pipeline and deterministic summarization engine. | ✅ |
| append_only_kv_cache_guard.py | Core | Enforces strict append-only context growth, preserves LLM KV cache prefix hit rates, and buffers mid-turn side mutations. | ✅ |
| archive_restore_action.py | Core | Typed GUI/server archive restore action contract: validates current-session archive path, explicit line range and restore budget, then streams the requested range into bounded XML context for the next Agent turn and returns UI-safe restore result metadata; late line ranges build/reuse a sparse byte-offset sidecar so repeated restores do not rescan from file start. | ✅ |
| archive_store.py | Core | Session-scoped content-addressed archive storage for retry-safe tool-result offload reuse, atomic payload/metadata writes, restore-map sidecar generation/self-healing, and metadata/payload hash validation before reuse. | ✅ |
| artifact_centric_loop.py | Core | Elevates artifacts from passive file I/O to first-class working scenes. | ✅ |
| artifact_heuristic_rule_engine.py | Core | Artifact-aware heuristic rule engine for next action prediction. | ✅ |
| ast_symbol_stub_extractor.py | Core | AST symbol stub extractor for lightweight code signature harvesting. | ✅ |
| atomic_tool_pair_cut_point_resolver.py | Core | Atomic tool-pair cut-point resolver for context compaction. | ✅ |
| bidi_agent_channel_gateway.py | Core | Bi-directional agent channel gateway for active peer-to-peer collaboration. | ✅ |
| big_at_context_bridge.py | Core | Bridges cross-discipline sessions via 'Big @' syntax, eliminating manual translation friction without context window bloat. | ✅ |
| bounded_hydration_types.py | Types | Types and data models for bounded initial page loading and upward cursor hydration. | ✅ |
| bounded_initial_page_hydration_engine.py | Core | Bounded initial page hydration engine with lazy upward cursor paging and memory eviction. | ✅ |
| branch_navigation_and_summary_engine.py | Core | Non-destructive branch navigation and exploration summary engine. | ✅ |
| cache_aware_session_lifecycle_router.py | Core | Cache-aware session lifecycle router and mutation defense governor. | ✅ |
| canonical_section_registry.py | Core | Item 120 in topic_06 roadmap: guarantees byte-identical prefix sharing across agent fleets. | ✅ |
| canonical_section_types.py | Types | Item 120 in topic_06 roadmap: enforces stable top-section ordering for 99% KV cache hit rate. | ✅ |
| caveman_output_throttle.py | Core | Caveman Ultra-Compact Output Mode & Output Token Throttle Engine. | ✅ |
| caveman_output_throttle_types.py | Types | Data contracts for Caveman Ultra-Compact Output Mode and Output Token Throttle. | ✅ |
| ccr_context_archival_transformer.py | Core | CCR (Chunk-Cache Retrieval) Context Archival Transformer. | ✅ |
| channel_handoff_and_hf_trace_engine.py | Core | Cross-platform channel handoff coordinator and HuggingFace Trace exporter engine. | ✅ |
| channel_handoff_and_hf_trace_types.py | Types | Types for cross-platform channel handoff, HF trace export, and media pointers. | ✅ |
| cleanup.py | Core | Context file cleanup with session-aware strategy. | ✅ |
| cleanup_ops.py | Core | Context cleanup entrypoints for session directory cleanup and orphan cleanup. | ✅ |
| cleanup_task.py | Core | Background task: periodically clean up orphaned context files. | ✅ |
| cli_dry_run_protocol.py | Core | Dry-run discovery protocol and best source selector for CLI tools. | ✅ |
| client_theme_injection_engine.py | Core | Agent self-reflective client theme introspection and hot-reload injection engine. | ✅ |
| client_theme_injection_types.py | Types | Types and schemas for client theme introspection, wallpaper synthesis and hot-reload injection. | ✅ |
| code_context_pager.py | Core | Code context pager for segmenting source files into virtual memory pages. | ✅ |
| compaction_observation_accounting.py | Core | Delivers deterministic host overhead separation, anti-fluttering hysteresis control, and visual compaction telemetry. | ✅ |
| compression_budget_router.py | Core | Dynamic budget router and four-dimensional quality evaluation engine. | ✅ |
| config.py | Config | Context management configuration. | ✅ |
| content_addressed_dedup_store.py | Core | Content-addressed chunk storage and session turn deduplication store. | ✅ |
| content_addressed_dedup_types.py | Types | Strongly typed data contracts for Content-Addressed Session Dedup and CCR Context Archival. | ✅ |
| content_density_ladder.py | Core | Progressive content density ladder and peek/skim token throttler. | ✅ |
| content_density_ladder_types.py | Types | Type definitions for progressive content density ladder and peek/skim token throttler. | ✅ |
| context_branches.py | Core | Volume-backed snapshot branch manifest (`branches.json`); list/append/get by branch_id for GUI bookmark fork. | ✅ |
| context_engineering_pipeline.py | Core | Unified Context Engineering Pipeline orchestrating ReAct remediation, ACI linting, and virtual memory. | ✅ |
| context_engineering_types.py | Types | Context engineering types and data protocols for ReAct trap remediation and ACI design. | ✅ |
| context_lifecycle_visualizer.py | Core | Context lifecycle visualizer rendering three-tier compression dashboards. | ✅ |
| context_lifecycle_visualizer_types.py | Types | Data contracts and schemas for Lean-Tail Context Lifecycle and Visualizer. | ✅ |
| context_overflow_detector.py | Core | Context overflow detector with 30+ vendor regex patterns and reconciliation auditing. | ✅ |
| context_virtual_memory.py | Core | Context Virtual Memory Manager and CoALA 4-Quadrant Structured Note-Taking Engine. | ✅ |
| conversation_tree_graph.py | Core | In-session tree-structured conversation graph and branch navigation engine. | ✅ |
| conversation_tree_html_exporter.py | Core | Interactive HTML and Markdown exporter for tree-structured conversation graphs. | ✅ |
| conversation_tree_types.py | Types | Type definitions for tree-structured conversation graph and branch replay engine. | ✅ |
| cow_session_branch.py | Core | Instant Session Forking and Copy-on-Write (CoW) State Branching Engine. | ✅ |
| cow_session_branch_types.py | Types | Type definitions for Instant Session Forking and Copy-on-Write (CoW) State Branching. | ✅ |
| cross_file_diff_applier.py | Core | Atomic cross-file diff applier with two-phase verification and rollback. | ✅ |
| cross_session_handoff_ledger.py | Core | Continuity ledger for managing cross-session handoff contracts and lifecycle. | ✅ |
| cross_session_handoff_types.py | Types | Type definitions for cross-session handoff contracts and continuity ledger. | ✅ |
| cumulative_file_tracker.py | Core | Cumulative file footprint tracker across multi-turn sessions, compactions, and branches. | ✅ |
| cut_point_selector.py | Core | Enforces tool call <-> tool result pairing invariants preventing provider API 400 (Invalid Parameter) failures during context compaction. | ✅ |
| cwd_deferred_assembly_guard.py | Core | Guard enforcing outside-in assembly order and deferred CWD service binding. | ✅ |
| cwd_deferred_assembly_types.py | Types | Type contracts for CWD deferred workspace service binding and session resume order. | ✅ |
| default_lossless_lean_tail_compactor.py | Core | Default lossless lean-tail conversation compaction engine. | ✅ |
| deferred_session_runtime_factory.py | Core | Deferred session runtime factory orchestrating outside-in assembly. | ✅ |
| deterministic_prefix_cache_guard.py | Core | Deterministic hash-pinned prefix cache guard. | ✅ |
| deterministic_prefix_cache_types.py | Types | Types and data models for deterministic hash-pinned prefix cache guard and append-only pipeline. | ✅ |
| diff_protocol_scorer.py | Core | Robust content-addressed diff application engine. | ✅ |
| diff_protocol_types.py | Types | Data models and parser for model-generated unified diffs. | ✅ |
| disambiguated_overflow_guard.py | Core | Disambiguated length overflow detector and single-recovery conversational guard. | ✅ |
| dual_tier_compactor_engine.py | Core | Dual-Tier Micro/Full Adaptive Compactor and Mid-Task Steering Engine. | ✅ |
| dual_tier_compactor_types.py | Types | Type definitions for Dual-Tier Micro/Full Adaptive Compactor, Mid-Task Steering, and Tool Loop Tracker Watchdog. | ✅ |
| dual_track_session_guard.py | Core | Dual-Track Session Scenario Context Isolator and Token Burn Guard. | ✅ |
| dual_track_session_guard_types.py | Types | Type definitions for Dual-Track Session Scenario Context Isolator and Token Burn Guard. | ✅ |
| durable_deferred_write_manager.py | Core | Manages crash-safe mid-turn facts and configuration updates that strictly survive abort and cancelation. | ✅ |
| durable_tri_queue.py | Core | Manages lane-level concurrent message dispatch, crash-safe queue resurrection, and abort semantics divergence. | ✅ |
| dynamic_tool_schema_pruner.py | Core | Dynamic Tool Schema Pruner with Progressive Disclosure. | ✅ |
| entropy_draining_engine.py | Core | Architecture entropy draining engine and dynamic working set rules pruner. | ✅ |
| entry_projectors.py | Core | Entry projector plugins for translating custom entries into LLM context messages. | ✅ |
| entry_transforms.py | Core | Entry transform plugins for post-compaction context pruning and deduplication. | ✅ |
| environment_changelog.py | Core | Dual-readable environment changelog and anti-amnesia recovery ledger. | ✅ |
| environment_changelog_types.py | Types | Type definitions for dual-readable environment changelog and anti-amnesia recovery ledger. | ✅ |
| evidence_grounding_gate.py | Core | Evidence-based locator grounding protocol and anti-hallucination gate. | ✅ |
| evidence_grounding_types.py | Types | Type definitions for evidence-based locator grounding protocol and anti-hallucination gate. | ✅ |
| extreme_streaming_governor.py | Core | 384K Extreme Long Output Streaming and Chunk Memory Governor. | ✅ |
| extreme_streaming_governor_types.py | Types | Type definitions for 384K Extreme Long Output Streaming and Chunk Memory Governor. | ✅ |
| file_access_tracker.py | Core | File access tracking system for context files. | ✅ |
| file_io_checkpoint_tracker.py | Core | Runtime context layer deterministic state extraction component. | ✅ |
| file_move_tracking_session_store.py | Core | Persistent file-move tracking session store with stable ChatId invariants. | ✅ |
| file_move_tracking_store_types.py | Types | Type definitions for file-move tracking session store. | ✅ |
| five_layer_rule_arbiter.py | Core | Five-layer rule hierarchy topology arbiter and anti-bloat garbage collector. | ✅ |
| full_repo_ast_packer.py | Core | AST-augmented packer for 1M long-context full-repo refactoring. | ✅ |
| full_repo_attention_anchor.py | Core | Attention anchor injection and AST drift tolerance aligner for 1M context. | ✅ |
| full_repo_refactor_pipeline.py | Core | Native 1M long-context full-repo refactoring pipeline facade. | ✅ |
| full_repo_refactor_types.py | Types | Type definitions for native 1M long-context full-repo refactoring pipeline. | ✅ |
| full_spectrum_lifecycle_hub.py | Core | Full-spectrum in-process lifecycle interceptor and dynamic context pruning hub. | ✅ |
| full_spectrum_lifecycle_types.py | Types | Type definitions for full-spectrum in-process lifecycle interceptor and context pruning hub. | ✅ |
| git_session_tree.py | Core | Git-like non-linear session tree and parent-id branching engine. | ✅ |
| git_session_tree_types.py | Types | Data contracts and types for Git-like non-linear session tree and branching engine. | ✅ |
| headless_rpc_gateway.py | Core | Powers automated pipelines, IDE extensions, and headless agent execution modes (--mode rpc / --mode json). | ✅ |
| headroom_adaptive_budget_compressor.py | Core | Prevents token exhaustion across long-horizon multi-turn execution. | ✅ |
| heavy_tool_payload_blob_store.py | Core | Heavy tool payload blob store and detachment manager. | ✅ |
| hidden_goal_rubric_preamble.py | Core | Delivers instant turn-1 goal grounding with zero tool-call round-trips. | ✅ |
| hierarchical_instruction_hub.py | Core | Project-Specific Goosehints and Hierarchical Instruction Hub. | ✅ |
| hierarchical_instruction_hub_types.py | Types | Type definitions for Project-Specific Goosehints and Hierarchical Instruction Hub. | ✅ |
| hierarchical_project_matrix.py | Core | Hierarchical Project Context Matrix and Agent Dynamic Binding Gate. | ✅ |
| hierarchical_project_matrix_types.py | Types | Data contracts for Hierarchical Project Context Matrix and Dynamic Binding Gate. | ✅ |
| in_context_next_action_predictor.py | Core | In-Context Next Action and Question Predictor. | ✅ |
| in_flight_steer_controller.py | Core | In-flight steering controller for active session redirection. | ✅ |
| in_process_bm25_retriever.py | Core | In-process sub-millisecond BM25 lexical retriever for AI agent context engineering. | ✅ |
| in_process_bm25_types.py | Types | Type definitions for In-Process BM25 Lexical Retriever and Dynamic Tool Schema Pruner. | ✅ |
| incremental_material_hydration_engine.py | Core | Incremental material hydration and project resumption engine. | ✅ |
| instance_metrics.py | Core | Context operation metrics for monitoring and observability. | ✅ |
| interactive_survey_engine.py | Core | Eliminates tedious multi-paragraph typing and accelerates requirement gathering 5x. | ✅ |
| interactive_survey_types.py | Types | Types and schemas for interactive mini-survey cards and rich deliverable document streamout. | ✅ |
| internal_external_message_pipeline.py | Core | Internal/external message separation and context transformation pipeline. | ✅ |
| internal_external_message_pipeline_types.py | Types | Type definitions for internal/external message separation and context transformation pipeline. | ✅ |
| lazy_subdirectory_rules.py | Core | Lazy-loaded subdirectory rules discovery probe and dynamic tool injection hub. | ✅ |
| lazy_subdirectory_rules_types.py | Types | Data contracts and types for lazy-loaded subdirectory rules discovery and dynamic tool injection. | ✅ |
| lca_branch_exploration_summary_engine.py | Core | LCA branch exploration summary inheritance and cumulative file footprint engine. | ✅ |
| lca_branch_summary_types.py | Types | Type contracts for LCA branch exploration summary and cumulative file tracking. | ✅ |
| lean_tail_boundary_compactor.py | Core | Lean-Tail Boundary Compactor implementing strict head/tail preservation. | ✅ |
| lean_tail_compression_engine.py | Core | Lean-Tail compaction engine with fixed-interval tail bounds and soft token budgeting. | ✅ |
| lean_tail_compression_types.py | Types | Data types and schemas for Lean-Tail compression and reasoning trace stripping. | ✅ |
| live_thread_compaction_types.py | Types | Data types and protocol models for remote sandbox live thread physical compaction. | ✅ |
| lossless_lean_tail_types.py | Types | Data types and schemas for default lossless lean-tail conversation compaction. | ✅ |
| media_pointer_lifecycle_manager.py | Core | Media pointer lifecycle manager for turn-scoped multimodal payload governance. | ✅ |
| memory_reinforce_emphasis_gate.py | Core | Memory rule reinforcement emphasis gate. | ✅ |
| memory_reinforce_skill_attach_types.py | Types | Types and data models for memory rule reinforcement emphasis gate and mid-session skill attachment. | ✅ |
| message_importance_classifier.py | Core | Message importance classifier for categorizing conversation turns by criticality. | ✅ |
| mid_session_skill_attachment_registry.py | Core | Mid-session dynamic skill and tool attachment registry. | ✅ |
| model_free_tool_pruner.py | Core | Model-free deterministic tool result pruner and zero-cost context compactor. | ✅ |
| model_free_tool_pruner_types.py | Types | Type definitions for model-free deterministic tool result pruner and zero-cost context compactor. | ✅ |
| model_harness_cost_router.py | Core | Model and Harness orthogonal decoupling with Total Cost-to-Outcome routing. | ✅ |
| multi_dimension_at_resolver.py | Core | Unified Multi-Dimension At-Symbol Context Resolver and Snapshot Ingestion Hub. | ✅ |
| multi_dimension_at_resolver_types.py | Types | Data contracts and models for Unified Multi-Dimension At-Symbol Context Resolver. | ✅ |
| multi_gateway_trust_governor.py | Core | Multi-Gateway trust tiering, high-risk action interception, and signed Handoff Cards. | ✅ |
| multi_gateway_trust_types.py | Types | Strongly typed data contracts for Model-Harness orthogonal decoupling and multi-gateway trust. | ✅ |
| multi_ide_ruleset_bridge.py | Core | Multi-IDE Universal Ruleset Parser and Trae Rules Compatibility Bridge. | ✅ |
| multi_ide_ruleset_bridge_types.py | Types | Type definitions for Multi-IDE Universal Ruleset Parser and Trae Rules Compatibility Bridge. | ✅ |
| multi_transport_adapters.py | Core | Multi-transport adapters for the unified AgentSession kernel. | ✅ |
| next_action_predictor_types.py | Types | Types and data contracts for In-Context Next Action and Question Predictor. | ✅ |
| offload.py | Core | Context offload: persist full tool outputs and conversation snapshots through framework-neutral scope IDs, with lifecycle access tracking and cleanup entrypoint re-exports. | ✅ |
| omniglyph_types.py | Types | OmniGlyph multimodal visual context channel and Ultra token governor types. | ✅ |
| omniglyph_visual_channel.py | Core | OmniGlyph visual context channel renderer and arbitration governor. | ✅ |
| orphaned_tool_healing_transform.py | Core | Sits between session tree/history projection and provider request transport. | ✅ |
| output_spill_to_disk_middleware.py | Core | Output spill to disk middleware. | ✅ |
| overflow_compaction_guard.py | Core | Bounds the compact-and-retry loop at one attempt per user action, preventing infinite compaction token burn. | ✅ |
| path_scoped_rule_matcher.py | Core | Path-scoped and task-phase rule matching router for dynamic working set slicing. | ✅ |
| path_stable_doc_session.py | Core | File-Path SHA-256 Stable Document Session Binding Hub. | ✅ |
| path_stable_doc_session_types.py | Types | Type definitions for File-Path SHA-256 Stable Document Session Binding Hub. | ✅ |
| persona_conflict_resolver.py | Core | Persona semantic conflict probe and mutual exclusion resolver. | ✅ |
| persona_conflict_resolver_types.py | Types | Data contracts and types for persona semantic conflict probe and mutual exclusion resolver. | ✅ |
| pi_compaction_types.py | Types | Type definitions for Pi Agent-style progressive context compaction, branch summarization, and cumulative file tracker engine. | ✅ |
| pi_progressive_compactor.py | Core | Pi Agent-style progressive context compaction and branch summarization engine. | ✅ |
| plan_mode_boundary_locker.py | Core | Runtime context layer boundary locking and plan review governance component. | ✅ |
| pluggable_context_pipeline_types.py | Types | Types for pluggable context projection and entry transform pipeline. | ✅ |
| pluggable_context_projection_pipeline.py | Core | Pluggable context projection and entry transform pipeline engine. | ✅ |
| prefix_integrity_barrier_types.py | Types | Types and schemas for pre-flight prefix integrity freeze and assertion barrier. | ✅ |
| prefix_integrity_freeze_barrier.py | Core | Active pre-flight barrier defending 99% prompt cache hits before provider dispatch. | ✅ |
| prefix_preserving_canonicalizer.py | Core | Prefix preserving canonicalizer for Prompt Cache optimization. | ✅ |
| pristine_passthrough_sandbox.py | Core | Raw Model Direct Passthrough and Pristine Testing Sandbox. | ✅ |
| pristine_passthrough_sandbox_types.py | Types | Type definitions for Raw Model Direct Passthrough and Pristine Testing Sandbox. | ✅ |
| proactive_clarification_state_machine.py | Core | Orchestrates adaptive convergence state machine, preventing blind tool executions and eliminating repetitive ambiguous multi-turn loops. | ✅ |
| proactive_clarification_types.py | Types | Types and schemas for proactive clarification, slot tracking, and convergence state machine. | ✅ |
| proactive_slot_tracker.py | Core | Maintains structured slot status matrix for proactive conversational convergence. | ✅ |
| progressive_cli_manifest_generator.py | Core | Progressive CLI Capability Manifest Generator conforming to llms.txt standard. | ✅ |
| progressive_cli_manifest_types.py | Types | Data types and schemas for progressive CLI capability manifests and dry-run discovery. | ✅ |
| project_hierarchy_session_index.py | Core | Full-text keyword indexing and search engine for hierarchical project sessions. | ✅ |
| project_hierarchy_session_types.py | Types | Project hierarchy session archive and keyword resurrection types. | ✅ |
| project_milestone_tracker.py | Core | Project milestone tracker managing multi-phase project checkpoints. | ✅ |
| project_milestone_types.py | Types | Data contracts for long-horizon project milestone checkpoints and resumption. | ✅ |
| prompt_cache_economics_engine.py | Core | Prompt cache economics engine and cross-deployment HUD generator. | ✅ |
| prompt_cache_economics_types.py | Types | Types and schemas for cross-deployment prompt cache economics and anti-drift HUD. | ✅ |
| prompt_cache_lifecycle_types.py | Types | Prompt-cache aware session lifecycle and prefix preserving router types. | ✅ |
| prompt_variable_contract_types.py | Types | Item 121 in topic_06 roadmap: pre-flight assertion against variable-induced prefix cache jitter. | ✅ |
| prompt_variable_contract_validator.py | Core | Item 121 in topic_06 roadmap: pre-flight assertion against variable-induced prefix cache jitter. | ✅ |
| protected_patterns_matcher.py | Core | Protected patterns matcher and syntax safety shield. | ✅ |
| prune_and_spill_recall.py | Core | Guarantees 100% recoverability of large tool outputs while shrinking inline context by 70%+ to protect prompt cache prefixes. | ✅ |
| quiet_command_rewriter_hook.py | Core | Quiet command rewriter hook. | ✅ |
| quiet_command_spill_types.py | Types | Quiet command rewriter, output spill, and Subagent context firewall types. | ✅ |
| react_trap_remediator.py | Core | ReAct trap remediation engine for production LLM Agent contexts. | ✅ |
| read_only_snapshot_capturer.py | Core | Read-only context snapshot capturer for non-intrusive peer agent inspection. | ✅ |
| reasoning_anchor_extractor.py | Core | Extractor for condensing raw reasoning streams into structured logic anchors. | ✅ |
| reasoning_compactor_types.py | Types | Type definitions for reasoning-preserving context compactor and token compression governor. | ✅ |
| reasoning_trace_stripper.py | Core | Reasoning trace stripper for removing chain-of-thought blocks from context and summaries. | ✅ |
| rejection_reason_guard.py | Core | Closes the HITL feedback loop and eliminates repeated agent blunders. | ✅ |
| remote_live_thread_compaction_coordinator.py | Core | Coordinator managing host-to-remote sandbox physical thread compaction synchronization. | ✅ |
| remote_thread_actor_endpoint.py | Core | Remote sandbox live thread actor endpoint. | ✅ |
| restore_map_contract.py | Core | Shared restore-map schema v2 contract reader/writer for archive writers and restore guidance, including path normalization and line-range validation. | ✅ |
| restore_map_structures.py | Core | Restore-map structural indexing and UI-safe restore metadata construction: content indexes, source-tagged recommended ranges, range-source hints, and bounded content feature summaries. | ✅ |
| rtk_tool_compressor_types.py | Types | Strongly typed data contracts for RTK Command-Aware Tool Output Lossless Compressor. | ✅ |
| rtk_tool_output_compressor.py | Core | RTK Command-Aware Tool Output Lossless Compressor. | ✅ |
| rule_based_session_synthesizer.py | Core | Rule-based session synthesizer for cross-session handoff generation. | ✅ |
| rule_telemetry_ledger.py | Core | Telemetry and usage ledger for dynamic rules. | ✅ |
| sandbox_cache_bridge_types.py | Types | Sandbox state-aware context cache bridge types and data models. | ✅ |
| sandbox_context_cache_bridge.py | Core | Sandbox state-aware context cache bridge and incremental patch stitching engine. | ✅ |
| sandbox_fs_event_probe.py | Core | Sandbox filesystem event probe and patch compiler. | ✅ |
| scoped_rules_importer.py | Core | Hermes and OpenClaw scoped rules asset importer. | ✅ |
| selective_context_trust_gate.py | Core | Selective context trust gate and misleading signal arbiter (SCOPE). | ✅ |
| selective_context_trust_types.py | Types | Types for selective context preference optimization and misleading signal gate (SCOPE). | ✅ |
| session_checkpoint_storage.py | Core | Storage layer for Session Step Checkpoints supporting atomic persistence. | ✅ |
| session_checkpoint_types.py | Types | Domain models and data contracts for Session State Checkpoint and Atomic Resume. | ✅ |
| session_cwd_guard.py | Core | Protects agent toolkits and bash execution sandboxes from working directory drift across machines, branches, and folder moves. | ✅ |
| session_data_sanitizer.py | Core | Session data sanitization engine for confidential information masking. | ✅ |
| session_dedup_processor.py | Core | Session-Dedup processor providing cross-turn content addressing and retrieve marker replacement. | ✅ |
| session_dedup_types.py | Types | Type contracts for Session-Dedup cross-turn content addressing and retrieve marker engine. | ✅ |
| session_epoch_splitter.py | Core | Auto-Forking Milestone Checkpoint Archiver & Long-Session Epoch Splitter. | ✅ |
| session_epoch_splitter_types.py | Types | Data contracts and models for Long Session Epoch Splitter and Milestone Archiver. | ✅ |
| session_fork_manager.py | Core | Session fork manager and background pipe-back pipeline. | ✅ |
| session_fork_steer_types.py | Types | Session fork and in-flight steer control types. | ✅ |
| session_keyword_resurrection_engine.py | Core | Session keyword resurrection engine for seamless historical agent revival. | ✅ |
| session_lifecycle_log_archiver.py | Core | Session lifecycle log archiver and offline bundle export engine. | ✅ |
| session_lifecycle_log_archiver_types.py | Types | Session lifecycle log archive and offline bundle export types. | ✅ |
| session_resume_integrity_validator.py | Core | Pre-execution safety gate asserting session state persistence integrity before resuming runs, compensating partial writes automatically. | ✅ |
| session_soft_reset.py | Core | Session state soft-reset and instant memory consolidation engine. | ✅ |
| session_soft_reset_types.py | Types | Data contracts and types for session state soft-reset and instant memory consolidation. | ✅ |
| session_spill_store.py | Core | Session-scoped tool output spill store and bounded preview locator harness. | ✅ |
| session_spill_store_types.py | Types | Type definitions for session-scoped tool output spill store and bounded preview locator. | ✅ |
| session_state_atomic_resume_engine.py | Core | Session state atomic checkpoint manager and resume protocol engine. | ✅ |
| session_state_delta_engine.py | Core | Session state delta engine and explicit invalidation compiler. | ✅ |
| session_state_delta_types.py | Types | Types and schemas for session state diff delta protocol and explicit invalidation. | ✅ |
| session_tree_navigator.py | Core | Delivers audit-grade conversation branching, time travel navigation, and branch summary reconciliation. | ✅ |
| single_kernel_transport_types.py | Types | Type contracts for single-kernel multi-transport decoupling and async-ack RPC protocol. | ✅ |
| sliding_window_session_lifecycle.py | Core | Adaptive inactivity sliding window session lifecycle manager and KV cache keeper. | ✅ |
| sliding_window_session_lifecycle_types.py | Types | Types and data contracts for sliding window session lifecycle and KV cache keeper. | ✅ |
| social_work_context_graph.py | Core | Social Collaboration Graph and Cross-Application Work Context Engine. | ✅ |
| social_work_context_graph_types.py | Types | Data contracts for Social Collaboration Graph and Cross-Application Work Context. | ✅ |
| structured_checkpoint_generator.py | Core | Runtime context management checkpoint synthesis layer. | ✅ |
| subagent_context_firewall.py | Core | Subagent context firewall and model downgrade governor. | ✅ |
| subagent_worktree_isolator.py | Core | Subagent Git Worktree write isolation and merge reconciliation. | ✅ |
| surface_projection_engine.py | Core | Immutable Event Log SSOT and Surface Projection Engine. | ✅ |
| surface_projection_types.py | Types | Type definitions for Immutable Event Log SSOT and Surface Projection Engine. | ✅ |
| tail_deferred_overflow_types.py | Types | Tail-only context append and disambiguated overflow types. | ✅ |
| tail_deferred_write_queue.py | Core | Tail-only context append and deferred write queue. | ✅ |
| theme_palette_synthesizer.py | Core | Core palette synthesis engine supporting WCAG contrast safety and XSS protection. | ✅ |
| tiered_context_compression_pipeline.py | Core | Four-Tier Progressive Context Compression Pipeline. | ✅ |
| tiered_token_compression_governor.py | Core | Tiered token compression governor with reasoning preservation and budget enforcement. | ✅ |
| token_estimator.py | Core | Provides high-throughput, drift-free token estimation anchored on provider billing data for context management decisions. | ✅ |
| token_tax_governor.py | Core | Token Tax governor unifying thin prompt contracts, GC, and context auditing. | ✅ |
| tokenomics_compression_types.py | Types | Strongly typed data contracts for the Four-Tier Tokenomics context compression engine. | ✅ |
| tool_loop_tracker.py | Core | ToolLoopTracker: Watchdog detecting tool call oscillation and infinite loops. | ✅ |
| tool_output_auditor.py | Core | Intercepts tool outputs to eliminate token blowups, saving up to 50%+ tokens while preserving diagnostic fidelity. | ✅ |
| tracker_manager.py | Core | Generic singleton manager for tracker instances. | ✅ |
| transient_sub_inquiry.py | Core | Runtime context layer ephemeral side-channel isolation component. | ✅ |
| transient_tool_output_gc.py | Core | Transient tool output garbage collection engine. | ✅ |
| transparent_reader.py | Core | Transparent decompression for context files. | ✅ |
| tree_session_storage.py | Core | Append-only immutable conversation tree storage. | ✅ |
| tree_session_storage_types.py | Types | Immutable tree-structured session types and navigation models. | ✅ |
| tree_state.py | Core | Session-tree bound branch state and tool result details replayer; pure-function branch fold, mono-collapsing anchor, and zero-I/O branch isolation. | ✅ |
| tri_state_handoff_engine.py | Core | Tri-state context pruning and Reality Cross-Check engine. | ✅ |
| tripartite_identity_anchor.py | Core | Tripartite context identity separation and immutable soul anchor engine. | ✅ |
| tripartite_identity_anchor_types.py | Types | Data contracts and types for tripartite context identity separation and immutable soul anchor. | ✅ |
| ultra_heuristic_filter.py | Core | Ultra heuristic pre-filter for low-cost token pruning. | ✅ |
| universal_thin_harness_types.py | Types | Universal agent thin harness adaptive contract and Token Tax governor types. | ✅ |
| universal_thin_prompt_generator.py | Core | Universal thin prompt generator for adaptive agent harnesses. | ✅ |
| usage_ledger_attempt.py | Core | Delivers audit-grade attempt billing, adjustment reconciliation, and entry-level cost rollups. | ✅ |
| user_query_disambiguation_guard.py | Core | Protects user prompt integrity and custom compaction instructions. | ✅ |
| virtual_page_swap_manager.py | Core | Virtual page swap manager for managing tiered code context memory. | ✅ |
| virtual_paged_code_types.py | Types | Virtual paged code context tiering and swap engine types. | ✅ |
| voice_spec_extractor_types.py | Types | Full-duplex voice requirement discovery and structured spec extractor types. | ✅ |
| voice_transcript_buffer.py | Core | Voice transcript buffer and conversation flow state tracker. | ✅ |
| voice_transcript_to_spec_extractor.py | Core | Voice transcript to structured technical plan/spec distillation engine. | ✅ |
| working_set_rules_types.py | Types | Data types and schemas for dynamic working-set rules and architecture entropy draining. | ✅ |
| session/（子包） | Core | Session 级上下文生命周期子域：活跃会话加载（session-aware 清理）、volume-backed 置顶文件注册表（跨压缩保留）、LangGraph checkpoint/message SSOT（rewind/truncate/edit-resend）。3 个 `session_*` 模块聚合于此，`session/__init__.py` 为聚合门面统一 re-export | ✅ |
| transcripts/（子包） | Core | 跨助手会话转录本纯净解析与连续性重锚子域：Claude Code / Codex CLI 会话流解析、沙箱工作区路径重锚（`/workspace`）与两阶段紧凑规约。5 个模块聚合于此，`transcripts/__init__.py` 为门面统一 re-export | ✅ |

## Key Dependencies

- `agent`
- `toolkits`
