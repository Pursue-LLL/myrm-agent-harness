# mcp_server/

## Overview

MCP adapter that exposes `MemoryManager` to external agents (Claude Code, Cursor, Codex) as four
tools: `memory_recall`, `memory_list`, `memory_store`, `memory_manage`. `MemoryMCPServer` registers
one tool per module; the manager is resolved per request (ContextVar binding → optional resolver →
default manager). Recalled bodies are sanitized and followed by a static untrusted advisory.

Distinct from [../mcp/](../mcp/_ARCH.md) (ai-memory wire-format interoperability gateway).
Parent index: [../_ARCH.md](../_ARCH.md). System design: [../../MEMORY_SYSTEM.md](../../MEMORY_SYSTEM.md).

## File Index

| File | Role | Description | I/O/P |
| --- | --- | --- | --- |
| `__init__.py` | Facade | Public entry: `MemoryMCPServer`, `create_memory_mcp_server`, per-request context setters. | ✅ |
| `server.py` | Core | `MemoryMCPServer` (tool registration, manager resolution, Streamable HTTP app) and its factory. | ✅ |
| `request_context.py` | Util | ContextVar bindings for the request's `MemoryManager` and the wiki-boundary flag. | ✅ |
| `common.py` | Util | `CATEGORY_TO_TYPE`, `parse_string_list`, `ManagerResolver`. | ✅ |
| `recall_tool.py` | Core | `memory_recall`: semantic search, profile lookup, budgeted and sanitized rendering. | ✅ |
| `list_tool.py` | Core | `memory_list`: category overview and paginated enumeration. | ✅ |
| `store_tool.py` | Core | `memory_store`: validation, wiki boundary, per-category writes. | ✅ |
| `manage_tool.py` | Core | `memory_manage`: rate / delete / update / correct of existing memories. | ✅ |

## Key Dependencies

- `../_memory_agent_tool_descriptions.py` (store/manage descriptions, `surface="mcp"`)
- `../memory_recall_formatting.py`, `../memory_recall_budget.py`, `../wiki_memory_boundary.py`, `../write_failure_feedback.py`
- `../../manager.py`, `../../types.py`
- External libraries: `mcp`, `starlette`
