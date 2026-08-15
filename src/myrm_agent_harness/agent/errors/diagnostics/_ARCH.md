# diagnostics/

## Overview
Error diagnostics component. Provides LLM error classification, context extraction, and structured diagnostic results.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Error diagnostics — data types (ErrorContext, DiagnosticResult) and re-exports. | ✅ |
| engine.py | Core | LLMErrorDiagnostic — error classification engine (connection, tls_certificate, custom_endpoint_unreachable, billing, api_key, custom_model_not_found, model, rate_limit, response_format_error, context_overflow, timeout, unknown) + truncation diagnostics (thinking_budget_exhausted, tool_call_truncated, tool_call_retry, text_continuation, text_continuation_exhausted) + cooldown hints + recovery action mapping. | ✅ |
| types.py | Core | ErrorContext and DiagnosticResult frozen dataclasses for structured LLM error diagnosis. | ✅ |

| Submodule | Description |
|-----------|-------------|
| i18n/ | Framework-level i18n for LLM error diagnostics; bundled `locales/*.json` (en/zh-CN/ja/ko/de), override via `MYRM_LOCALES_DIR` |
