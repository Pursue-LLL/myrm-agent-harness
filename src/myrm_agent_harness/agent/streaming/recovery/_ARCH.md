# agent/streaming/recovery/

## Overview
Streaming error-recovery strategies. **`stream_recovery.py`** composes the four mixins consumed by `stream_executor.py` via multiple inheritance.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports the four recovery mixins | ✅ |
| stream_recovery.py | Core | StreamRecoveryMixin — composes overflow, LLM failover, safety refusal fallback, escalation, transient retry, iteration-limit, empty-response, truncation, steering, subagent, and goal continuation recovery | ✅ |
| stream_recovery_continuation.py | Core | StreamContinuationRecoveryMixin — steering injection, subagent completion, goal continuation | ✅ |
| stream_recovery_oneshot.py | Core | OneshotRecoveryMixin — targeted one-shot recovery (THINKING_SIGNATURE / DUPLICATE_TOOL_USE_ID / IMAGE_TOO_LARGE / MEDIA_REJECTED / ALLOWED_TOOLS_TOOL_CHOICE_REJECTED / LONG_CONTEXT_TIER), with per-image and aggregate historical image eviction fallback | ✅ |
| stream_recovery_truncation.py | Core | StreamTruncationRecoveryMixin — length/max-token continuation, truncated tool-call retry, `reset_ephemeral_max_output_tokens` | ✅ |

## Key Dependencies

- `agent._internals.agent_recovery`
- `agent.errors.fault_side`
- `toolkits.llms.errors.classifier`
