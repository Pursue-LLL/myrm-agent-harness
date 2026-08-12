# redact/

## Overview

Secret redaction domain — masks API keys, tokens, and credentials before they
reach the LLM context or log files (Layer 2 output redaction). Three files by
concern: `patterns.py` holds the compiled regexes (single source of truth, also
consumed by `agent/skills/security/content_sanitizer.py`); `engine.py` owns the
bounded-replace pipeline and public APIs; `__init__.py` is the aggregation
facade exposing the public `core.security.redact` import surface.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Aggregation facade — re-exports engine + shared helpers (`_mask_token`). | ✅ |
| patterns.py | Core | Compiled detection regexes (token prefixes, ENV/JSON/Auth/header/URL userinfo/query/bare-token/JWT, YAML/colon + form-urlencoded configs, CLI `=` flags, control chars), word-boundary key validation, `_mask_token` / form-body / ENV/YAML/CLI replacers. | ✅ |
| engine.py | Core | Redaction engine — bounded replace (ReDoS guard), control-split token guard, `redact_sensitive_text`, `RedactingFormatter`, `escape_invisible_unicode`, `redact_for_llm`, `redact_for_display`. | ✅ |

## Key Dependencies

- None within `core.security` (foundation layer)

## Consumers

- `agent/security/redact.py` — thin facade re-exporting public + internal symbols
- `agent/skills/security/content_sanitizer.py` — imports `patterns.py` regexes for structured content masking
- `utils/errors.py`, `toolkits/browser/exceptions.py` — `redact_for_llm`
- `agent/middlewares/approval/_batch_decisions.py` — `redact_for_display`
- toolkits across browser / web_fetch / mcp / code_execution / memory — `redact_sensitive_text`
