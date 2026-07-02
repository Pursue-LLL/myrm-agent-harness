# core/security/detection/

## Overview
Security detection modules — PII classification, content boundary marking, information leak detection, prompt injection guard, and pseudonymization.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Module docstring. | — |
| content_boundary.py | Core | Content boundary marking — wraps untrusted/tool output with delimiters for downstream detection. | ✅ |
| leak_detector.py | Core | Information leak detector — identifies sensitive data patterns in text. | ✅ |
| pii_classifier.py | Core | PII classifier — detects personally identifiable information (emails, phones, IDs, etc.). | ✅ |
| prompt_guard.py | Core | Prompt injection guard — detects prompt injection attempts in user/tool input. | ✅ |
| harmful_state_detector.py | Core | Harmful psychological state detector — blocks self-harm/severe depression patterns from persistent memory storage. | ✅ |
| pseudonym_store.py | Core | Pseudonym store — persistent mapping between real values and pseudonyms. | ✅ |
| pseudonymizer.py | Core | Pseudonymizer — replaces PII with reversible pseudonyms using the pseudonym store. | ✅ |

## Key Dependencies

- No internal dependencies (foundation layer)
