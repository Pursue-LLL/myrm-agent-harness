# diagnostics/

## Overview
Error diagnostics component. Provides LLM error classification, context extraction, and structured diagnostic results.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Error diagnostics — data types (ErrorContext, DiagnosticResult) and re-exports. | ✅ |
| engine.py | Core | LLMErrorDiagnostic — error classification engine with 9 diagnostic branches (connection, billing, api_key, model, rate_limit, response_format, context_overflow, timeout, unknown) + custom endpoint variants + truncation diagnostics + cooldown hints. | ✅ |

| Submodule | Description |
|-----------|-------------|
| i18n/ | Framework-level i18n for LLM error diagnostics; bundled `locales/*.json` (en/zh-CN/ja/ko/de), override via `MYRM_LOCALES_DIR` |
