# approval/

## Overview
Tool approval subsystem — Human-in-the-Loop approval flow with correction learning.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Tool approval subsystem — Human-in-the-Loop approval flow. | — |
| batch_processor.py | Core | Batch security evaluation — `evaluate_tool_batch`. YOLO auto-approve (DENY always enforced except interactive smart-deny override). Fast-Path read-only MCP. **Pattern allowlist** auto-approve via `allowlist.find_matching_entry(..., command=shell_command, session_id=current_session_id)` when action is ASK; discriminates `ALLOWLIST_SESSION_ALLOW` vs `ALLOWLIST_AUTO_APPROVE`. Emits `SANDBOX_AUTO_BYPASS` audit traces when running in sandbox environments. `is_interactive` kwarg: when True, LLM DENY routes to `pending_approval` (with `smart_denied` extra_ctx) instead of `auto_denied`, allowing user once-override. Marks `extra_ctx["high_risk"]` for ESCALATE threats, Taint conflicts, LLM UNCERTAIN scenarios, socially irreversible actions, protected instruction mutations (`protected_instruction`), and Auto Mode Suspended (`extra_ctx["auto_mode_suspended"]`) to prevent permanent allowlisting. Supports `classify_all_shell_in_auto_mode` for full shell intent review in auto mode. | ✅ |
| _batch_decisions.py | Internal | Interrupt payload and decision application (edit shell re-gate). Smart-denied payloads restrict `allowedDecisions` to approve+reject only and carry `smartDenied`+`reviewerReason` for frontend rendering. High-risk scenarios (ESCALATE, Taint, LLM UNCERTAIN), socially irreversible actions (`sociallyIrreversible`), Auto Mode Suspended (`autoModeSuspended`), protected instruction mutations (`protected_instruction`), and financial transactions emit `hideAllowAlways` in reviewConfig. Financial spend actions bind and strictly verify `action_digest` against parameter tampering and auto-inject `idempotency_key` into payment tools (Stripe). Mutable script operands revalidate content SHA-256 against approval snapshot at final boundary to prevent TOCTOU execution drift (CVE-2026-32921). Unified `_should_block_allow_always` guard combines integration-mutation + protected-instruction-mutation + high_risk + smart_denied + financial + socially irreversible + suspended checks as backend safety net. Shared `_try_add_to_allowlist` handles allowlist writes for both approve and edit branches, forwarding `ttl_seconds` for time-bound auto-revoking grants. | ✅ |
| _batch_review.py | Internal | LLM-based security review, runtime domain tracking, and skill hook evaluation. | ✅ |
| correction_learning.py | Core | HITL correction learning — converts approval edits/rejects into persistent SemanticMemory preferences and ProceduralMemory rules. Zero LLM cost (deterministic dict-diff classification). Fires on APPROVAL_CORRECTION hook. | ✅ |
| helpers.py | Core | Denial tracking, **allow-always four scopes** (permission/tool/exact/pattern via `derive_command_pattern`), time-bound auto-revocation (`ttl_seconds` → `expires_at`), session-scoped in-memory isolation, allowlist persistence. | ✅ |
| middleware.py | Core | Bridges the Permission Engine with the LangGraph tool pipeline. Computes `is_interactive` (not cron, not shadow) and passes to `evaluate_tool_batch`. Auto-denies approval for shadow agents (no UI channel). Fires APPROVAL_CORRECTION hook after decisions for correction learning. | ✅ |
| rate_limiter.py | Core | Approval rate limiter. Independent from core approval logic for easy testing and configuration. | ✅ |
| scheduler.py | Core | HITL timeout scheduler — auto-resumes agents when approval or Web clarification requests expire. Approval uses global decision format; clarification uses `resume_value_override` (empty dict → no_answer). Idempotent `resolve_if_first` prevents race conditions between timeout auto-resume and manual user resume. | ✅ |

## Key Dependencies

- `observability`
- `core.hooks` (APPROVAL_CORRECTION event)
- `toolkits.memory` (SemanticMemory, ProceduralMemory persistence)
