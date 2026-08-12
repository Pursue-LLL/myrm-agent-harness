"""Skill Boundary Provider.

Enforces parameter-aware boundaries for loaded skills.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.middlewares.guardrails.core import (
    GuardrailDecision,
    GuardrailProvider,
    GuardrailReason,
    GuardrailRequest,
)

if TYPE_CHECKING:
    from myrm_agent_harness.agent.skills import SkillMetadata

logger = logging.getLogger(__name__)

#: Checker signature: (skill_id, permission_type, operation) -> (allowed, reason)
#: Async checker functions are awaited automatically; sync callables are supported
#: for sync tool paths.
PermissionChecker = Callable[[str, str, str], tuple[bool, str] | Awaitable[tuple[bool, str]]]


class SkillBoundaryProvider(GuardrailProvider):
    """Provider that parses tool schema and enforces skill-specific boundaries.

    Provides parameter-aware isolation based on skill permissions.
    """

    name = "skill_boundary"

    def __init__(
        self,
        permission_checker: PermissionChecker | None = None,
    ):
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

    def _extract_critical_params(
        self, tool_name: str, tool_input: dict[str, object]
    ) -> str:
        """Extract schema-aware boundary parameters."""
        perm_type = self._infer_permission_type(tool_name)
        if perm_type in ("file_read", "file_write", "file_delete"):
            return str(tool_input.get("path", tool_input.get("filename", tool_input)))
        if perm_type in ("shell_exec", "code_interpreter"):
            return str(
                tool_input.get(
                    "command",
                    tool_input.get("script", tool_input.get("code", tool_input)),
                )
            )
        if perm_type == "network_access":
            return str(tool_input.get("url", tool_input.get("query", tool_input)))
        return str(tool_input)

    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        if not self._permission_checker:
            return GuardrailDecision(allow=True)

        return asyncio.run(self._evaluate_skills(request, self._invoke_async))

    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        if not self._permission_checker:
            return GuardrailDecision(allow=True)

        return await self._evaluate_skills(request, self._invoke_async)

    async def _invoke_async(
        self, skill_id: str, permission_type: str, critical_input: str
    ) -> tuple[bool, str]:
        """Resolve the permission checker result, awaiting async checkers.

        Sync checkers (e.g. ``asyncio.run`` wrappers) are invoked directly and
        must not be called from a running event loop; the async tool path always
        routes through :meth:`aevaluate` which awaits async checkers.
        """
        checker = self._permission_checker
        if checker is None:
            return True, ""
        result = checker(skill_id, permission_type, critical_input)
        if inspect.isawaitable(result):
            return await result
        return result

    def _resolve_loaded_skills(self) -> list[SkillMetadata]:
        """Return skills loaded in the current session (empty on failure → allow)."""
        try:
            from myrm_agent_harness.agent.skill_agent.context import get_loaded_skills

            return get_loaded_skills()
        except Exception as e:
            logger.warning("Failed to get loaded skills: %s", e)
            return []

    async def _evaluate_skills(
        self,
        request: GuardrailRequest,
        invoke: Callable[[str, str, str], Awaitable[tuple[bool, str]]],
    ) -> GuardrailDecision:
        """Enforce permission boundaries across loaded skills.

        A tool call is allowed when any loaded skill has been granted the
        inferred permission type for the target operation, or when no skill is
        loaded / the tool has no permission mapping.
        """
        loaded_skills = self._resolve_loaded_skills()
        if not loaded_skills:
            return GuardrailDecision(allow=True)

        permission_type = self._infer_permission_type(request.tool_name)
        if not permission_type:
            return GuardrailDecision(allow=True)

        critical_input = self._extract_critical_params(
            request.tool_name, request.tool_input
        )

        for skill in loaded_skills:
            skill_id = skill.storage_skill_id or skill.name
            allowed, _reason = await invoke(skill_id, permission_type, critical_input)
            if allowed:
                return GuardrailDecision(allow=True)

        skill_ids = [s.storage_skill_id or s.name for s in loaded_skills]
        return GuardrailDecision(
            allow=False,
            reasons=[
                GuardrailReason(
                    code="skill_boundary.violation",
                    message=f"None of the loaded skills {skill_ids} have {permission_type} permission for target: {critical_input}",
                )
            ],
        )
