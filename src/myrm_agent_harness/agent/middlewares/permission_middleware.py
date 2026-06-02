"""Permission Check Middleware

工具执行前的权限验证中间件。

使用loaded_skills ContextVar追踪会话中加载的skills，
对所有loaded skills进行权限检查。

[INPUT]

[OUTPUT]
- PermissionCheckMiddleware: Agent middleware for runtime permission validation

[POS]
Permission check middleware (framework layer). Decoupled from the business layer via callback mechanism.

"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class PermissionCheckMiddleware(AgentMiddleware[Any, Any]):
    """Permission check middleware for Skill tool calls.

    Uses loaded_skills ContextVar to track skills in current session.
    For each tool call, checks if ANY loaded skill has permission to execute it.

    Design rationale:
    - Skills are prompt injections (SKILL.md in system prompt)
    - Cannot precisely attribute tool calls to specific skills
    - Conservative approach: if ANY loaded skill is granted the permission, allow
    - Fail-closed: if no loaded skills, allow by default (tool may be from main prompt)

    Business layer provides a permission_checker function that:
    - Queries granted permissions from database
    - Calls framework-layer validation
    - Logs permission usage
    """

    def __init__(self, permission_checker: Callable[[str, str, str], tuple[bool, str]] | None = None):
        """Initialize permission check middleware.

        Args:
            permission_checker: Function that checks permissions
                (skill_id, permission_type, operation) -> (allowed, reason)
                If None, permission checks are skipped (fallback for compatibility)
        """
        self._permission_checker = permission_checker

    async def on_tool_start(self, tool: str, input_str: str, **kwargs: object) -> str | None:
        """Check permission before tool execution.

        Checks all loaded skills in current session. If ANY skill has permission,
        allows the tool call.

        Returns error message if permission denied, None if allowed.
        """
        if not self._permission_checker:
            # No checker configured - allow by default
            return None

        # Get loaded skills from ContextVar
        try:
            from myrm_agent_harness.agent._skill_agent_context import get_loaded_skills

            loaded_skills = get_loaded_skills()
        except Exception as e:
            logger.warning("Failed to get loaded skills: %s", e)
            return None

        if not loaded_skills:
            # No skills loaded - allow by default (tool may be from main prompt)
            return None

        # Extract permission type from tool name
        permission_type = self._infer_permission_type(tool)
        if not permission_type:
            # Tool doesn't require permission check
            return None

        # Check if ANY loaded skill has permission
        for skill in loaded_skills:
            skill_id = skill.storage_skill_id or skill.name
            allowed, _reason = self._permission_checker(skill_id, permission_type, input_str)

            if allowed:
                # At least one skill has permission - allow
                logger.debug("Permission granted: skill=%s, permission=%s, tool=%s", skill_id, permission_type, tool)
                return None

        # No loaded skill has permission - deny
        skill_ids = [s.storage_skill_id or s.name for s in loaded_skills]
        logger.warning(
            f"Permission denied: tools={tool}, permission={permission_type}, "
            f"loaded_skills={skill_ids}, none have required permission"
        )
        return (
            f"Permission denied: This operation requires {permission_type} permission. "
            f"None of the loaded skills ({', '.join(skill_ids)}) have been granted this permission."
        )

    def _infer_permission_type(self, tool_name: str) -> str | None:
        """Infer permission type from tool name.

        Maps tool names to permission types (e.g., "file_read_tool" -> "file_read").
        Returns None for tools that don't require permission checks.
        """
        # Common tool name patterns
        tool_lower = tool_name.lower()

        if "file" in tool_lower and "read" in tool_lower:
            return "file_read"
        if "file" in tool_lower and ("write" in tool_lower or "create" in tool_lower):
            return "file_write"
        if "file" in tool_lower and "delete" in tool_lower:
            return "file_delete"
        if "shell" in tool_lower or "bash" in tool_lower or "execute" in tool_lower:
            return "shell_exec"
        if "code" in tool_lower and "interpreter" in tool_lower:
            return "code_interpreter"
        if "browser" in tool_lower or "web" in tool_lower or "fetch" in tool_lower:
            return "network_access"
        if "env" in tool_lower:
            return "env_var_access"

        # No permission mapping found
        return None


__all__ = ["PermissionCheckMiddleware"]


# Implementation notes:
#
# Skills are prompt injections (SKILL.md content injected into system prompt).
# The Agent cannot precisely attribute a tool call to a specific skill because:
# 1. Skills influence LLM's decision-making through prompt context
# 2. LLM makes autonomous decisions about which tools to use
# 3. A tool call may be influenced by multiple loaded skills
#
# Therefore, this middleware uses a conservative approach:
# - Track all loaded skills in the session (via loaded_skills ContextVar)
# - For each tool call, check if ANY loaded skill has the required permission
# - If yes: allow (at least one skill is authorized)
# - If no: deny (no authorized skill in session)
# - If no skills loaded: allow (tool call from main prompt, not skill-triggered)
#
# This design balances security (permission enforcement) with usability (don't
# block legitimate tool calls from enabled+authorized skills).
