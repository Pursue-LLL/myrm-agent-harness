# core/security/detection/

## Overview
Security detection modules — PII classification, content boundary marking, information leak detection, prompt injection guard, intent router, and pseudonymization.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Module public exports for core security detection subsystem. | — |
| content_boundary.py | Core | Content boundary marking — wraps untrusted/tool output with Nonce-guarded delimiters and privileged tag stripping; `extract_wrapped_payload` unwraps envelopes via symmetric pairing for programmatic (PTC) consumers. | ✅ |
| instruction_shape.py | Core | Instruction-shape detector — sentence-level agent-directed shapes (guardrail bypass, unattended execution, exfiltration, spoofed approval, agent command, untrusted-channel-write) in durable content. | ✅ |
| intent_router.py | Core | Intake-stage dangerous intent router — dual-tier regex & actionability detection for mass destruction, mass exfiltration, and privilege mutation. | ✅ |
| leak_detector.py | Core | Information leak detector — identifies sensitive data patterns in text, incl. password-like heuristic and numeric-credential (PIN/OTP/2FA) detection. | ✅ |
| pii_classifier.py | Core | PII classifier — detects personally identifiable information (emails, phones, IDs, etc.). | ✅ |
| prompt_guard.py | Core | Prompt injection guard — detects prompt injection attempts in user/tool input. | ✅ |
| harmful_state_detector.py | Core | Harmful psychological state detector — blocks self-harm/severe depression patterns from persistent memory storage. | ✅ |
| pseudonym_store.py | Core | Pseudonym store — persistent mapping between real values and pseudonyms. | ✅ |
| pseudonymizer.py | Core | Pseudonymizer — replaces PII with reversible pseudonyms using the pseudonym store. | ✅ |

## Key Dependencies

- `content_boundary.strip_invisible_unicode` — used by `instruction_shape` and `intent_router` for anti-obfuscation normalization before matching.
- No external runtime dependencies (foundation layer).
