# chat_model/

## Overview
LangChain LiteLLM chat-model adapter: aggregate root (`model.py`) plus sync/async generation & streaming mixins and shared exceptions.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Sub-package exports. | — |
| model.py | Core | `ChatLiteLLM`, `clean_model_kwargs`: config, bind_tools, structured_output, prompt-cache routing. Aggregate root composing the mixins below. | ✅ |
| exceptions.py | Core | Shared adapter exceptions (`EmptyChoicesError`/`EmptyStreamError`/`StreamStallTimeoutError`) and OpenAI param whitelist constants. | ✅ |
| message_mixin.py | Core | `ChatLiteLLMMessageMixin`: message normalization, developer-role promotion, reasoning_content stamp, image_url detail sanitization, ChatResult assembly. | ✅ |
| sync_mixin.py | Core | `ChatLiteLLMSyncMixin`: synchronous generation and streaming with empty-response retry and unified token-usage recording. | ✅ |
| async_mixin.py | Core | `ChatLiteLLMAsyncMixin`: asynchronous generation and streaming with concurrency gate and stream stall detection, unified token-usage recording. | ✅ |

## Key Dependencies

- `toolkits.llms.adapters` (converters / streaming / concurrency / stream_aggregator / tool_recovery / model_capability / safety_termination_detector)
- `utils.token_economics`
