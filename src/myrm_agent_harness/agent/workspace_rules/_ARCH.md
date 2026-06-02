# workspace_rules/

## Overview
Workspace rules — project-level context file discovery and injection.

Two-layer mechanism:
1. **Startup injection** (`middleware.py`): Scans workspace root on first LLM call, injects rules as SystemMessage after `user_instructions`, before `memory_context`.
2. **Progressive discovery** (`tracker.py`): Monitors tool call arguments for directory paths, discovers rules in newly accessed subdirectories, appends to tool results.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public API exports for workspace rules module. | — |
| scanner.py | Core | Rule file discovery, security scanning, YAML frontmatter stripping, and loading. Supports AGENTS.md, CLAUDE.md, .cursorrules, .myrm.md, .hermes.md, HERMES.md, .windsurfrules, .myrm/rules/*.md, .cursor/rules/*.mdc, .claude/CLAUDE.md, .github/copilot-instructions.md. Traverses upward to git root (max 5 levels). inode-level dedup for case-insensitive filesystems. Head/tail truncation for large files. Blocked files (injection detected) return a `[BLOCKED]` placeholder RuleFile with `blocked=True` instead of being silently skipped. | ✅ |
| middleware.py | Core | AgentMiddleware for startup injection. Injects discovered rules as SystemMessage at KV Cache-optimal position (after user_instructions, before memory_context). One-time injection with marker detection. | ✅ |
| tracker.py | Core | SubdirectoryContextTracker for progressive rule discovery. Session-scoped via ContextVar. Extracts directory paths from tool call arguments, checks for rule files, appends content to tool results (not system prompt). Integrated via tool_interceptor_middleware POST-CALL stage. | ✅ |

## Key Dependencies

- `agent.security.detection.prompt_guard` — injection pattern scanning
- `agent.security.detection.content_boundary` — Unicode sanitization, marker neutralization
- `agent.middlewares._session_context` — workspace_root ContextVar
- `agent.middlewares.tool_interceptor_middleware` — POST-CALL integration for tracker
