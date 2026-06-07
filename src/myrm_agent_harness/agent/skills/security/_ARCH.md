# security/

## Overview
Export-time content sanitization for skill privacy protection.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports ContentSanitizer, Redaction, SanitizationResult. | — |
| content_sanitizer.py | Core | Detects secrets/paths/credentials and provides structured Diff for frontend preview. | ✅ |

## Key Dependencies

- `core.security.redact` — runtime regex patterns reused for export-time detection parity
