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
| stream_recovery_truncation.py | Core | StreamTruncationRecoveryMixin — length/max-token continuation, truncated tool-call retry, reasoning-only retry (non-resume) + report-only (resume), `reset_ephemeral_max_output_tokens` | ✅ |

## Invariants

- **Tag-wrapped reasoning is not content.** Providers that inline the thinking phase into
  `content` (MiniMax emits `<think>…</think>`) look like they produced user-visible text.
  `_has_inline_reasoning` strips `THINKING_TAG_NAMES` blocks before the content probe, so a
  reasoning-only reply routes to recovery instead of being mistaken for an answer — the
  stream layer already strips those tags, meaning the user saw an empty turn.
- **Resume turns cannot be retried.** `agent_input` is a `Command` that LangGraph has already
  consumed; replaying one advances no work (verified: it emits zero stream chunks). Recovery
  therefore reports the condition and ends. It must **not** raise the output budget as a
  consolation: the handler returns `False`, so the caller breaks the streaming loop and the
  executor's `finally` clears the ephemeral override — a raise there can never outlive the turn
  and only emits a misleading "budget raised" log. Prevention lives upstream: `thinking_headroom`
  floors a thinking model's `max_tokens` at creation time.
- **Budget boost needs a real base.** `_boost_output_tokens` scales from the configured
  `max_tokens`; with none configured it falls back to `thinking_output_floor` for known thinking
  models and stays a safe no-op otherwise (an unknown ceiling could otherwise be overshot).

## Key Dependencies

- `agent._internals.agent_recovery`
- `agent.errors.fault_side`
- `toolkits.llms.errors.classifier`
