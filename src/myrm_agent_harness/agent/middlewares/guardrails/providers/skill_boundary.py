"""Skill Boundary Provider.

Enforces parameter-aware boundaries for loaded skills.
"""

import logging
from collections.abc import Callable

from myrm_agent_harness.agent.middlewares.guardrails.core import (
    GuardrailDecision,
    GuardrailProvider,
    GuardrailReason,
    GuardrailRequest,
)

logger = logging.getLogger(__name__)


class SkillBoundaryProvider(GuardrailProvider):
    """Provider that parses tool schema and enforces skill-specific boundaries.

    Provides parameter-aware isolation based on skill permissions.
    """

    name = "skill_boundary"

    def __init__(self, permission_checker: Callable[[str, str, str], tuple[bool, str]] | None = None):
        self._permission_checker = permission_checker

    def _infer_permission_type(self, tool_name: str) -> str | None:
        """Infer basic permission category from tool name."""
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
        return None

    def _extract_critical_params(self, tool_name: str, tool_input: dict[str, object]) -> str:
        """Extract schema-aware boundary parameters."""
        perm_type = self._infer_permission_type(tool_name)
        if perm_type in ("file_read", "file_write", "file_delete"):
            return str(tool_input.get("path", tool_input.get("filename", tool_input)))
        if perm_type in ("shell_exec", "code_interpreter"):
            return str(tool_input.get("command", tool_input.get("script", tool_input.get("code", tool_input))))
        if perm_type == "network_access":
            return str(tool_input.get("url", tool_input.get("query", tool_input)))
        return str(tool_input)

    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        if not self._permission_checker:
            return GuardrailDecision(allow=True)

        try:
            from myrm_agent_harness.agent._skill_agent_context import get_loaded_skills
            loaded_skills = get_loaded_skills()
        except Exception as e:
            logger.warning("Failed to get loaded skills: %s", e)
            return GuardrailDecision(allow=True)

        if not loaded_skills:
            return GuardrailDecision(allow=True)

        permission_type = self._infer_permission_type(request.tool_name)
        if not permission_type:
            return GuardrailDecision(allow=True)

        critical_input = self._extract_critical_params(request.tool_name, request.tool_input)

        for skill in loaded_skills:
            skill_id = skill.storage_skill_id or skill.name
            allowed, _reason = self._permission_checker(skill_id, permission_type, critical_input)
            if allowed:
                return GuardrailDecision(allow=True)

        skill_ids = [s.storage_skill_id or s.name for s in loaded_skills]
        return GuardrailDecision(
            allow=False,
            reasons=[
                GuardrailReason(
                    code="skill_boundary.violation",
                    message=f"None of the loaded skills {skill_ids} have {permission_type} permission for target: {critical_input}"
                )
            ]
        )

    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        return self.evaluate(request)
