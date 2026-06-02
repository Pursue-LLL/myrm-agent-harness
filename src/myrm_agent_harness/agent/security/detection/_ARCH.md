# detection/

## Overview
Agent Security Detection module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public API exports for detection subsystem (classify_content, redact_pii, scan_for_leaks, etc.) | ✅ |
| content_boundary.py | Core | Content boundary defense core. Five-layer defense-in-depth (Unicode folding, structural framing strip, marker sanitization, random boundaries, pattern detection) for prompt injection prevention. | ✅ |
| leak_detector.py | Core | Output-side credential leak detector. 40+ credential pattern matchers (API key prefixes + blockchain + cloud infra + ENV/JSON/Header context + mnemonic + Shannon entropy + PEM block-level multiline redaction) for preventing secret exfiltration. | ✅ |
| pii_classifier.py | Core | Input-side PII classification engine. 30+ built-in regex patterns (bilingual CN/EN) with short-circu | ✅ |
| pii_redactor.py | Core | PII redactor. Type-aware smart masking (phone numbers retain first 3 and last 4 digits, emails retai | ✅ |
| pseudonym_store.py | Core | Local SQLite store for reversible PII pseudonymization. Maps original_text to typed placeholders (<TYPE_N>) with cross-session persistence. | ✅ |
| pseudonymizer.py | Core | Reversible PII pseudonymization engine. Replaces detected PII with typed placeholders via PseudonymStore, and provides a streaming-safe restorer with chunk-boundary buffering. | ✅ |
| deep_pii_detector.py | Core | LLM-based non-structured PII detector for deep scan mode. Batch-processes texts to identify 20+ semantic PII types. Protocol-based, fail-open. | ✅ |
| deep_pii_prompt.py | Core | Prompt template for LLM deep PII detection. PL2-PL4 classification with One-Shot example, covering 20+ non-structured privacy types. | ✅ |
| canary_guard.py | Core | Output-side injection success detector. Deterministic canary token — zero false positives, zero dependencies, microsecond latency. | ✅ |
| prompt_guard.py | Core | Input-side injection detector. 7+2 bilingual injection patterns with anti-obfuscation (leet speak, invisible Unicode, whitespace) for prompt injection defense. | ✅ |
| tool_result_validator.py | Core | Provides ValidationResult, validate_tool_result, should_apply_validation. | ✅ |
