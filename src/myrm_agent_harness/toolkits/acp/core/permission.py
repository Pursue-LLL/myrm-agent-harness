"""Default permission manager for the ACP runtime system.

Provides the framework-level DefaultPermissionManager with 4 modes (safe, ask,
allow_all, bypass), tool allowlists with parameter-level wildcards, and
session-level approval caching. Business layer can replace via PermissionManager
Protocol.


[INPUT]
- myrm_agent_harness.toolkits.acp.types::PermissionDecision, PermissionMode (POS: ACP runtime type definitions)

[OUTPUT]
- DefaultPermissionManager: permission manager supporting 4 modes and tool allowlists

[POS]
ACP permission management layer. Provides framework-level permission control with safe/ask/allow_all/bypass
modes and parameter-level wildcard filtering.
"""

from __future__ import annotations

import fnmatch
import logging

from myrm_agent_harness.toolkits.acp.types import PermissionDecision, PermissionMode

logger = logging.getLogger(__name__)

_READ_TOOLS = frozenset(
    {
        "read",
        "search",
        "list",
        "glob",
        "grep",
        "find",
        "read_file",
        "read_text_file",
        "list_dir",
        "list_files",
    }
)


class DefaultPermissionManager:
    """Framework-provided permission manager.

    Supports 4 modes:
    - ``safe``: Only allow read operations.
    - ``ask``: Delegate to external decision (caller must handle the Future).
    - ``allow_all``: Auto-approve everything.
    - ``bypass``: Skip permission checks entirely (SDK handles permissions).

    Tool allowlists support parameter-level wildcards::

        allowed_tools = ["Read", "Bash(npm run *)", "Write(/src/*)"]

    Session-level approval caching: once a tool is approved with "always allow",
    subsequent requests for the same tool in the same session are auto-approved.
    """

    def __init__(
        self,
        mode: PermissionMode = "allow_all",
        allowed_tools: list[str] | None = None,
    ) -> None:
        self._mode = mode
        self._allowed_tools = allowed_tools or []
        self._approval_cache: dict[str, set[str]] = {}

    @property
    def mode(self) -> PermissionMode:
        return self._mode

    async def check(
        self,
        tool_name: str,
        tool_input: dict[str, object],
        session_id: str,
    ) -> PermissionDecision:
        """Check whether a tool invocation is permitted.

        For ``ask`` mode, this returns DENY_ONCE — the caller (runtime) should
        emit a permission_request event and await the Future instead.
        """
        if self._mode == "bypass":
            return PermissionDecision.ALLOW_ONCE

        if self._mode == "allow_all":
            return PermissionDecision.ALLOW_ONCE

        if self._is_cached_approval(tool_name, session_id):
            return PermissionDecision.ALLOW_ONCE

        if self._allowed_tools and self._matches_allowlist(tool_name, tool_input):
            return PermissionDecision.ALLOW_ONCE

        if self._mode == "safe":
            if self._is_read_tool(tool_name):
                return PermissionDecision.ALLOW_ONCE
            return PermissionDecision.DENY_ONCE

        # ask mode — signal that external decision is needed
        return PermissionDecision.DENY_ONCE

    def record_approval(self, tool_name: str, session_id: str) -> None:
        """Cache an "always allow" decision for a tool within a session."""
        if session_id not in self._approval_cache:
            self._approval_cache[session_id] = set()
        self._approval_cache[session_id].add(tool_name)

    def clear_session_cache(self, session_id: str) -> None:
        """Remove cached approvals for a session."""
        self._approval_cache.pop(session_id, None)

    # -- Internal --

    def _is_read_tool(self, tool_name: str) -> bool:
        normalized = tool_name.lower().replace("-", "_")
        return normalized in _READ_TOOLS

    def _is_cached_approval(self, tool_name: str, session_id: str) -> bool:
        session_approvals = self._approval_cache.get(session_id)
        if session_approvals is None:
            return False
        return tool_name in session_approvals

    def _matches_allowlist(self, tool_name: str, tool_input: dict[str, object]) -> bool:
        """Check if the tool invocation matches any allowlist entry.

        Supports patterns like:
        - ``"Read"`` — matches tool name exactly
        - ``"Bash(npm run *)"`` — matches tool name + first argument pattern
        - ``"Write(/src/*)"`` — matches tool name + path argument pattern
        """
        for pattern in self._allowed_tools:
            paren_idx = pattern.find("(")
            if paren_idx == -1:
                if pattern == tool_name:
                    return True
                continue

            pattern_name = pattern[:paren_idx]
            if pattern_name != tool_name:
                continue

            param_pattern = pattern[paren_idx + 1 :].rstrip(")")
            if not param_pattern:
                return True

            for value in tool_input.values():
                if isinstance(value, str) and fnmatch.fnmatch(value, param_pattern):
                    return True

        return False
