# routing/

## Overview

Pre-agent routing layer. Determines which LLM tier/model to use before Agent creation.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Lazy-import init | — |
| complexity_router.py | Core | Two-phase (rule+LLM judge) task complexity routing with session momentum. Selects SIMPLE/STANDARD/REASONING model tier. | ✅ |
| privacy_routing.py | Core | Privacy-aware model routing. Routes to appropriate models based on PII sensitivity levels. | ✅ |
| specialty_router.py | Core | Cross-vendor task domain specialty classification and routing (CODE, LONG_DOC, REASONING, MULTIMODAL, CASUAL, GENERAL) with session momentum & fallback chain. | ✅ |

## Key Dependencies

- `agent.config` (LLMConfig)

## Design Notes

- **Momentum**: `complexity_router` supports session momentum — short follow-up messages inherit the conversation's recent routing tier to prevent quality degradation during multi-turn complex tasks. Applied on **both** the rule path and the LLM-judge path: a Phase-2 verdict (fresh or cached) is smoothed identically to a rule result, so a short ambiguous follow-up cannot downgrade an ongoing complex task. Image/video queries carry a **vision floor**: `_apply_momentum(has_image=True)` never downgrades below STANDARD, because SIMPLE selects the light model (not vision-guaranteed) and a text-only history must not strip the user's media (the rule phase already forces STANDARD+ via `image_input` +6.0). Upgrades to REASONING remain allowed.
- **LLM judge**: Phase 2 classifies ambiguous cases via a filter LLM with a bounded timeout (`_JUDGE_TIMEOUT_S`) — a hung judge call degrades to STANDARD with reason `llm_judge_unavailable` instead of blocking routing. Degraded verdicts (timeout / exception / unparseable output) are **not cached**: `_llm_judge_classify` returns `None` on degradation and `route_task` skips the judge cache (judge verdicts never enter the unbounded dedup cache), so a transient judge failure can never pin the default tier for the cache TTL — the next identical query is re-judged once the judge recovers. Callers create the judge with deterministic low temperature (0.0) to keep classification stable.
- **Content dedup (MR-18)**: exact-text routing results are cached to skip repeated scoring. The cache holds **pure, context-free rule verdicts only** (`rule_result`) — never momentum- or min-tier-adjusted results, which are session-local, and never LLM-judge verdicts, which are managed exclusively by the TTL-bounded `_judge_cache` (the judge branch never reads this cache, so duplicating verdicts here would only create an unbounded stale copy for the rule branch to mis-read). Cache keys are scoped by image presence (`_dedup_key`), so a text-only verdict never satisfies an image query (image tasks require vision-capable models). On a dedup hit the session momentum is still re-applied, mirroring the judge-cache path: cached tiers are raw classifications, and momentum recomputes per-turn. `min_tier` requests skip dedup reads and writes entirely, so a regenerate escalation cannot leak into later plain requests.
- **Min-tier floor**: `route_task(min_tier=...)` enforces a minimum tier regardless of classification result. Used by callers for complaint-up escalation (regenerate → automatic tier upgrade).
- **Penalty feedback**: `record_misroute(tier)` records misrouted tiers so PenaltyTracker reduces future misrouting probability (24h decay). `route_task(penalty_tracker=...)` accepts a custom tracker (forwarded to the rule phase); when omitted the global default shared with `record_misroute` is used. Complaint-up callers skip `record_misroute` when the last tier is the highest one (REASONING): it has nothing to escalate to, so penalizing it would only degrade future routing (the system gets "dumber" right after a user dissatisfaction).
- **Cache-friendly**: Routing runs before Agent creation, so it does not affect system prompt cache hit rates.
- **Extensible**: All routers accept custom keyword sets and configuration overrides via function parameters.
- **LLM proxy**: Cursor/Codex raw LLM passthrough is out of scope — `/v1` is Agent API only.
