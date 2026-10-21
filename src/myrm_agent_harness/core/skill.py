"""Skill declaration domain primitives shared by backends/ and toolkits/.

[INPUT]
- (none — pure constants)

[OUTPUT]
- DEFAULT_ALLOWED_TOOLS: Default ``allowed-tools`` allow-list for a compiled skill

[POS]
Framework-agnostic skill domain. Lives in ``core/`` so both the ``backends/``
workflow compiler and ``toolkits/`` consumers share one SSOT without a
toolkits→backends dependency. The list is a static domain constant (it changes
only when the built-in capability set changes), so it belongs here rather than
in the higher-churn ``backends/`` compiler.
"""

from __future__ import annotations

# Default ``allowed-tools`` for a compiled skill. Every entry MUST be a name registered in
# ``agent.tool_management.tool_layers``: skill attenuation *removes* any tool absent from a
# skill's declared ``allowed_tools`` union, so a stale name here silently strips that capability
# from the agent on every turn the skill is active. ``bash_code_execute_tool`` and
# ``file_write_tool`` are intentionally declared — attenuation still intersects the declaration
# with the trust ceiling, so declaring an elevated tool never grants it to an INSTALLED skill.
DEFAULT_ALLOWED_TOOLS: tuple[str, ...] = (
    "browser_navigate_tool",
    "browser_interact_tool",
    "browser_snapshot_tool",
    "browser_extract_tool",
    "bash_code_execute_tool",
    "file_read_tool",
    "file_write_tool",
    "web_fetch_tool",
)

__all__ = ["DEFAULT_ALLOWED_TOOLS"]
