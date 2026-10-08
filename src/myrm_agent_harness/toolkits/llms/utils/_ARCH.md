# utils/

## Overview
LLM toollayer: JSON handles, modelparameter, log

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | LLM toollayer: JSON handles, modelparameter, log | — |
| litellm_utils.py | Core | Tool-argument JSON recovery for malformed LLM output. `parse_tool_call_arguments_with_recovery` takes a `stream_complete` flag: `False` (provider stopped mid-generation, or never reported a finish) refuses every close-the-JSON repair and returns `strategy="truncated_stream_unverified", safe=False`, because closing partial JSON fabricates a valid-looking object missing unstreamed fields. Independent of that flag, a completion that would close a value cut off *inside a string* (path, command, file body) is refused with `strategy="truncated_mid_value", safe=False`: the closed prefix parses but is a shorter, valid-looking value (a truncated path or command is not a smaller version of the same request). Cuts at a number, literal, key or container boundary remain completable. | ✅ |
| truncated_json.py | Core | Pure helpers for truncated JSON: `close_truncated_json` terminates open strings and containers, completes number/literal tails and drops dangling keys; `ends_inside_string` reports whether the cut landed inside a string value. No I/O. | ✅ |
| model_kwargs.py | Core | Model-parameter compatibility: strip internal keys (`_in_fallback`, `_json_mode_fallback`), drop `response_format` for unsupported models (qwen-plus), and apply the Kimi function-calling temperature floor. | ✅ |
| model_utils.py | Core | Model introspection — best-effort context window limit extraction from BaseChatModel, and the documented per-response output ceiling of a model (`get_model_output_ceiling`, cached) with `clamp_budget_to_model_ceiling`, which limits an upward output-budget adjustment to that ceiling and never below a budget the provider already accepted | ✅ |
| logger.py | Core | LiteLLM API request/response logging utility. Provides detailed LLM API call logging with toggle sup | ✅ |
| proxy.py | Core | Egress proxy utilities: URL normalization (socks to socks5), credential masking, URL validation with link-local/IMDS SSRF protection, HTTP status discrimination, and connectivity probing with TTL caching. | ✅ |
| no_proxy_bypass.py | Core | `LanEndpointNoProxyManager` — `is_local_or_lan_endpoint` recognises localhost, RFC 1918 private subnets and local domain suffixes; `build_recommended_no_proxy_entries` builds the matching `NO_PROXY` list; `configure_bypass_client_kwargs` sets `trust_env=False` for such URLs so local Ollama/vLLM endpoints are not hijacked by `HTTP_PROXY` | — |

## Key Dependencies

- `core`
- `utils`
