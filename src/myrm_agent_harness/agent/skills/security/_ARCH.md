# security/

## Overview
Export-time content sanitization for skill privacy protection.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports ContentSanitizer, Redaction, SanitizationResult, SecretKind. | — |
| content_sanitizer.py | Core | Detects secrets/paths/credentials via a rule table (each rule names the capture group holding the secret and a `SecretKind` code, so only the secret is replaced and quotes/keys/flags stay) and provides structured Diff for frontend preview; findings carry `kinds` codes, never display text, so callers localize them; a redacted file keeps the final line break it had. | ✅ |

## Key Dependencies

- `core.security.redact` — runtime regex patterns reused for export-time detection parity
