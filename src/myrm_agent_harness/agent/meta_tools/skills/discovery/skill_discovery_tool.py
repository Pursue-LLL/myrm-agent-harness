"""Skill discovery meta-tool.

Provides Agent with abilities to search, install, uninstall skills
and install directly from GitHub URLs.

Uses SkillDiscoveryBackend Protocol for search/install/get_detail.
install_from_url and uninstall are optional capabilities injected
as callbacks from the business layer when available.

user_id is extracted at runtime from RunnableConfig context (framework pattern),
keeping the tool layer free from business concepts.

[INPUT]
- backends.skills.discovery_protocols::SkillDiscoveryBackend, (POS: SkillBackend SkillBackend SkillDiscoveryBackend)

[OUTPUT]
- create_skill_discovery_tool: Create the skill discovery tool.

[POS]
Skill discovery meta-tool.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Literal

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from myrm_agent_harness.agent.context_management.context import extract_context_from_runnable_config

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.backends.skills.discovery_protocols import SkillDiscoveryBackend, SkillInstallResult

TOOL_DESCRIPTION = """Search, install, and uninstall skills from external sources (GitHub, skills.sh, etc.).

Use this tool when:
- User asks "find me a skill for X" or "is there a skill that can..."
- User wants to extend agent capabilities with new skills
- User provides a GitHub URL to install a skill from
- User wants to uninstall a previously installed skill

Four actions:
1. action="search": Search for skills by keyword
2. action="install": Install a skill by ID and source (from search results)
3. action="install_from_url": Install a skill directly from a GitHub URL
4. action="uninstall": Uninstall a locally installed skill by ID

Important workflow:
- For search+install: ALWAYS search first, present results, ONLY install after user confirms
- For install_from_url: User provides a GitHub URL, you install directly
- For uninstall: Confirm with the user before uninstalling
"""

InstallFromUrlFn = Callable[[str, str], Coroutine[None, None, "SkillInstallResult"]]
UninstallFn = Callable[[str, str], Coroutine[None, None, "SkillInstallResult"]]


def _extract_user_id(config: RunnableConfig) -> str:
    """Extract user_id from RunnableConfig context (framework pattern)."""
    context = extract_context_from_runnable_config(config)
    uid = str(context.get("user_id", ""))
    if not uid:
        raise ValueError(
            "user_id is required in RunnableConfig context for skill operations. "
            "Business layer must set context['user_id']."
        )
    return uid


def create_skill_discovery_tool(
    discovery_backend: SkillDiscoveryBackend,
    *,
    install_from_url_fn: InstallFromUrlFn | None = None,
    uninstall_fn: UninstallFn | None = None,
) -> BaseTool:
    """Create the skill discovery tool.

    Args:
        discovery_backend: Skill discovery backend (Protocol injection)
        install_from_url_fn: Optional callback for direct URL install (business layer)
        uninstall_fn: Optional callback for uninstall (business layer)
    """

    class SkillDiscoveryInput(BaseModel):
        action: Literal["search", "install", "install_from_url", "uninstall"] = Field(
            description=(
                "Action: 'search' to find skills, 'install' to install by ID, "
                "'install_from_url' to install from GitHub URL, 'uninstall' to remove"
            )
        )
        query: str = Field(default="", description="Search keywords (required for action='search')")
        skill_id: str = Field(default="", description="Skill ID (required for 'install' and 'uninstall')")
        source: str = Field(default="", description="Skill source from search results (required for action='install')")
        url: str = Field(default="", description="GitHub URL or owner/repo (required for action='install_from_url')")

    @tool("skill_discovery_tool", description=TOOL_DESCRIPTION, args_schema=SkillDiscoveryInput)
    async def skill_discovery_func(
        action: str, query: str = "", skill_id: str = "", source: str = "", url: str = "", *, config: RunnableConfig
    ) -> str:
        """Search, install, and uninstall skills from external sources."""
        if action == "search":
            return await _handle_search(discovery_backend, query)

        user_id = _extract_user_id(config)
        if action == "install":
            return await _handle_install(discovery_backend, skill_id, source, user_id)
        elif action == "install_from_url":
            return await _handle_install_from_url(install_from_url_fn, url, user_id)
        elif action == "uninstall":
            return await _handle_uninstall(uninstall_fn, skill_id, user_id)
        return f"Unknown action: {action}. Use 'search', 'install', 'install_from_url', or 'uninstall'."

    return skill_discovery_func


async def _handle_search(backend: SkillDiscoveryBackend, query: str) -> str:
    if not query.strip():
        return "Error: 'query' is required for search action."

    results = await backend.search(query, limit=8)
    if not results:
        return f"No skills found for '{query}'. Try different keywords or describe your need differently."

    lines = [f"Found {len(results)} skill(s) for '{query}':\n"]
    for i, r in enumerate(results, 1):
        sr = r.result if hasattr(r, "result") else r
        stars_str = f" ({sr.stars} stars)" if getattr(sr, "stars", 0) > 0 else ""
        source_label = {
            "prebuilt": "Official",
            "github": "GitHub",
            "skills_sh": "Community",
            "clawhub": "ClawHub",
            "lobehub": "LobeHub",
        }.get(sr.source, sr.source)
        lines.append(
            f"{i}. **{sr.name}** [{source_label}]{stars_str}\n"
            f" {sr.description}\n"
            f' -> To install: skill_id="{sr.id}", source="{sr.source}"'
        )

    lines.append(
        "\nPresent these results to the user and ask which one they'd like to install. "
        "Only call install after user confirms."
    )
    return "\n".join(lines)


async def _handle_install(backend: SkillDiscoveryBackend, skill_id: str, source: str, user_id: str | None) -> str:
    if not skill_id or not source:
        return "Error: 'skill_id' and 'source' are required for install action."

    result = await backend.install(skill_id, source, user_id)

    if result.success:
        msg = (
            f"Successfully installed skill '{result.skill_name}'!\n"
            f" Path: {result.installed_path}\n"
            f" ID: {result.skill_id}\n"
        )
        if result.scan_summary:
            msg += f"\n    Security scan: {result.scan_summary}\n"
        msg += "\nThe skill is now available and will be used automatically when relevant."
        return msg
    return f"Installation failed: {result.error}"


async def _handle_install_from_url(install_fn: InstallFromUrlFn | None, url: str, user_id: str | None) -> str:
    if not url.strip():
        return "Error: 'url' is required for install_from_url action."

    if install_fn is None:
        return "Error: Direct URL installation is not supported by this backend."

    result = await install_fn(url, user_id)

    if result.success:
        msg = (
            f"Successfully installed skill '{result.skill_name}' from URL!\n"
            f" Path: {result.installed_path}\n"
            f" ID: {result.skill_id}\n"
        )
        if result.scan_summary:
            msg += f"\n    Security scan: {result.scan_summary}\n"
        msg += "\nThe skill is now available and will be used automatically when relevant."
        return msg
    return f"Installation from URL failed: {result.error}"


async def _handle_uninstall(uninstall_fn: UninstallFn | None, skill_id: str, user_id: str | None) -> str:
    if not skill_id.strip():
        return "Error: 'skill_id' is required for uninstall action."

    if uninstall_fn is None:
        return "Error: Uninstall is not supported by this backend."

    result = await uninstall_fn(skill_id, user_id)

    if result.success:
        return f"Successfully uninstalled skill '{result.skill_name}'."
    return f"Uninstall failed: {result.error}"
