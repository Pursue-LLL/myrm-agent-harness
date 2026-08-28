# wire/

## Overview
OpenCode multi-wire transport for ChatLiteLLM: Responses API (`/v1/responses`) and Anthropic Messages (`/v1/messages`).

## File Index

| File | Role | Description |
|------|------|-------------|
| __init__.py | Package | Re-exports wire transport helpers (params, translator, normalizer). |
| translator.py | Core | Chat messages → Responses input; reasoning item replay; tool_calls/function_call_output; system → instructions |
| normalizer.py | Core | Responses payload/events → chat-completions shape; preserve `responses_reasoning_items`; failed/error SSE → ResponsesStreamError |
| params.py | Core | Build litellm.responses kwargs (reasoning, include) from ChatLiteLLM call params |
| anthropic_params.py | Core | Anthropic Messages wire overrides for OpenCode Go minimax/qwen |
| invocation.py | Core | Sync/async invoke + stream adapters; fail-open retry on `invalid_encrypted_content` |

## POS
Harness-only protocol layer. Vendor routing tables live in server `app/core/wire/`.
