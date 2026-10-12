# memory_agent_tools/

## Overview

LangChain tools the agent uses to read and write memory: `memory_search_tool` (unified read plane
over memory / wiki / sessions), `memory_save_tool` and `memory_manage_tool`. Each tool is built by
a `build_*` function bound to one `MemoryManager`; `create_memory_tools` assembles them.

Parent index: [../_ARCH.md](../_ARCH.md). System design: [../../MEMORY_SYSTEM.md](../../MEMORY_SYSTEM.md).

## File Index

| File | Role | Description | I/O/P |
| --- | --- | --- | --- |
| `__init__.py` | Facade | Public entry: `create_memory_tools`, `CATEGORY_TO_TYPE`. | ✅ |
| `factory.py` | Core | `create_memory_tools`: recall-mode gate, policy/backends defaults, tool assembly. | ✅ |
| `search_tool.py` | Core | `memory_search_tool`: corpus resolution, drill-down, profile lookup, section assembly. | ✅ |
| `save_tool.py` | Core | `memory_save_tool` + `MemorySaveInput`: wiki/transient rejection, session buffering vs approval-queue writes per category. | ✅ |
| `manage_tool.py` | Core | `memory_manage_tool` + `MemoryManageInput`: rate/delete/update/correct/discard of existing memories (protected memories refused). | ✅ |
| `common.py` | Util | `CATEGORY_TO_TYPE` mapping and `parse_string_list` argument normaliser. | ✅ |

## Key Dependencies

- `../memory_search_policy.py`, `../memory_search_execution.py`, `../memory_recall_*.py`, `../tool_result_sources.py`
- `../wiki_memory_boundary.py`, `../transient_fact_boundary.py`, `../write_failure_feedback.py`
- `../_memory_agent_tool_descriptions.py` (LLM-visible descriptions, injected by `factory.py`)
- `../../manager.py`, `../../session.py`, `../../types.py`
