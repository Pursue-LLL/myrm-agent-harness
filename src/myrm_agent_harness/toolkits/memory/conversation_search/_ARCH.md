# conversation_search/

## Overview
Framework-level conversation recall toolkit. Provides `ConversationSearchProtocol`, shared formatting helpers, and an optional standalone `conversation_search_tool` factory. GeneralAgent uses `memory_search_tool(corpus=sessions)` instead of mounting this tool at Turn1.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public exports for conversation recall. | — |
| `types.py` | Core | Conversation search DTOs, limits, scope/lineage request fields and source reference contracts. | ✅ |
| `format_output.py` | Core | Shared hit formatting and `conversation_history` sources emission. | ✅ |
| `tool.py` | Core | Standalone `conversation_search_tool` factory for harness unit tests; product path uses `memory_search_tool(corpus=sessions)`. | ✅ |
| `memory_provider.py` | Core | Default `MemoryManager` provider for framework users, including recent-mode browsing. | ✅ |

## Key Dependencies

- `myrm_agent_harness.toolkits.memory.manager`
- `myrm_agent_harness.toolkits.memory.protocols.conversation_search`
