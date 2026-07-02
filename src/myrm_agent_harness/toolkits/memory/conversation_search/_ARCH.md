# conversation_search/

## Overview
Framework-level conversation recall toolkit. It exposes a Protocol-backed `conversation_search_tool` tool that returns
stored snippets, summaries and UI-safe source references without business storage coupling or live LLM summarization.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public exports for conversation recall. | — |
| `types.py` | Core | Conversation search DTOs, limits, scope/lineage request fields and source reference contracts. | ✅ |
| `tool.py` | Core | Agent-callable `conversation_search_tool` factory；Server GeneralAgent 经 `conversation_search_setup` 注册为 eager。 | ✅ |
| `memory_provider.py` | Core | Default `MemoryManager` provider for framework users, including recent-mode browsing. | ✅ |

## Key Dependencies

- `myrm_agent_harness.toolkits.memory.manager`
- `myrm_agent_harness.toolkits.memory.protocols.conversation_search_tool`
