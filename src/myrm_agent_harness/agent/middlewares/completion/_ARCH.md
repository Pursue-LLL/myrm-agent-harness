# completion/

## Overview

Completion guard subsystem — finish gate, code verification, external evidence,
deliverable write claims, execution-claim grounding, per-turn evidence
disclosure, and mixed-message early termination.

Detailed design: [MIDDLEWARE_SYSTEM.md](../MIDDLEWARE_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public exports for CompletionGuard and helpers. | — |
| `completion_guard.py` | Core | Finish gate + Mixed Message Guard + independent sandbox re-run for code tasks. Orchestrates checklist, external evidence, deliverable write, execution-claim and PPT checks. Publishes the per-turn disclosure payload (evidence tier + staged artifacts) read by the post-run `message_end` event, with a per-run rejection budget keyed by the bound message id so concurrent runs cannot reset or exhaust each other. Mixed Message preserves effectful calls (`is_mutating_tool`, registry fail-closed) and interaction/UI carriers; only guaranteed side-effect-free non-interactive read-only tools are stripped. | ✅ |
| `completion_check_tool.py` | Internal | The `_completion_check` runtime hook: builds the model-facing blocking message for each reason and, with no reason set, returns the task-aware verification checklist from this run's records. | ✅ |
| `completion_guard_state.py` | Internal | Per-run guard state (rejection budget, forced-finish latch) and the per-turn disclosure registry (evidence tier, staged drafts), keyed by the bound message id with an LRU cap; `attach_disclosure_to_event()` feeds the `message_end` event once per turn. | ✅ |
| `completion_guard_safety.py` | Internal | Effectful tool detection SSOT (`is_mutating_tool`) with static mutation/interaction-UI alias sets and registry fail-closed fallback; consumed by Mixed Message Guard and server Cron post-run verification. | ✅ |
| `deliverable_auto_staging.py` | Internal | Automatic staging and LRU preservation for unwritten deliverables in `.myrm/staged_artifacts/`. | ✅ |
| `deliverable_confidence_tier.py` | Core | DeliverableConfidenceTier SSOT (VERIFIED, ARTIFACT, RESEARCH, PLAN), deterministic physical evidence resolver (measured 0.018 ms over a 66-record turn), and the disclosure policy (`should_disclose_tier`): evidence tiers are always shown, PLAN only when the answer itself makes a completion claim. | ✅ |
| `completion_guard_checklist.py` | Internal | Verification command classification, checklist builder, temporal ordering analysis. | ✅ |
| `completion_guard_external_evidence.py` | Internal | Freshness-sensitive external evidence gate (web/browser + MCP: PTC bash via ``skills.mcp_*`` and Direct FC via ``mcp__{server}__{tool}``; internal code-task requests are exempted from external-evidence requirements). | ✅ |
| `deliverable_write_verifier.py` | Internal | Zero-call deliverable write claim detection and unwritten deliverable heuristic sniffer. | ✅ |
| `execution_claim_verifier.py` | Internal | Completion-claim grounding against this run's tool records: verification claims (real test runners only; dry runs and zero-test outputs never ground a pass), outbound/irreversible action claims (MCP with outbound semantics, outbound commands, outbound tool names), and code-change claims (successful writes or shell mutations). Sentence-level scan with attribution/conditional/negation/explanation exclusions and request-intent gating for bare result forms; `has_completion_claim()` exposes the claim detection for the disclosure policy. | ✅ |
| `execution_claim_lexicon.py` | Internal | Declarative lexicons for the claim verifier: claim patterns, request-side intents, strict test-runner list, outbound command and tool-name vocabulary, and evidence-shape vetoes (dry runs, zero-test output, PATH rewrites, read-only MCP calls). | ✅ |
| `query_grounding_verifier.py` | Internal | Entity state/data query intent grounding and physical evidence verification (detects business entity queries e.g. orders/tickets/logistics, supports per-entity grounding map matching against tool arguments and outputs, blocks ungrounded hallucination when query tools were omitted or unsearched entities were fabricated, and halts fake success claims when query tools failed). | ✅ |
| `ppt_outline_verifier.py` | Internal | PPT reporting plan outline quality gate — detects PPT/slide-deck delivery and enforces the 4-dimensional rubric (concise titles, explicit takeaway per slide, concrete visual/data anchor, balanced density). | ✅ |

## Key Dependencies

- `agent.middlewares.tooling.tool_interceptor_middleware` — LoopGuard CallRecord window
- `agent.security.guards.loop_guard` — CallRecord, ToolGroup, VerificationCategory
- `toolkits.code_execution` — independent verification re-run sandbox
- `agent._internals.run_lifecycle.post_run_events` — attaches the per-turn disclosure payload via `attach_disclosure_to_event()` to the `message_end` event (the server persists it as message metadata)
