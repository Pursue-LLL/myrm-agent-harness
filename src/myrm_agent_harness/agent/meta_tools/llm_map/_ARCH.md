# llm_map/

## Overview
LangChain tool adapter for the `llm_map` batch engine. Agent-layer wrapper; pure engine lives in `toolkits/llms/batch/`.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports `create_llm_map_tool` | — |
| llm_map_tool.py | Core | `create_llm_map_tool()` — vault spillover, progress, cancellation via ContextVars | ✅ |

## Module Dependencies

- `toolkits.llms.batch.llm_map::llm_map` (POS: bounded concurrent map engine)
- `agent.artifacts.vault::ArtifactVault` (POS: large-result spillover store)
