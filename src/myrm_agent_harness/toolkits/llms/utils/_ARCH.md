# utils/

## Overview
LLM toollayer: JSON handles, modelparameter, log

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | LLM toollayer: JSON handles, modelparameter, log | — |
| litellm_utils.py | Core | LiteLLM utility functions. Provides JSON processing tools for handling LLM-generated malformed JSON. | ✅ |
| model_utils.py | Core | Model introspection — best-effort context window limit extraction from BaseChatModel | ✅ |
| logger.py | Core | LiteLLM API request/response logging utility. Provides detailed LLM API call logging with toggle sup | ✅ |
| proxy.py | Core | Egress proxy utilities: credential masking, URL validation with link-local/IMDS SSRF protection, HTTP status discrimination, and connectivity probing with TTL caching. | ✅ |

## Key Dependencies

- `core`
- `utils`
