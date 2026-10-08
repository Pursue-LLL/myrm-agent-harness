# security/

## Overview
Export-time content sanitization for skill privacy protection.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports ContentSanitizer, Redaction, SanitizationResult. | — |
| content_sanitizer.py | Core | Detects secrets/paths/credentials via a rule table (each rule names the capture group holding the secret, so only the secret is replaced and quotes/keys/flags stay) and provides structured Diff for frontend preview; a redacted file keeps the final line break it had. | ✅ |

## Key Dependencies

- `core.security.redact` — runtime regex patterns reused for export-time detection parity
