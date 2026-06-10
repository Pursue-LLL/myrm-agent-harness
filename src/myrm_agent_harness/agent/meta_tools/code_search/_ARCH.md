# code_search/

## Overview
Semantic code search meta-tool. Provides hybrid FTS5+Vector search over workspace source code.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public exports (create_code_search_tool) | — |
| tool.py | Core | Agent tool factory wrapping CodeIndexer | ✅ |

## Key Dependencies

- `myrm_agent_harness.toolkits.code_index` (CodeIndexer)
- `langchain.tools` (tool decorator)
