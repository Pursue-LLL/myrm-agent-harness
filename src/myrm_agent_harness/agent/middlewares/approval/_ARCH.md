# approval/

## Overview
Tool approval subsystem — Human-in-the-Loop approval flow.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Tool approval subsystem — Human-in-the-Loop approval flow. | — |
| batch_processor.py | Core | Batch security evaluation — `evaluate_tool_batch`. YOLO auto-approve (DENY always enforced except interactive smart-deny override). Fast-Path read-only MCP. **Pattern allowlist** auto-approve via `allowlist.find_matching_entry(..., command=shell_command, session_id=current_session_id)` when action is ASK; discriminates `ALLOWLIST_SESSION_ALLOW` vs `ALLOWLIST_AUTO_APPROVE`. Emits `SANDBOX_AUTO_BYPASS` audit traces when running in sandbox environments. `is_interactive` kwarg: when True, LLM DENY routes to `pending_approval` (with `smart_denied` extra_ctx) instead of `auto_denied`, allowing user once-override. Marks `extra_ctx["high_risk"]` for ESCALATE threats, Taint conflicts, LLM UNCERTAIN scenarios, socially irreversible actions, protected instruction mutations (`protected_instruction`), and Auto Mode Suspended (`extra_ctx["auto_mode_suspended"]`) to prevent permanent allowlisting. Supports `classify_all_shell_in_auto_mode` for full shell intent review in auto mode. | ✅ |
| _batch_decisions.py | Internal | Interrupt payload and decision application (edit shell re-gate). Smart-denied payloads restrict `allowedDecisions` to approve+reject only and carry `smartDenied`+`reviewerReason` for frontend rendering. High-risk scenarios (ESCALATE, Taint, LLM UNCERTAIN), socially irreversible actions (`sociallyIrreversible`), Auto Mode Suspended (`autoModeSuspended`), protected instruction mutations (`protected_instruction`), and financial transactions emit `hideAllowAlways` in reviewConfig. Financial spend actions bind and strictly verify `action_digest` against parameter tampering and auto-inject `idempotency_key` into payment tools (Stripe). Mutable script operands revalidate content SHA-256 against approval snapshot at final boundary to prevent TOCTOU execution drift (CVE-2026-32921). Unified `_should_block_allow_always` guard combines integration-mutation + protected-instruction-mutation + high_risk + smart_denied + financial + socially irreversible + suspended checks as backend safety net. Shared `_try_add_to_allowlist` handles allowlist writes for both approve and edit branches, forwarding `ttl_seconds` for time-bound auto-revoking grants. | ✅ |
| _batch_review.py | Internal | LLM-based security review, runtime domain tracking, and skill hook evaluation. | ✅ |
| denial_diagnostic_bridge.py | Core | Denial diagnostic bridge connecting security auto-review denials to Dots-style 4-way adaptive resolution. | ✅ |
| intent_ledger.py | Core | User intent ledger preserving task anchors and directives for reasoning-blind approval classification. | ✅ |
| helpers.py | Core | Denial tracking, **allow-always four scopes** (permission/tool/exact/pattern via `derive_command_pattern`), time-bound auto-revocation (`ttl_seconds` → `expires_at`), session-scoped in-memory isolation, allowlist persistence. | ✅ |
| middleware.py | Core | Bridges the Permission Engine with the LangGraph tool pipeline. Computes `is_interactive` (not cron, not shadow) and passes to `evaluate_tool_batch`. Auto-denies approval for shadow agents (no UI channel). Fires APPROVAL_CORRECTION hook for user edits only (rejections stay in the audit trail); no built-in handler is registered, the event is an extension point for user-defined hooks. | ✅ |
| rate_limiter.py | Core | Approval rate limiter. Independent from core approval logic for easy testing and configuration. | ✅ |
| scheduler.py | Core | HITL timeout scheduler — auto-resumes agents when approval or Web clarification requests expire. Approval uses the global decision format; clarification uses `resume_value_override` (empty dict → no_answer). Idempotent resolution per key: the timer claims the key itself and never cancels its own task, while the manual path's `resolve_if_first` claims and cancels the timer, so the loser of the race is a no-op and a suspending timeout callback is not aborted. `reopen(key)` re-arms resolution when a resumed run stopped at a new interrupt that carries no timer. | ✅ |
| tiered_risk_evaluator.py | Core | Three-tier operation risk adaptive evaluator (READ / WRITE / HIGH_RISK) with dynamic brake and NEED_CONFIRMATION token generation. | ✅ |

## Key Dependencies

- `observability`
- `core.hooks` (APPROVAL_CORRECTION event)
