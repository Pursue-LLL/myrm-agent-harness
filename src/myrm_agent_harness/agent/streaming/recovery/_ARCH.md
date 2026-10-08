# agent/streaming/recovery/

## Overview
Streaming error-recovery strategies. **`stream_recovery.py`** composes the four mixins consumed by `stream_executor.py` via multiple inheritance.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports the four recovery mixins | ✅ |
| context_pressure_gate.py | Gate | Pre-flight context pressure gate, token budget compaction, and presumed-overflow recovery handler | ✅ |
| stream_recovery.py | Core | StreamRecoveryMixin — composes overflow, LLM failover, safety refusal fallback, escalation, transient retry, iteration-limit, empty-response, truncation, steering, subagent, and goal continuation recovery | ✅ |
| stream_recovery_budget.py | Core | StreamOutputBudgetMixin — output-budget half of truncation recovery, inherited by `StreamTruncationRecoveryMixin`: `_boost_output_tokens` sets the one-shot larger budget a retry runs with (2x/3x/4x of the base, capped at `MAX_EPHEMERAL_OUTPUT_TOKENS` and at the model's documented output ceiling; a base that already reaches a cap or ceiling is kept as is), starting from the configured `max_tokens` or, failing that, a thinking model's headroom floor | ✅ |
| stream_recovery_continuation.py | Core | StreamContinuationRecoveryMixin — steering injection, subagent completion, goal continuation | ✅ |
| stream_recovery_oneshot.py | Core | OneshotRecoveryMixin — targeted one-shot recovery (THINKING_SIGNATURE / DUPLICATE_TOOL_USE_ID / IMAGE_TOO_LARGE / MEDIA_REJECTED / ALLOWED_TOOLS_TOOL_CHOICE_REJECTED / LONG_CONTEXT_TIER), with per-image and aggregate historical image eviction fallback | ✅ |
| stream_recovery_truncation.py | Core | StreamTruncationRecoveryMixin — length/max-token continuation, retry of truncated or withheld tool calls (one retry with a larger output budget from `StreamOutputBudgetMixin`), reasoning-only retry (non-resume) + report-only (resume), `reset_ephemeral_max_output_tokens` | ✅ |

## Invariants

- **Tag-wrapped reasoning is not content.** Providers that inline the thinking phase into
  `content` (MiniMax emits `<think>…</think>`) look like they produced user-visible text.
  `_has_inline_reasoning` strips `THINKING_TAG_NAMES` blocks before the content probe, so a
  reasoning-only reply routes to recovery instead of being mistaken for an answer — the
  stream layer already strips those tags, meaning the user saw an empty turn.
- **A withheld tool call is a tool call.** Arguments that are cut off or unparseable are never
  executed: the adapter records them in `additional_kwargs["tool_call_recovery"]` (`safe=False`)
  and emits no `tool_calls`, so LangGraph ends the turn on a message with nothing else in it.
  `event_handlers` therefore keeps such a message in `collected_messages`, the length-truncation
  handler fires on it whatever `finish_reason` the provider reported, and
  `_has_tool_calls` — the one predicate shared by the truncation and empty-response handlers — counts
  it, so the turn is retried once or reported (`tool_call_truncated`); it never ends silently or
  is mistaken for an empty reply. The retry re-sends the original request plus one appended hint
  and a one-shot larger `max_tokens`; the prompt prefix is untouched, so the provider cache hits.
- **Resume turns cannot be retried.** `agent_input` is a `Command` that LangGraph has already
  consumed; replaying one advances no work (verified: it emits zero stream chunks). Recovery
  therefore reports the condition and ends. It must **not** raise the output budget as a
  consolation: the handler returns `False`, so the caller breaks the streaming loop and the
  executor's `finally` clears the ephemeral override — a raise there can never outlive the turn
  and only emits a misleading "budget raised" log. Prevention lives upstream: `thinking_headroom`
  floors a thinking model's `max_tokens` at creation time.
- **Budget boost needs a real base.** `_boost_output_tokens` scales from the configured
  `max_tokens`; with none configured it falls back to `thinking_output_floor` for known thinking
  models and stays a safe no-op otherwise (an unknown ceiling could otherwise be overshot). The scaled
  budget is also bounded by the model's documented output ceiling (`clamp_budget_to_model_ceiling`), so a
  retry cannot turn a truncated answer into a provider 400; a ceiling below the base is a stale table
  entry — the base was already served — and is ignored.

## Key Dependencies

- `agent._internals.agent_recovery`
- `agent.errors.fault_side`
- `agent.config.llm_safety` (grace call re-pairs its history through `normalize_messages`)
- `toolkits.llms.errors.classifier`
