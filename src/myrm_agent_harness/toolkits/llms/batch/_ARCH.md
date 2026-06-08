# batch/

## Overview
Lightweight batch LLM-map primitive — one shared instruction over N items with bounded concurrency, per-item failure isolation, and prompt-cache-friendly System/Human split.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports `llm_map`, result types | — |
| llm_map.py | Core | `llm_map()` engine, `LlmMapReport`, `LlmMapItemResult` | ✅ |

## Module Dependencies

- `langchain_core.language_models::BaseChatModel`
- `infra.concurrency.limiter::ConcurrencyLimiter`
- `toolkits.llms.errors.resilient::resilient_llm_call`

## Division vs agent/meta_tools/llm_map/

| Package | Responsibility |
|---------|----------------|
| `toolkits/llms/batch/` | Pure engine (no agent/artifact deps) |
| `agent/meta_tools/llm_map/` | LangChain tool + vault spillover adapter |
