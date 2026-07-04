# streaming/

## Overview
BaseAgent event processing pipeline.

Detailed design: [STREAMING_SYSTEM.md](STREAMING_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | BaseAgent event processing pipeline. | — |
| artifact_events.py | Core | Artifact event handler. `collect_ui_artifacts` yields `ui_artifact` before `data_update` so downstream collectors can merge surface data. | ✅ |
| channel_output_hints.py | Config | Per-channel output format hints. Resolves channel-specific prompt guidance (e.g. Telegram: no tables; WhatsApp: plain text only; voice: conversational). Symmetric with model_discipline.py. | ✅ |
| escalation_scrubber.py | Core | Model self-escalation marker scrubber. Detects <<<NEEDS_PRO>>> markers in streaming output, buffers content to prevent marker display, and signals stream_recovery to switch to a stronger model. | ✅ |
| event_handlers.py | Core | LangGraph stream event to business event transformer. Emits TOOL_IMAGE_OUTPUT for multimodal ToolMessage content; emits `tasks_steps` from todo_write progress events + reviewing_sources. | ✅ |
| message_builder.py | Core | Pure-function module for message preparation and timestamp injection. | ✅ |
| model_discipline.py | Config | Per-model execution discipline. Resolves model-family-specific behavior guidance (anti-narration, tool honesty, anti-negative-claim, proactive grounding search, XML tool-call defense, context-first check, proactive capability discovery, tool enforcement, per-family corrections for GPT/Claude/Gemini/DeepSeek/Qwen/GLM) and escalation contract prompt (conditional: only when escalation_target_llm is configured and differs from current model). | ✅ |
| reasoning_scrubber.py | Core | 流式清洗器。处理非标准模型泄漏在普通 content 流中的思考过程标签，将其跨 Chunk 无损转化为独立事件。导出 THINKING_TAG_NAMES 供渲染层 strip_thinking_tags 复用。 | ✅ |
| source_tracker.py | Core | Source reference forwarding capability for BaseAgent. | ✅ |
| step_builder.py | Core | Agent step data builder. Constructs frontend display data from tool names and arguments with per-too | ✅ |
| stream_buffer.py | Core | Harness engine-layer stream state persistence component. | ✅ |
| stream_compactor.py | Core | Provides StreamCompactor. | ✅ |
| stream_dispatcher.py | Core | StreamDispatcherMixin dispatches astream chunks to the output_queue; routes `swarm_fission` GraphInterrupt to dedicated SSE event (not approval). | ✅ |
| stream_executor.py | Core | Stream execution engine. Encapsulates the complete lifecycle of Agent.astream(). | ✅ |
| stream_recovery.py | Core | StreamRecoveryMixin composes overflow, failover, escalation, transient retry, iteration-limit (with grace-call summary), empty-response, truncation, steering, subagent, and goal continuation recovery strategies. | ✅ |
| stream_recovery_continuation.py | Core | StreamContinuationRecoveryMixin handles steering injection, subagent completion events, goal continuation status, and background goal terminal callbacks. | ✅ |
| stream_recovery_oneshot.py | Core | OneshotRecoveryMixin — targeted one-shot recovery for THINKING_SIGNATURE, IMAGE_TOO_LARGE, MEDIA_REJECTED, LONG_CONTEXT_TIER. | ✅ |
| stream_recovery_truncation.py | Core | StreamTruncationRecoveryMixin handles length/max-token continuation with progressive output budget boosting (ContextVar ephemeral_max_output_tokens), truncated tool-call auto-retry, and structured truncation warnings. | ✅ |
| types.py | Config | Streaming module core type definitions. Defines all stream event data types and enums (incl. TOOL_IMAGE_OUTPUT for multimodal tool outputs). | ✅ |
| utils.py | Core | Agent internal utility functions. Provides context validation, timestamp injection, agent behavior rules (anti-narration + tool honesty), and tool name normalization. | ✅ |

| Submodule | Description |
|-----------|-------------|
| broadcast/ | ToolBroadcastBus side-channel + ToolCallBroadcaster (chat UI via EventLogger→SSE). See [broadcast/_ARCH.md](broadcast/_ARCH.md). |

## Key Dependencies

- `toolkits`
- `utils`
