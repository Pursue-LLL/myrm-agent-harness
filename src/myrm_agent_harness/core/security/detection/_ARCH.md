# core/security/detection/

## Overview
Security detection modules — PII classification, content boundary marking, information leak detection, prompt injection guard, intent router, pseudonymization, and semantic element risk classification.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Module public exports for core security detection subsystem. | — |
| content_boundary.py | Core | Content boundary marking — wraps untrusted/tool output with Nonce-guarded delimiters and privileged tag stripping; `extract_wrapped_payload` unwraps envelopes via symmetric pairing for programmatic (PTC) consumers. | ✅ |
| instruction_shape.py | Core | Instruction-shape detector — sentence-level agent-directed shapes (guardrail bypass, unattended execution, exfiltration, spoofed approval, agent command, untrusted-channel-write) in durable content. | ✅ |
| intent_router.py | Core | Intake-stage dangerous intent router — dual-tier regex & actionability detection for mass destruction, mass exfiltration, and privilege mutation. | ✅ |
| leak_detector.py | Core | Information leak detector — identifies sensitive data patterns in text (vendor prefixes, ENV/JSON/Header context, structural formats, entropy, mnemonic seeds); earlier redactions (`[REDACTED:*]` markers, `abcdef***...wxyz` partial masks) count as placeholders, so redacted text scans clean. | ✅ |
| password_heuristic.py | Core | Keyword-anchored password heuristic for secrets the leak detector misses — `find_password_spans` returns the secret's own span per keyword occurrence: a value the text introduces (`is`/`to`/`:`/`=`/`是`, plausibility-checked) else a generated-looking token nearby (4 classes among lower/upper/digit/strong symbol, within a tight window; the keyword and neighbouring capitalised words never win), plus numeric PIN/OTP/2FA codes anchored to keywords. `secret_value_span` is the shared value rule (trim, length, numeric/field-state/mask/identifier/template/URL rejection, already-redacted markers) also used by persistence for `key: value` assignments. Text without a keyword yields nothing. | ✅ |
| pii_classifier.py | Core | PII classifier — detects personally identifiable information (emails, phones, IDs, etc.). | ✅ |
| prompt_guard.py | Core | Prompt injection guard — 10 EN + 4 ZH injection categories with anti-obfuscation (leet speak, invisible Unicode, whitespace) and word-boundary precision. Two-tier score: `max_score` (every hit; audit trail and durable-store gates) vs `block_score` / `should_block` (only hits unambiguous on their own; consumed by the live-input guard and the rule-file loader, so plain role assignment like `Act as a translator` is audited but not blocked). Negated extraction verbs (`Never print the API keys`) are not reported. | ✅ |
| semantic_risk.py | Core | Semantic element risk lexicon (SSOT) — bilingual destructive/financial/account/admin/publish vocabulary classifying GUI controls (role + name) as high-risk; consumed by browser DOM and desktop AX interaction gates so all GUI channels share one identical gate vocabulary. | ✅ |
| harmful_state_detector.py | Core | Harmful psychological state detector — blocks self-harm/severe depression patterns from persistent memory storage. | ✅ |
| pseudonym_store.py | Core | Pseudonym store — persistent mapping between real values and pseudonyms. | ✅ |
| pseudonymizer.py | Core | Pseudonymizer — replaces PII with reversible pseudonyms using the pseudonym store. | ✅ |

## Key Dependencies

- `content_boundary.strip_invisible_unicode` — used by `instruction_shape` and `intent_router` for anti-obfuscation normalization before matching.
- No external runtime dependencies (foundation layer).
