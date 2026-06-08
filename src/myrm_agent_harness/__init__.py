"""Myrm Agent Harness - Professional Agent framework with advanced skill system.

This library provides a production-ready Agent framework built on LangChain/LangGraph,
featuring:
- Complete LangChain compatibility (astream, ainvoke, abatch)
- Advanced skill system with progressive disclosure
- MCP (Model Context Protocol) integration
- Flexible Protocol-based architecture
- Multi-level API design (zero-config to full control)

Quick Start:
    >>> from myrm_agent_harness.api import create_skill_agent, LLMConfig
    >>>
    >>> agent = await create_skill_agent(llm_config=LLMConfig(...))
    >>>
    >>> # LangChain standard API
    >>> async for chunk in agent.astream({"messages": [("user", "Hello!")]}):
    ...     print(chunk)
"""

from importlib import import_module

__version__ = "0.1.0rc2"

_EXPORTS: dict[str, tuple[str, str]] = {
    "SkillAgent": ("myrm_agent_harness.api.factory", "SkillAgent"),
    "create_skill_agent": ("myrm_agent_harness.api.factory", "create_skill_agent"),
    "LLMConfig": ("myrm_agent_harness.api.config", "LLMConfig"),
    "AgentRuntimeConfig": ("myrm_agent_harness.api.types", "AgentRuntimeConfig"),
    "AgentEventType": ("myrm_agent_harness.api.types", "AgentEventType"),
}

__all__ = [
    "AgentEventType",
    "AgentRuntimeConfig",
    "LLMConfig",
    "SkillAgent",
    "__version__",
    "create_skill_agent",
]


def __getattr__(name: str) -> object:
    """Lazily resolve public exports to keep package import lightweight."""
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(__all__ + [name for name in globals() if not name.startswith("_")]))
