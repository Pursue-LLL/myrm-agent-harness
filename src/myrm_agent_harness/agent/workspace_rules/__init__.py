"""Workspace rules — project-level context file discovery and injection.

Provides two mechanisms for workspace rule file support:

1. **Startup injection** (middleware.py): Scans workspace root for rule files
   (AGENTS.md, CLAUDE.md, SOUL.md, MEMORY.md, .cursorrules, .clinerules,
   .myrm.md, .hermes.md, HERMES.md, .windsurfrules, .myrm/rules/*.md,
   .cursor/rules/*.mdc, .claude/CLAUDE.md, .github/copilot-instructions.md)
   and injects them as a SystemMessage on the first LLM call. Position:
   after user_instructions, before memory_context — optimized for KV Cache
   prefix stability.

2. **Progressive discovery** (tracker.py): Monitors tool call arguments for
   file/directory paths. When a new directory is accessed, checks for rule
   files (including .claude/CLAUDE.md, .github/copilot-instructions.md) and
   appends their content to the tool result (not the system prompt).

[INPUT]
- scanner.py: Rule file discovery and loading
- middleware.py: LLM middleware for startup injection
- tracker.py: Progressive subdirectory discovery

[OUTPUT]
- workspace_rules_middleware: AgentMiddleware instance for startup injection
- scan_workspace_rules(): Manual scan function
- RuleFile: Rule file data class
- check_and_append_rules(): POST-CALL hook for tracker
- init_subdirectory_tracker(): Initialize session tracker
- reset_subdirectory_tracker(): Reset session tracker

[POS]
Workspace rules module. Two-layer context file support: startup injection
via middleware and progressive subdirectory discovery via tool interception.
"""

from myrm_agent_harness.agent.workspace_rules.middleware import (
    workspace_rules_middleware,
)
from myrm_agent_harness.agent.workspace_rules.scanner import (
    RuleFile,
    scan_workspace_rules,
)
from myrm_agent_harness.agent.workspace_rules.tracker import (
    check_and_append_rules,
    init_subdirectory_tracker,
    reset_subdirectory_tracker,
)

__all__ = [
    "RuleFile",
    "check_and_append_rules",
    "init_subdirectory_tracker",
    "reset_subdirectory_tracker",
    "scan_workspace_rules",
    "workspace_rules_middleware",
]
