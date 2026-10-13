# security/

## Overview

Security enforcement as middleware — security boundary rules injection and the
eight-layer guardrail defense (intent router, prompt guard, PII, leak detection, canary).

Detailed design: [MIDDLEWARE_SYSTEM.md](../MIDDLEWARE_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public exports for security middleware classes. | — |
| `security_boundary_middleware.py` | Core | Adds `SECURITY_BOUNDARY_SYSTEM_RULES` as an independent SystemMessage once per run; state merges it by appending, so it sits behind the latest user message and the main System Prompt is untouched. | ✅ |
| `text_blocks.py` | Core | Applies a text transform to a message content that is text or a text + image block list (image data and other fields pass through untouched). | ✅ |
| `pii_actions.py` | Core | Per-level PII actions (warn, redact, pseudonymize, block) under a `PrivacyPolicy`; shared by the guardrail's input and output layers, the tool-result PII guard and the outbound privacy guard. `apply_privacy_policy` is the one entry for "classify, then act under the policy" (a policy-blocked text is fully redacted instead). Audit entries and logs can be switched off for silent re-screening. | ✅ |
| `outbound_privacy_guard.py` | Core | The privacy policy at the model-call boundary: registered into `toolkits.llms` `outbound_guard`, it screens the text of every non-system message of every model call (title, suggestions, compaction, memory extraction, sub-agents, anything that bypasses the agent loop) under the run policy, else the process policy (`set_process_privacy_policy`, installs the guard when enabled). It acts like the loop does (warn leaves text alone; redact / pseudonymize / block are stable under repetition), so text the main loop already screened passes byte-identical and the prompt cache is unharmed; the main loop sets `privacy_enforced_by_loop` so it is not processed twice. Fail-closed: a guard error aborts the call. Also exposes `sanitize_outbound_text` for callers that must mask before they cut or ground text. Custom keywords and patterns are detected (blocking, routing, tracker) but `redact_pii` does not mask them. | ✅ |
| `user_input_guard.py` | Core | Screens the user-authored messages (text or text blocks; runtime-synthetic messages are skipped) through the intent router, prompt guard and PII guard in turn; a block is final. The latest message is screened in full: audit entries, logs, the safety caution and PII rewrites happen on the first model call of an input only, and PII is classified on every call so the privacy tracker follows the message. Earlier messages, which reach the model again each turn, get the policy silently (PII rewrite; a block under `fail_closed` injection or intent policy) with no audit, logs or caution, and are skipped when no policy acts on them. | ✅ |
| `security_guardrail_middleware.py` | Core | Eight-layer defense integrated as an AgentMiddleware: circuit-breaker cognition, input screening (`user_input_guard`), tool-result redact (text and the text blocks of block-list results; image data is not scanned), canary guard (text and tool-call arguments, also when the model wrote no text), leak detector, PII redact, history redact. A redaction replaces only the message `content` (`model_copy`), so status, metadata, marks and usage stay. While the model call runs it marks the loop as the privacy enforcer (`privacy_enforced_by_loop`, only when its policy is enabled) so the outbound guard stays out of the way. | ✅ |

## Key Dependencies

- `agent.security.detection` — content_boundary, intent_router, leak_detector, prompt_guard, pii, canary_guard
- `agent.security.guards.privacy_tracker`, `agent.security.audit` — per-run privacy level and decision audit log
- `agent.middlewares._message_origin` — tells the user's own message from a runtime-injected one
- `agent.middlewares._session_context` — canary token, privacy policy, terminal errors
