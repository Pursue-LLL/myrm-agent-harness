# adapters/

## Overview
LLM adapter layer: LangChain-compatible LiteLLM interface, provider-specific message compatibility shims, message converters, streaming, tool call parsing, schema normalization, and concurrency control.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Module exports | — |
| chat_model.py | Core | LangChain LiteLLM adapter for unified multi-model invocation, including provider-aware message normalization (MiniMax system→human demotion, OpenAI GPT-5+/Codex/o-series system→developer promotion), reasoning_content auto-stamp for thinking-mode models (DeepSeek/Kimi/MiMo), and per-call `allowed_openai_params` injection to protect framework/user params from LiteLLM's incomplete provider capability declarations | ✅ |
| model_capability.py | Core | Model capability detection for reasoning_content echo-back requirements (MiMo, DeepSeek, Kimi/Moonshot) | ✅ |
| concurrency.py | Core | Concurrency gate — per-model and global asyncio semaphores | ✅ |
| converters.py | Core | Bidirectional message format conversion (LangChain ↔ LiteLLM) with explicit message-name preservation | ✅ |
| metrics.py | Core | Empty response retry metrics tracking | ✅ |
| safety_termination_detector.py | Core | Detects provider safety terminations and suppresses truncated tool_calls to prevent corrupt dispatch | ✅ |
| schema_normalizer.py | Core | Tool schema normalizer for OpenAI-compatible providers | ✅ |
| stream_aggregator.py | Core | Stream data aggregation & XML tag purging — eliminates sync/async stream duplication | ✅ |
| streaming.py | Core | Streaming response parsing, incremental tool call merging | ✅ |
| tool_call_parsers.py | Core | Unified tool call format parsing for multiple LLMs (incl. XML and DeepSeek DSML) | ✅ |
| tool_recovery.py | Core | Cross-provider tool call argument recovery with fallback strategies | ✅ |

## Key Dependencies

- `infra`
- `observability`
- `utils`
