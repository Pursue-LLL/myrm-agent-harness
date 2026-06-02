# hooks/

## Overview
User-configurable lifecycle hook system. Complements middlewares (framework-internal safety logic) by providing external extension points without source code modification.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | User-configurable lifecycle hook system. Complements middlewares (framework-internal safety logic) b | — |
| executor.py | Core | Hook execution layer. Manages hook registration and execution with ContextVar-based session isolatio | ✅ |
| output_spiller.py | Core | Hook output spiller. Prevents oversized hook outputs (>2500 tokens) from bloating context by writing to disk. | ✅ |
| graceful_shutdown.py | Core | Graceful shutdown manager. Handles SIGTERM/SIGINT signals, triggers graceful shutdown, and auto-save | ✅ |
| hot_reload.py | Core | Hook hot-reload watcher. Monitors JSON/YAML config file changes and auto-reloads hook definitions wi | ✅ |
| skill_parser.py | Core | SKILL.md Hook parser — extract hooks from Markdown frontmatter. | ✅ |
| tool_name_mapping.py | Core | Provides map_to_claude_tool_name, map_from_claude_tool_name, should_trigger_hook. | ✅ |
| types.py | Core | Hook type definitions. Defines all Hook-related data structures, consumed by executor.py and integra | ✅ |
| webhook.py | Core | SSRF defense-in-depth utilities for webhook hooks. | ✅ |

## Key Dependencies

- `toolkits`
- `utils`
