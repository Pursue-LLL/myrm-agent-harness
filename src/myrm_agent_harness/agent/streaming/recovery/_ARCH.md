# agent/streaming/recovery/

## Overview
Streaming error-recovery strategies. **`stream_recovery.py`** composes the recovery mixins consumed by `stream_executor.py` via multiple inheritance.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports the four recovery mixins | ✅ |
| context_pressure_gate.py | Gate | Pre-flight context pressure gate, token budget compaction, and presumed-overflow recovery handler (a 400 that states the model's own output ceiling is never presumed to be an overflow) | ✅ |
| goal_session.py | Core | `goal_session_id(ctx)`: the goal lookup key of a run (chat id, else session id, else message id); shared by goal continuation and provider-window parking so both address the same goal | ✅ |
| stream_recovery.py | Core | StreamRecoveryMixin — composes overflow, LLM failover (with fast-failover on is_quota_exhausted), safety refusal fallback, escalation, transient retry (short-circuited on quota exhaustion), iteration-limit, empty-response, truncation, steering, subagent, and goal continuation recovery | ✅ |
| stream_recovery_budget.py | Core | StreamOutputBudgetMixin — output-budget half of truncation recovery, inherited by `StreamTruncationRecoveryMixin`: `_boost_output_tokens` sets the one-shot larger budget a retry runs with (2x/3x/4x of the base, capped at `MAX_EPHEMERAL_OUTPUT_TOKENS` and at the model's documented output ceiling; a base that already reaches a cap or ceiling is kept as is), starting from the configured `max_tokens` or, failing that, a thinking model's headroom floor | ✅ |
| stream_recovery_continuation.py | Core | StreamContinuationRecoveryMixin — steering injection, subagent completion, goal continuation | ✅ |
| stream_recovery_oneshot.py | Core | OneshotRecoveryMixin — targeted one-shot recovery (THINKING_SIGNATURE / DUPLICATE_TOOL_USE_ID / IMAGE_TOO_LARGE / MEDIA_REJECTED / ALLOWED_TOOLS_TOOL_CHOICE_REJECTED / LONG_CONTEXT_TIER); image surgery delegates to `stream_recovery_image_shrink` | ✅ |
| stream_recovery_image_shrink.py | Core | Provider image-limit recovery primitives: `parse_image_max_dimension` reads the ceiling the provider states (default 8000), `shrink_oversized_images` re-compresses each over-limit base64 image against both the base64 byte ceiling and the pixel ceiling (a pixel-correct downscale is accepted even when its bytes grew, a byte-triggered shrink that did not shrink is refused), and falls back to `evict_aggregate_historical_images` — older images degraded to 512px WebP or replaced by a semantic placeholder while the latest turn is protected — when no single image is oversized but the aggregate payload is | ✅ |
| stream_recovery_window.py | Core | ProviderWindowRecoveryMixin — `_handle_provider_window` for RATE_LIMIT / BILLING / OVERLOADED errors after model failover and before blind transient backoff: reads the provider-stated retry boundary once (`extract_provider_window`), then serves a ≤300 s wait exactly in-turn (`WindowAction.RETRY`), parks the running goal until the reset (`park_goal_for_provider_window`, `WindowAction.HELD`), or ends the turn at once with the real reset time (`WindowAction.FAIL`; `cooldown_remaining_ms` rides the error context). Also owns the cancel-aware sleep shared with transient retry | ✅ |
| turn_retry_state.py | Core | `TurnRetryState` — per-attempt one-shot recovery guards (format/payload, reasoning effort, PAAS 1305) and restart signals, bound fresh to StreamContext per API attempt so a guard fires at most once and prompt cache keys survive | — |
| stream_recovery_truncation.py | Core | StreamTruncationRecoveryMixin — length/max-token continuation, retry of truncated or withheld tool calls (one retry with a larger output budget from `StreamOutputBudgetMixin`), reasoning-only retry (non-resume) + report-only (resume), `reset_ephemeral_max_output_tokens` | ✅ |
| `disconnection_recovery.py` | Core | Resilient disconnection recovery manager with offline action staging. | ✅ |
| `recovery_types.py` | Core | Domain types for event replay buffer and resilient disconnection recovery. | ✅ |
| `replay_buffer.py` | Core | Circular event replay buffer with monotonic sequence ordering and gap detection. | ✅ |

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
- **An output ceiling is not an overflow.** A 400 stating the model's own `max_tokens` ceiling has
  nothing to do with context size. The adapter loop (`adapters/chat_model/output_cap_recovery.py`)
  lowers `max_tokens` and retries; when it declines, `is_presumed_overflow` declines too (it reads the
  same wording through `errors.output_limit.parse_output_limit`), so a high-occupancy session is not
  compacted — a destructive step that cannot cure the error — and the original error surfaces.
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

- **Retry timing follows the provider-stated boundary.** When the provider says when the window reopens,
  `_handle_provider_window` is the only retry policy: a short wait is slept exactly (cancel-aware), a
  longer one parks the goal as `WAIT` (`wait_kind=usage_limit`, `wait_resume_at`) and ends the turn, and a
  boundary beyond the 24 h hold cap or a spent quota with no boundary fails at once. Blind transient
  backoff only runs when the provider gave no signal. A goal that held without completing a turn in
  between is paused after `MAX_NO_PROGRESS_HOLDS`, so a provider that keeps rejecting cannot loop forever.

## Key Dependencies

- `agent._internals.agent_recovery`
- `agent.errors.fault_side`
- `agent.config.llm_safety` (grace call re-pairs its history through `normalize_messages`)
- `toolkits.llms.errors.classifier`
